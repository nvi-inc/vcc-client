import re
import sys
from pathlib import Path
from datetime import datetime, timedelta

from tkinter import *
from tkinter import ttk, font, messagebox

from vcc import json_decoder, VCCError, vcc_cmd
from vcc.client import VCC
from vcc.session import Session

COLUMNS = ['type', 'date', 'code', 'doy', 'time', 'duration', 'stations', 'operations',
           'correlator', 'status', 'dbc', 'analysis', 'del']

UNUSED = ['date', 'doy', 'time', 'status', 'del', 'dbc']
TYPES = {'INTENSIVES': 'intensive'}


# Update VCC Network stations with local file
def update_network(lines):

    # Extract data from file
    is_station = re.compile(' (?P<code>\w{2}) (?P<name>.{8}) (?P<domes>.{9}) (?P<cdp>.{4}) (?P<description>.+)$').match
    network = {rec['code']: rec.groupdict() for line in lines if (rec := is_station(line))}
    # Set flag for VLBA stations
    vlba = network['Va']['description'] + 'Va'
    network = {sta: dict(**data, **{'is_vlba': sta in vlba}) for (sta, data) in network.items()}

    # Get existing information from VOC
    try:
        with VCC('CC') as vcc:
            old = {data['code']: data for data in rsp.json() if data.pop('updated')} \
                if (rsp := vcc.get('/stations')) else {}
            if network == old:
                raise VCCError('No changes in network stations')
            if added := {code: value for (code, value) in network.items() if old.get(code) != value}:
                if not (rsp := vcc.post('/stations', data=added)):
                    raise VCCError(rsp.text)
                print("\n".join([f'{i:4d} {sta} {status}' for i, (sta, status) in enumerate(rsp.json().items(), 1)]))
            for index, sta_id in enumerate([code for code in old if code not in network], 1):
                if not (rsp := vcc.delete(f'/stations/{sta_id}')):
                    raise VCCError(rsp.text)
                print(f'{index:4d} {sta_id} {rsp.json()[sta_id]}')
    except VCCError as exc:
        print(str(exc))


# Update codes for centers or dbc
def update_codes(lines):
    codes = {'SKED CODES': 'operations', 'SUBM CODES': 'analysis', 'CORR CODES': 'correlator'}

    # Read file and extract data
    data, in_section = {}, False
    key = None
    for line in lines:
        if in_section:
            if key in line:
                in_section = False
            else:
                code = line.strip().split()[0].strip()
                data[key][code] = {'code': code, 'description': line.strip()[len(code):].strip()}
        elif keys := [key for key in codes if key in line]:
            in_section = True
            key = keys[0]
            data[key] = {}

    if data:
        try:
            with VCC('CC') as vcc:
                for key, name in codes.items():
                    rsp = vcc.post(f'/catalog/{name}', data=data[key])
                    if not rsp:
                        raise VCCError(rsp.text)
                    print(f'{len([code for code, status in rsp.json().items() if status == "updated"])} '
                          f'of {len(data[key])} {key} where updated')
        except VCCError as exc:
            print(str(exc))


def decode_duration(text):
    hours, minutes = [float(txt.strip() or '0') for txt in text.split(':')]
    return int(hours * 3600 + minutes * 60)


def encode_duration(seconds):
    hours = int(seconds / 3600)
    minutes = int((seconds - hours * 3600) / 60)
    return f'{hours:02d}:{minutes:02d}'


