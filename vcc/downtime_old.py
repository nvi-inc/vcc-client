from datetime import datetime
import sys

from PyQt5.QtGui import QFont, QCursor, QFontDatabase
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QMainWindow, QApplication, QWidget, QLayout, QLineEdit
from PyQt5.QtWidgets import QLabel, QVBoxLayout, QHBoxLayout, QGroupBox, QGridLayout, QPushButton, QPlainTextEdit

from vcc import settings, VCCError, json_decoder
from vcc.server import VCC


# Class for dashboard application
class DownTimeWnd(QMainWindow):

    def __init__(self, sta_id, name, group):

        self.vcc = VCC('DB')

        self.app = QApplication(sys.argv)

        self.network, self.sefds = [], {}
        self.timer = None

        self.session = self.get_session(ses_id)

        self.network = self.session.network
        self.station_scans = {}
        self.messenger = None
        self._get_ses = self._get_skd = self._after_get_schedule = None

        super().__init__()

        self.setWindowFlags(Qt.WindowCloseButtonHint | Qt.WindowMinimizeButtonHint)
        self.setWindowTitle(f'Downtime for {self.sta_id.capitalize()} - {self.station["name"]}')
        self.resize(700, 100)

        # Make Application layout
        self.utc_display = QLabel('')
        self.station_box = QLabel()
        self.start_box = make_text_box(self.session.start.strftime('%Y-%m-%d %H:%M'))
        self.start_status = QLabel('')
        self.version_box = make_text_box(self.session.sched_version, fit=False)
        self.messages = make_text_box('Not monitoring', fit=False)

        widget = QWidget()
        self.Vlayout = QVBoxLayout()
        self.Vlayout.addLayout(self.make_session_box())
        self.Vlayout.addLayout(self.make_monit_box())
        self.Vlayout.addLayout(self.make_footer_box())
        widget.setLayout(self.Vlayout)
        self.setCentralWidget(widget)

        self.init_pos()
        self.show()
        self.start()

    # Start application timer and messenger for message monitoring
    def start(self):
        # Start timer to update information
        self.timer = Timer(self.on_timer)
        self.timer.start()

        # Request schedule and request SEFDs after
        self.get_schedule(self.get_sefds)

        # Start messenger
        try:
            self.messenger = Messenger(self.vcc, self.process_messages, ses_id=self.session.code)
            self.messenger.start()
        except Exception as exc:
            ErrorMessage(self.full_name, f'Could not start messenger\n{str(exc)}')

    # Set initial position for interface
    def init_pos(self):
        if hasattr(settings, 'Positions'):
            self.move(settings.Positions.x, settings.Positions.y)

    def get_session(self, ses_id):
        try:
            rsp = self.vcc.get_api().get(f'/sessions/{ses_id}')
            if not rsp:
                raise VCCError(f'{ses_id} not found')
            return Session(json_decoder(rsp.json()))
        except VCCError as exc:
            ErrorMessage(self.full_name, str(exc), critical=True)
            sys.exit(0)

    # Make footer with buttons and timer
    def make_footer_box(self):
        hbox = QHBoxLayout()
        # Add Done button
        cancel = QPushButton("Done")
        cancel.clicked.connect(self.close)
        hbox.addWidget(cancel)
        hbox.addStretch(1)
        # Add a display for UTC time
        hbox.addWidget(self.utc_display)
        hbox.setContentsMargins(10, 5, 15, 5)
        hbox.setSizeConstraint(QLayout.SetNoConstraint)
        return hbox

    # Make box displaying session information
    def make_session_box(self):
        groupbox = QGroupBox(self.session.code.upper())
        groupbox.setStyleSheet("QGroupBox { font-weight: bold; } ")

        box = QGridLayout()
        box.addWidget(QLabel('Stations'), 0, 0)

        self.station_box.setStyleSheet("border: 1px solid grey;padding :3px;border-radius : 2;background-color: white")
        self.update_station_box()
        box.addWidget(self.station_box, 0, 1, 1, 5)

        box.addWidget(QLabel('Start time'), 1, 0)
        box.addWidget(self.start_box, 1, 1, 1, 2)

        box.addWidget(self.start_status, 1, 3, 1, 3)

        box.addWidget(QLabel('Schedule'), 2, 0)
        box.addWidget(self.version_box, 2, 1, 1, 2)
        #box.addWidget(QPushButton('Make SKD'), 2, 5)

        groupbox.setLayout(box)
        grid = QGridLayout()
        grid.addWidget(groupbox)

        return grid

    # Update information in station box using red for not schedule stations
    def update_station_box(self):
        scheduled = sorted(self.session.schedule.observing if self.session.schedule else self.session.network)
        removed = sorted([sta for sta in self.session.network if sta not in scheduled])
        txt = "<font color='black'>{}{}</font>".format(', '.join(scheduled), ', ' if removed else '')
        if removed:
            txt += "<font color='red'>{}</font>".format(', '.join(removed))
        self.station_box.setText(txt)

    # Update session box with schedule version
    def update_session_box(self):
        self.update_station_box()
        self.start_box.setText(self.session.start.strftime('%Y-%m-%d %H:%M'))
        self.version_box.setText(self.session.sched_version)


