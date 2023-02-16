import sys
from datetime import datetime
from functools import partial
from subprocess import Popen, PIPE
import json
import traceback
import math

from PyQt5.QtGui import QFont, QCursor
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QMainWindow, QApplication, QWidget, QLayout, QLineEdit
from PyQt5.QtWidgets import QLabel, QVBoxLayout, QHBoxLayout, QGroupBox, QGridLayout, QPushButton, QPlainTextEdit

from vcc import settings, json_decoder, VCCError
from vcc.session import Session
from vcc.server import VCC

from vcc.processes import Timer, Get, MultiGet, ErrorMessage, make_text_box
from vcc.messenger import Messenger
from vcc.windows import StationMessage, SEFDs


class StatusWidget(QLineEdit):

    def __init__(self, sta_id):
        super().__init__()
        self.sta_id = sta_id
        self.setReadOnly(True)
        self.lines = [f'{datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")} - start log for {sta_id}']
        self.viewer = None
        self.setCursor(QCursor(Qt.PointingHandCursor))

    def mousePressEvent(self, event):
        if self.viewer:
            self.viewer.setPlainText('\n'.join(self.lines))
        else:
            self.viewer = QPlainTextEdit()
            #self.viewer.setFont(QFont('default_families', 9))  # monospace
            #f = QFontDatabase.FixedFont()
            self.viewer.setFont(QFont('Arial', 9))  # monospace
            self.viewer.setMinimumWidth(450)
            self.viewer.setWindowTitle(f'{self.sta_id} - events')
            self.viewer.setPlainText('\n'.join(self.lines))
            self.viewer.closeEvent = self.viewerCloseEvent
            self.viewer.show()

    def clean(self):
        if self.viewer:
            self.viewer.close()

    def add_text(self, utc, text):
        record = f'{utc.strftime("%Y-%m-%d %H:%M:%S - ")}{text}'
        self.lines.append(record)
        if self.viewer:
            self.viewer.appendPlainText(record)

    def viewerCloseEvent(self, event):
        self.viewer = None

    def setText(self, text, log_only=False):
        now = datetime.utcnow()
        self.add_text(now, text)
        if not log_only:
            super().setText(f'{now.strftime("%H:%M:%S - ")}{text}')