# Update sessions using local master file
def update_master(lines, filter_old=True):

    header = re.compile(r'\s*(?P<year>\d{4})\sMULTI-AGENCY (?P<master>INTENSIVES)? ?SCHEDULE')
    now = datetime.utcnow() if filter_old else datetime(1900, 1, 1)

    # Read master file
    sessions = {}
    for line in lines:
        if line.startswith('|'):
            data = dict(zip(COLUMNS, list(map(str.strip, line.strip(' \n|').split('|')))))
            start = datetime.strptime(f'{data["date"]} {data["time"]}', '%Y%m%d %H:%M')
            data['duration'] = decode_duration(data['duration'])
            if (start + timedelta(seconds=data['duration'])) > now:
                # Clean some unused data
                data = {key: value for key, value in data.items() if key not in UNUSED}
                sessions[data['code']] = dict(**data, **{'start': start, 'master': master})
        elif info := header.match(line):
            # Read multi agency line
            master = TYPES.get(info.group('master'), 'standard')

    # Post data to VCC
    try:
        with VCC('CC') as vcc:
            if rsp := vcc.post('/sessions', data=sessions, params={'notify': filter_old}):
                for ses_id, status in rsp.json().items():
                    print(ses_id, status)
            elif ans := rsp.json():
                for key, info in ans.items():
                    print(f'{key}: {info}')
            else:
                print(rsp.text)
    except VCCError as exc:
        print(str(exc))


class VCCEntry(Entry):
    time_format = '%Y-%m-%d %H:%M'

    def __init__(self, frame, text, on_edited=None, width=None):
        self.value = StringVar()
        text = text.strftime(self.time_format) if isinstance(text, datetime) else text
        self.value.set(text)
        super().__init__(frame, textvariable=self.value, width=width)
        if on_edited:
            try:
                self.value.trace_variable('w', on_edited)
            except TclError:
                self.value.trace_add('write', on_edited)


    def reset(self, state, text):
        self.value.set(text)
        self.configure(state=state)

    def get_text(self):
        return self.value.get()

    def get_datetime(self):
        try:
            return datetime.strptime(self.value.get(), self.time_format)
        except:
            return None

    @property
    def is_empty(self):
        return len(self.value.get().strip()) == 0


class VCCOption(OptionMenu):
    def __init__(self, frame, options, selected):
        self.value = StringVar()
        self.value.set(selected)
        super().__init__(frame, self.value, *options)

        #f = font.nametofont(self.cget("font"))
        #self.config(width=int(f.measure(max(options, key=len)) / f.measure("0")) + 1, anchor='w')
        self.config(width=5, anchor='w')

    def get_text(self):
        return self.value.get()

    def reset(self, state, text):
        self.value.set(text)
        self.configure(state=state)