class Downtime:
    select_one = 'Select...'

    def __init__(self, sta_id):

        self.sta_id = sta_id
        self.station, self.codes = None, []
        self.downtime = []

        self.last_row, self.records = 0, []

        for group_id in ['CC', 'NS', 'OC', 'AC', 'CO', 'DB']:
            if hasattr(settings.Signatures, group_id):
                self.group_id = group_id
                break
        else:
            raise VCCError('No valid groups in configuration file')
        self.can_update = (self.group_id == 'CC') or \
                          (self.group_id == 'NS' and settings.Signatures.NS[0].lower() == sta_id.lower())

    def get_information(self):
        try:
            with VCC(self.group_id) as vcc:
                api = vcc.get_api()
                rsp = api.get(f'/stations/{self.sta_id}')
                if not rsp:
                    raise VCCError(rsp.text)
                self.station = json_decoder(rsp.json())
                rsp = api.get(f'/downtime/')
                if not rsp:
                    raise VCCError(rsp.text)
                self.codes = rsp.json()
                rsp = api.get(f'/downtime/{self.sta_id}')
                print(rsp, rsp.text)
                records, today = json_decoder(rsp.json()) if rsp else [], datetime.utcnow()
                self.downtime = [rec for rec in records if not rec['end'] or rec['end'] >= today]
            return
        except VCCError as exc:
            print(f'Failed to get information for {self.sta_id}! [{str(exc)}]')

    def show(self):
        def open_date_entry(widget, event):
            print('open_date_entry', event)
            x, y = event.x, event.y
            print(widget.state(), type(widget.identify(x, y)), widget.identify(x, y))
            if 'disabled' not in widget.state() and widget.identify(x, y) == 'Combobox.button':
                print('calling drop_down')
                widget.state(['pressed'])
                widget.drop_down()

        def string_edited(row_id, name):
            has_changed(row_id, name)

        def selection_changed(row_id, name):
            def new_selection(selection):
                if row_id + 1 == self.last_row and selection != self.select_one:
                    record = self.records[row_id]
                    for item in ['start', 'end', 'comment_entry']:
                        record[item]['state'] = 'normal'
                    record['start'].config(mindate=get_min_date())
                    record['start'].focus_set()
                    add_row(self.last_row + 1, '', '', '', '', new_row=True)
                has_changed(row_id, name)

            return new_selection

        def get_min_date():
            val = datetime.now().date()
            for record in self.records:
                val = max(get_date(record['end'], val), val)
            return val

        def get_date(widget, default=''):
            try:
                return widget.get_date()
            except IndexError:
                return default

        def has_changed(index, name):
            print('has_changed', index, name)
            if name == 'TESTING':
                return
            record = self.records[index]
            print(record)
            # if name == 'end':
            #    record['end'].config(mindate=record['start'].get_date())
            # if record['end'].get_date() < record['start'].get_date():
            #    record['end'].set_date(record['start'].get_date())
            value = record[name].get_date() if name in ['start', 'end'] else record[name].get()
            print(name, index, len(self.downtime))
            if index >= len(self.downtime) or value != self.downtime[index][name]:
                record['update']['state'] = "normal"

        def make_date_entry(name, date, row_id, col_id, state, min_date=None):
            ymd = {'year': date.year, 'month': date.month, 'day': date.day} if date else {}
            widget = DateEntry(wnd, selectmode='day', **ymd, showweeknumbers=False, firstweekday='sunday')
            widget.bind("<<DateEntrySelected>>", lambda ev, r=row_id - 1, n='TESTING': has_changed(r, n))
            widget.bind("<FocusOut>", lambda ev, r=row_id - 1, n=name: has_changed(r, n))
            widget.bind('<ButtonPress-1>', lambda ev: open_date_entry(widget, ev))
            widget.grid(row=row_id, column=col_id)
            if min_date:
                widget.config(mindate=min_date)
            if not date:
                widget.delete(0, 'end')
            Pmw.Balloon(wnd).bind(widget, "Click arrow to open Calendar\nMacOS: use double click")
            widget['state'] = state
            return widget

        # Add new row in interface
        def add_row(index, reason, start, end, comment, new_row=False):
            tk.Grid.rowconfigure(wnd, index, weight=1)
            # Reason
            var = tk.StringVar(value=self.select_one if new_row else reason)
            menu = tk.OptionMenu(wnd, var, *self.codes, command=selection_changed(index - 1, 'reason'))
            menu.grid(row=index, column=0, sticky="nsew")
            menu.config(takefocus=1)
            menu['state'] = 'normal' if new_row else 'disable'

            rec = {'reason': var, 'menu': menu,
                   'start': make_date_entry('start', start, index, 1, "disable", None),
                   'end': make_date_entry('end', end, index, 2, "disable" if new_row else "normal", start),
                   'comment': tk.StringVar(value=comment),
                   'status': tk.StringVar(value='' if new_row else 'Ok')
                   }
            self.records.append(rec)

            # Comment
            rec['comment'].trace("w", lambda name, k, mode, r=index - 1, n='comment': string_edited(r, n))
            rec['comment_entry'] = tk.Entry(wnd, width=50, textvariable=rec['comment'])
            rec['comment_entry'].grid(row=index, column=3, sticky="ew", pady=2)
            rec['comment_entry']['state'] = "disable" if new_row else "normal"
            # Update column
            rec['update'] = tk.Button(wnd, text='Update', state='disable', command=lambda: update_vcc(index-1))
            rec['update'].grid(row=index, column=4, sticky="nsew", padx=5, pady=5)

            self.last_row = index
            # Update button
            done.grid(row=self.last_row + 1, column=0, sticky="ew")
            tk.Grid.rowconfigure(wnd, self.last_row + 1, weight=2)

        def update_vcc(index):
            data = self.records[index]

            record = {'start': get_date(data['start']), 'end': get_date(data['end']),
                      'reason': data['reason'].get(), 'comment': data['comment'].get()}
            print(record)

            #if record:
            #    with VCC(self.group_id) as vcc:
            #        api = vcc.get_api()
            #        rsp = api.put(f'/downtime/{self.sta_id}', data=record)
            #        print(rsp.text)

            data['update']['state'] = "disable"

        wnd = tk.Tk()

        wnd.title(f'Downtime for {self.sta_id.capitalize()} - {self.station["name"]}')
        Pmw.initialise(wnd)

        # Display column names
        columns = {'Problem': 0, 'Start': 0, 'End': 0, 'Comment': 7, 'Status': 0}
        for col, (text, weight) in enumerate(columns.items()):
            wnd.columnconfigure(col, weight=weight)
            tk.Label(wnd, text=text, anchor="w").grid(row=0, column=col, sticky="w")
        done = tk.Button(wnd, text='Done', command=wnd.destroy)

        row = 0
        # Insert row for every downtime event
        for row, dt in enumerate(self.downtime, 1):
            add_row(row, dt['reason'], dt['start'], dt['end'], dt['comment'])
        add_row(self.last_row + 1, '', '', '', '', new_row=True)

        wnd.eval('tk::PlaceWindow . center')
        wnd.update()
        # run the app
        wnd.mainloop()

    def exec(self):
        self.get_information()

        if self.can_update:
            self.show()
        elif self.downtime:
            print(f'Scheduled downtime for {self.sta_id.capitalize()} - {self.station["name"]}')
            for dt in self.downtime:
                print(f'{dt["start"].strftime("%Y-%m-%d"):10s} '
                      f'{dt["end"].strftime("%Y-%m-%d") if dt["end"] else "Unknown":10s} '
                      f'{dt["reason"]:15s} {dt["comment"]}')
        else:
            print(f'NO scheduled downtime for {self.sta_id.capitalize()} - {self.station["name"]}')