# Class for dashboard application
class Dashboard(QMainWindow):

    def __init__(self, ses_id):

        self.full_name = 'VLBI dashboard V0.1'
        self.vcc = VCC('DB')

        self.app = QApplication(sys.argv)

        self.network, self.sefds = [], {}
        self.timer = None

        self.session = self.get_session(ses_id)

        self.network = self.session.network
        self.station_scans = {}
        self.messenger = None
        self._get_ses = self._get_skd = self._after_get_schedule = None
        self._sefd_request = None

        super().__init__()

        self.setWindowFlags(Qt.WindowCloseButtonHint | Qt.WindowMinimizeButtonHint)
        self.setWindowTitle(self.full_name)
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

    # Process urgent message sent by a station
    def process_urgent(self, headers, data):
        sta_id = data.get('station', headers.get('sender', None))
        if sta_id and (sta_id.capitalize() in self.network):
            sta_id = sta_id.capitalize()
            for line in data['msg'].splitlines():
                self.update_station_log(sta_id, f'URGENT: {line}')
            StationMessage(self, headers, data)

    # Process master message send by the Operation centeer
    def process_master(self, headers, data):
        if data['session'].upper() == self.session.code:
            self.update_session()

    # Process schedule message indicating that new schedule is available
    def process_schedule(self, headers, data):
        self.get_schedule()

    # Process messages received from stations
    def process_sta_info(self, headers, data):
        sta_id = data.get('station', None)
        sta_id = sta_id.capitalize() if sta_id else headers.get('sender', '__').capitalize()

        ses_id = data.get('session', None)
        ses_id = ses_id.upper() if ses_id else headers.get('session', '__').upper()

        # Check if valid station and session id
        if sta_id not in self.network or (ses_id not in ['__', self.session.code.upper()]):
            print('DB Msg not process', sta_id, ses_id, self.network)
            return
        if 'sefd' in data:
            self.get_sefds(station=sta_id)
        elif 'status' in data:
            self.update_station_info(sta_id, 'Status', data['status'])
            self.update_scans(sta_id, data)
        elif 'schedule' in data:
            self.update_station_info(sta_id, 'Status', f'V{data["version"]} fetched')
            self.update_station_info(sta_id, 'Sched', f'V{data["version"]}')

    # Process messages received trough the messaging system
    def process_messages(self, headers, command):
        # Decode command
        if headers['format'] == 'json':
            command = json.loads(command)
            text = ', '.join([f'{key}={val}' for key, val in command.items()])
        else:
            text = command
        code = headers['code']
        msg, name = f'{code} {text}', f'process_{code}'
        self.messages.setText(msg)
        # Call function for this specific code
        if hasattr(self, name):
            getattr(self, name)(headers, command)
        # Acknowledge message
        self.messenger.acknowledge_msg()

    # Show the SEFDs in external window
    def show_sefds(self, sta_id):
        if sta_id in self.sefds and (sefd := self.sefds[sta_id].get('data', None)):
            self.sefds[sta_id]['wnd'] = wnd = SEFDs(self, sefd)
            wnd.show()

    # Local function to make Label
    def _make_L(self, sta, text):
        return QLabel(text)

    # Local function to make Label align center
    def _make_C(self, sta, text):
        label = QLabel(text)
        label.setAlignment(Qt.AlignCenter)
        return label

    # Local function to make a Text box
    def _make_T(self, sta, text):
        return StatusWidget(sta)

    # Local function to make PushButton with specific text
    def _make_B(self, sta, text):
        widget = QPushButton()
        widget.clicked.connect(partial(self.show_sefds, sta_id=sta))
        return widget

    # Add a row with many widget to display station information
    def add_station_row(self, row, sta):
        for key, info in self.header.items():
            txt = sta.capitalize() if key == 'Station' else ''
            widget = getattr(self, f'_make_{info[0]}')(sta, txt)
            self.station_info.addWidget(widget, row, info[1], 1, info[2])

    # Make the box that will be use to display information from stations
    def make_monit_box(self):

        self.station_info = QGridLayout()
        self.header = {'Station': ('L',0,1), 'Sched': ('L',1,1), 'SEFD': ('B',2,2), 'Scans': ('C',5,1), 'Status': ('T',6,4)}
        for label, info in self.header.items():
            self.station_info.addWidget(QLabel(label), 0, info[1])

        for row, sta in enumerate(self.session.network, 1):
            self.add_station_row(row, sta)

        groupbox = QGroupBox('Station Monitoring')
        groupbox.setStyleSheet("QGroupBox { font-weight: bold; } ")
        groupbox.setLayout(self.station_info)

        grid = QGridLayout()
        grid.addWidget(groupbox)
        return grid

    # Update a widget in a row
    def update_widget(self, row, col_name, text):
        #col = self.header[col_name][1]
        #self.station_info.itemAtPosition(row,col).widget().setText(text)
        self.get_widget(row, col_name).setText(text)

    # Update a widget in a row
    def get_widget_text(self, row, col_name):
        #col = self.header[col_name][1]
        #return self.station_info.itemAtPosition(row,col).widget().text()
        return self.get_widget(row, col_name).text()

    # Update a widget in a row
    def get_widget(self, row, col_name):
        col = self.header[col_name][1]
        item = self.station_info.itemAtPosition(row,col)
        return item.widget() if item else None

    # Get the rows associated with stations
    def get_station_list(self):
        stations = {}
        for row in range(1, self.station_info.rowCount()):
            if item := self.station_info.itemAtPosition(row,0):
                stations[item.widget().text()] = row
        return stations

    # Clean the box with station information
    def clean_monit_box(self, sched=False):
        # Reset monit information
        for row in range(len(self.network)+1, self.station_info.rowCount()):
            self.remove_monit_row(row)
        # Add new stations
        for row in range(self.station_info.rowCount()-1, len(self.network)):
            self.add_station_row(row+1, self.network[row])
        for row, info in enumerate(self.network, 1):
            sta, data = (info.capitalize(), None) if isinstance(info, str) else (info['sta'].capitalize(), info)
            self.update_monit_row(row, sta, data)

    # Check if a row has data
    def row_has_data(self, row):
        return bool(self.station_info.itemAtPosition(row,0))

    # Update station information
    def update_station_info(self, sta_id, col_name, text):
        for row in range(1, self.station_info.rowCount()):
            if item := self.station_info.itemAtPosition(row,0):
                if sta_id == item.widget().text():
                    self.update_widget(row, col_name, text)
                    return

    # Update station information
    def update_station_log(self, sta_id, text):
        for row in range(1, self.station_info.rowCount()):
            if item := self.station_info.itemAtPosition(row, 0):
                if sta_id == item.widget().text():
                    widget = self.get_widget(row, 'Status')
                    widget.setText(text, True)
                    return

    # Update station information
    def update_scans(self, sta_id, data):
        if 'scan_id' in data:
            for row in range(1, self.station_info.rowCount()):
                if item := self.station_info.itemAtPosition(row,0):
                    if sta_id == item.widget().text():
                        self.update_widget(row, 'Scans', f'{data["scan_id"]}/{self.station_scans[sta_id]}')
                        return

    # Remove row from stations
    def remove_monit_row(self, row):
        for col in range(self.station_info.columnCount()):
            if layout := self.station_info.itemAtPosition(row,col):
                layout.widget().deleteLater()
                self.station_info.removeItem(layout)

    # Start scheduler to make a new schedule
    def show_scheduler(self):
        command = f'{settings.Scripts.scheduler} {self.session.code}'
        prc = Popen(command, shell=True, stdin=PIPE, stdout=PIPE, stderr=PIPE)
        prc.communicate()

    # Update a row in the monit box
    def update_monit_row(self, row, sta, data):
        if not self.row_has_data(row):
            self.add_station_row(row, sta)

        self.update_widget(row, 'Station', sta)

        version = f'V{data["version"]}' if data and data['version'] else self.get_widget_text(row, 'Sched')
        self.update_widget(row, 'Sched', version if version else 'None')
        if data and 'nbr_scans' in data:
            self.station_scans[sta] = str(data['nbr_scans'])
            self.update_widget(row, 'Scans', str(data['nbr_scans']))
        if sta not in self.sefds:
            self.sefds[sta] = {'wnd': None , 'data': None}
        sefd = self.sefds[sta]['data']
        self.update_widget(row, 'SEFD', datetime.fromisoformat(sefd['observed']).strftime('%Y-%m-%d %H:%M') if sefd else 'No data')

    # Update the monit box
    def update_monit_box(self):
        network = self.session.schedule.scheduled if self.session.schedule else self.network
        rows = self.get_station_list()  # Get row for each stations
        for info in network:
            sta, data = (info.capitalize(), None) if isinstance(info, str) else (info['station'].capitalize(), info)
            if row := rows.get(sta, 0):
                self.update_monit_row(row, sta, data)

    # Update the text in the status box and icon
    def update_start_status(self):
        status = self.session.get_status()
        if status == 'waiting':
            dt = (self.session.start - datetime.utcnow()).total_seconds()
            if dt > 3600:
                hours, minutes = divmod(int(dt / 60), 60)
                dt_text = f'Starting in {hours:d} hour{"s" if hours > 1 else ""} and {minutes:02d} minutes'
            elif dt > 60:
                minutes = math.ceil(dt / 60)
                dt_text = f'Starting in {minutes:d} minute{"s" if minutes > 1 else ""}'
            else:
                seconds = math.ceil(dt)
                s = 's' if seconds > 1 else ''
                dt_text = f'Starting in {seconds:02d} second{"s" if seconds > 1 else ""}'

            color = 'black' if dt > 600 else 'red'
            text = "<font color='{}'>{}</font>".format(color, dt_text)
        else:
            text = "<font color='{}'>{}</font>".format('black', status.capitalize())

        self.start_status.setText(text)

    # Call at end of schedule
    def update_end_status(self):
        # done = self.session.waiting_done()
        # if done > 0:
        #    self.start_progress.setValue(done)
        pass

    # Process timer tick
    def on_timer(self):
        # Update utc
        self.utc_display.setText(datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC'))
        self.update_start_status()
        self.update_end_status()

    # Execute app
    def exec(self):
        sys.exit(self.app.exec_())

    # Called when window is closing
    def closeEvent(self, event):
        for row in range(1, self.station_info.rowCount()):
            if widget := self.get_widget(row, 'Status'):
                widget.clean()
        try:
            print('Close messenger')
            self.messenger.stop()
            print('Close timer')
            self.timer.stop()
            print('Closed ok')
        except Exception as err:
            print('Closed with problem')
            print(str(err))
            print(traceback.format_exc())

    #
    def msg_received(self, ch, method, properties, body):
        # close connection on receiving stop message
        ch.basic_ack(delivery_tag=method.delivery_tag)

    def update_session(self):
        self._get_ses = Get(self.vcc, f'/sessions/{self.session.code}')
        self._get_ses.on_finish(self.session.code, self.process_session_response)
        self._get_ses.start()

    def get_schedule(self, next=None):
        self._after_get_schedule = next
        self._get_skd = Get(self.vcc, f'/schedules/{self.session.code.lower()}', params={'select': 'summary'})
        self._get_skd.on_finish(self.session.code, self.process_schedule_response)
        self._get_skd.start()

    def process_session_response(self, ses_id, response, error):

        try:
            if response:
                self.session = Session(response.json())
                self.network = self.session.network
                self.update_session_box()
                self.clean_monit_box()
                self.get_schedule()
                return
        except VCCError as exc:
            error = str(exc)

        reason = error if error else 'Invalid data from VLBI Data Center'
        failure = f'Error requesting session {ses_id}'
        ErrorMessage(self.full_name, failure, reason, critical=True)

    # Receive schedule information and update interface
    def process_schedule_response(self, ses_id, response, error):

        try:
            if response:
                sched = response.json()
                self.session.update_schedule(sched)
                self.network = self.session.network
                self.update_session_box()
                self.clean_monit_box(sched=True)
                self.update_monit_box()
            if self._after_get_schedule:
                self._after_get_schedule()
        except VCCError:
            pass

    # Problem requesting schedule
    def error_sefds(self, error):
        ErrorMessage('Error requesting SEFD', error)

    # Request SEFDs in multi thread environment
    def get_sefds(self, station=None):
        requests, params = [], None
        if station and station in self.sefds:
            self.sefds[station]['data'] = None

        for sta_id in [station] if station else self.network:
            if sta_id not in self.sefds:
                self.sefds[sta_id] = {'wnd': None , 'data': None}
            if not self.sefds[sta_id]['data']:
                action = (sta_id, f'/data/onoff/{sta_id.lower()}', params)
                requests.append(action)

        # Use MultiGet to request information from VWS
        if requests:
            self._sefd_request = MultiGet(self.vcc)
            self._sefd_request.set_requests(requests, self.process_sefds, self.error_sefds, self.update_monit_box)
            self._sefd_request.start()

    # Receive SEFDs and update monit box
    def process_sefds(self, sta_id, response, error):
        try:
            if response:
                self.sefds[sta_id]['data'] = response.json()
                sefd = self.sefds[sta_id]['data']
                if sefd:
                    when = datetime.fromisoformat(sefd['observed']).strftime('%Y-%m-%d %H:%M')
                    self.update_station_info(sta_id, 'SEFD', when)
                    self.update_station_log(sta_id, f'uploaded onoff values dated {when}')
        except VCCError:
            pass


def main():
    import argparse

    parser = argparse.ArgumentParser(description='Access VCC Dashboard')
    parser.add_argument('-c', '--config', help='config file', required=False)
    parser.add_argument('session', help='session code')

    args = settings.init(parser.parse_args())

    Dashboard(args.session).exec()


if __name__ == '__main__':

    import sys
    sys.exit(main())