class SessionViewer:

    def __init__(self, ses_id):

        self.type = self.start = self.duration = self.network = None
        self.operations = self.correlator = self.analysis = None

        try:
            self.root, self.vcc = Tk(), VCC('CC')
            self.is_intensive = BooleanVar()
            self.vcc.connect()
            self.session = self.get_session(ses_id)
        except VCCError as exc:
            vcc_cmd('message-box', f"-t 'Failed contacting VCC' -m '{str(exc)}' -i 'warning'")
            exit(0)
        except TclError as exc:
            vcc_cmd('message-box', f"-t 'TK problem' -m '{str(exc)}' -i 'warning'")
            exit(0)

        self.oc = self.get_options('/catalog/operations')
        self.co = self.get_options('/catalog/correlator')
        self.ac = self.get_options('/catalog/analysis')
        self.stations = self.get_stations()

        self.is_intensive.set(self.session.master == 'intensive')
        self.init_wnd()
        self.root.mainloop()

    def init_wnd(self):
        # Set the size of the tkinter window
        self.root.title(f'Session {self.session.code}')

        style = ttk.Style(self.root)
        style.theme_use('clam')
        # Add a frame for TreeView
        main_frame = Frame(self.root, padx=5, pady=5)
        frame1 = self.init_session(main_frame)
        frame2 = self.init_network(main_frame)
        frame3 = self.init_done(main_frame)
        main_frame.update()
        main_frame.pack(expand=YES, fill=BOTH)
        width = max(700, frame1.winfo_reqwidth() + 10)
        height = frame1.winfo_reqheight() + frame2.winfo_reqheight() + frame3.winfo_reqheight() + 15
        self.root.minsize(width, height)
        self.root.geometry(f"{width}x{height}")

    def init_session(self, main_frame):
        frame = LabelFrame(main_frame, text=self.session.code.upper(), padx=5, pady=5)
        # Reason label and OptionMenu
        Label(frame, text="Code", anchor='w').grid(row=0, column=0, padx=5, pady=5, sticky='nw')
        code = VCCEntry(frame, self.session.code)
        code.grid(row=0, column=1, columnspan=2, padx=5, pady=5, sticky='we')
        code.reset('disabled', self.session.code)
        code.configure(disabledbackground="white", disabledforeground="black")
        Label(frame, text="Type", anchor='w').grid(row=0, column=3, padx=5, pady=5, sticky='we')
        self.type = VCCEntry(frame, self.session.type)
        self.type.grid(row=0, column=4, columnspan=2, padx=5, pady=5, sticky='we')
        Checkbutton(frame, text="Intensive", variable=self.is_intensive).grid(row=0, column=6, columnspan=2,
                                                                              padx=5, pady=5, sticky='ne')
        Label(frame, text="Start", anchor='w').grid(row=1, column=0, padx=5, pady=5, sticky='we')
        self.start = VCCEntry(frame, self.session.start)
        self.start.grid(row=1, column=1, columnspan=2, padx=5, pady=5, sticky='we')
        Label(frame, text="Duration (HH:MM)", anchor='w').grid(row=1, column=3, columnspan=2,
                                                               padx=5, pady=5, sticky='we')
        self.duration = VCCEntry(frame, self.session.dur, width=4)
        self.duration.grid(row=1, column=5, padx=5, pady=5, sticky='e')
        Label(frame, text="Operations Center", anchor='w').grid(row=2, column=0, columnspan=2,
                                                                padx=5, pady=5, sticky='w')
        self.operations = VCCOption(frame, self.oc, self.session.operations)
        self.operations.grid(row=2, column=2, columnspan=1, padx=5, pady=5, sticky='e')
        Label(frame, text="Correlator", anchor='w').grid(row=2, column=3, columnspan=1,
                                                                padx=5, pady=5, sticky='w')
        self.correlator = VCCOption(frame, self.co, self.session.correlator)
        self.correlator.grid(row=2, column=4, columnspan=1, padx=5, pady=5, sticky='e')
        Label(frame, text="Analysis", anchor='w').grid(row=2, column=5, columnspan=1,
                                                                padx=5, pady=5, sticky='w')
        self.analysis = VCCOption(frame, self.ac, self.session.analysis)
        self.analysis.grid(row=2, column=6, columnspan=1, padx=5, pady=5, sticky='e')

        for col in range(7):
            frame.columnconfigure(col, uniform='a')
        frame.columnconfigure(7, weight=1)
        frame.pack(expand=NO, fill=BOTH)

        return frame

    def init_network(self, main_frame):
        frame = LabelFrame(main_frame, text='Network', padx=5, pady=10)
        # Reason label and OptionMenu
        Label(frame, text="Stations", anchor='w').grid(row=0, column=0, padx=5, pady=5, sticky='nw')
        self.network = VCCEntry(frame, self.session.stations_str)
        self.network.grid(row=0, column=1, padx=5, pady=5, sticky='we')
        frame.columnconfigure(1, weight=1)
        frame.pack(expand=NO, fill=BOTH)
        return frame

    def get_session(self, ses_id):
        try:
            rsp = self.vcc.get(f'/sessions/{ses_id}')
            if rsp:
                return Session(json_decoder(rsp.json()))
        except VCCError:
            pass
        return Session({'code': ses_id})

    def get_options(self, url):
        try:
            rsp = self.vcc.get(url)
            if rsp:
                return [item['code'].strip() for item in json_decoder(rsp.json())]
        except VCCError:
            pass
        return []

    def get_stations(self):
        try:
            rsp = self.vcc.get('/stations')
            if rsp:
                return [item['code'].strip() for item in json_decoder(rsp.json())]
        except VCCError:
            pass
        return []

    def init_done(self, main_frame):
        frame = Frame(main_frame, padx=5, pady=5)
        button = Button(frame, text="Done", command=self.done)
        button.pack(side=LEFT)
        Button(frame, text="Submit", command=self.submit).pack(side=RIGHT)
        frame.configure(height=button.winfo_reqheight()+10)
        frame.pack(fill=BOTH)
        return frame

    def done(self):
        self.root.destroy()

    def submit(self):
        # Check if name is not empty
        self.session.type = self.type.get_text().strip()
        if self.type.is_empty:
            messagebox.showerror('Input error', 'Session type is empty')
            self.root.focus_set()
            self.type.focus_set()
            return
        # Get session type
        self.session.master = 'intensive' if self.is_intensive.get() else 'standard'
        # Check if start time is valid
        start = self.start.get_datetime()
        if not start:
            messagebox.showerror('Input error', 'Invalid datetime format\nYYYY-mm-dd HH:MM')
            self.root.focus_set()
            self.start.focus_set()
            return
        self.session.start = start
        # Check if duration is at least 1 minute
        err_msg = self.session.set_duration(self.duration.get_text())
        if err_msg:
            messagebox.showerror('Input error', err_msg)
            self.root.focus_set()
            self.duration.focus_set()
            return
        # Check if centers are selected
        for name in {'operations', 'correlator', 'analysis'}:
            item = getattr(self, name)
            if not item.get_text():
                messagebox.showerror('Input error', f'Select {name}')
                self.root.focus_set()
                item.focus_set()
                return
            setattr(self.session, name, item.get_text().strip())
        # Check station list
        if self.network.is_empty:
            messagebox.showerror('Input error', f'No stations')
            self.root.focus_set()
            self.network.focus_set()
            return

        network = self.network.get_text().split(' -')
        included = [code.capitalize() for code in re.findall('..', network[0])]
        removed = [code.capitalize() for code in re.findall('..', network[1])] if len(network) > 1 else []
        not_valid = [code for code in included+removed if code not in self.stations]
        if not_valid:
            messagebox.showerror('Input error', f'Bad station\n{"".join(not_valid)}')
            self.root.focus_set()
            self.network.setFocus()
            return
        self.session.included, self.session.removed = included, removed
        # Update information on VCC
        try:
            data = {code: getattr(self.session, code) for code in COLUMNS if hasattr(self.session, code)}
            data = dict(**data, **{'start': self.session.start, 'master': self.session.master,
                                   'stations': self.network.get_text()})
            rsp = self.vcc.put(f'/sessions/{self.session.code}', data=data)
            if not rsp:
                raise VCCError(f'VCC response {rsp.status_code}\n{rsp.text}')
            status = json_decoder(rsp.json())[self.session.code]
            if status in ['updated', 'cancelled']:
                messagebox.showinfo(f'{self.session.code.upper()}', status.capitalize())
            else:
                messagebox.showerror(f'{self.session.code.upper()}',
                                     f'Not updated!'
                                     f'\n{"Same information already on VCC" if status == "same" else status}')
        except VCCError as exc:
            messagebox.showerror(f'Problem updating {self.session.code}', str(exc))


def delete_session(ses_id):
    try:
        with VCC('CC') as vcc:
            if rsp := vcc.get(f'/sessions/{ses_id.lower()}'):
                rsp = vcc.delete(f'/sessions/{ses_id.lower()}')
            try:
                for key, info in rsp.json().items():
                    print(f'{key}: {info}')
            except:
                print(rsp.text)
    except VCCError as exc:
        print(str(exc))


def view_session(ses_id):
    viewer = SessionViewer(ses_id)


def master(param, delete=False, filter_old=True):
    from vcc import settings

    # Check that user has right privileges
    if not settings.check_privilege('CC'):
        vcc_cmd('message-box',
                "-t 'NO privilege for this action' -m 'Only Coordinating Center can update master' -i 'warning'")
        return

    if delete:
        delete_session(param)
        return

    if (path := Path(param)).exists():
        # Open file and get what type of file
        with open(path) as f:
            data = f.read()
        if 'MULTI-AGENCY' in data:
            update_master(data.splitlines(), filter_old=filter_old)
        elif 'IVS Master File Format Definition' in data:
            update_codes(data.splitlines())
        elif 'ns-codes.txt' in data:
            update_network(data.splitlines())
        else:
            print(f'{path.name} is not a valid master, master-format or ns-codes file.')
    elif param == path.stem:  # This most be a session
        view_session(param)
