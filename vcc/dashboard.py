import json
import math
import sys
from datetime import datetime, timedelta
import threading
import queue

from tkinter import *
from tkinter import ttk, scrolledtext, messagebox

from vcc import settings, VCCError, json_decoder, groups
from vcc.server import VCC
from vcc.session import Session
from vcc.messaging import RMQclientException


class Inbox(threading.Thread):

    def __init__(self, ses_id, vcc, messages):
        super().__init__()

        self.rmq_client, self.messages = vcc.get_rmq_client(ses_id), messages

    def run(self):
        try:
            self.rmq_client.monit(self.process_message)
        except RMQclientException as exc:
            pass

    def stop(self):
        self.rmq_client.close()

    def process_message(self, headers, data):
        self.messages.put((headers, data))  # Send message to dashboard
        self.rmq_client.acknowledge_msg()  # Always acknowledge message


# Class to display SEFD for specific station
class SEFDViewer:
    def __init__(self, app, data):
        self.app, self.data, self.top = app, data, None

    def show(self):
        if not self.top:
            self.top = Toplevel(self.app.root, padx=10, pady=10)
            self.top.title(f'SEFD {self.data["sta_id"]}')
            self.init_observed()
            self.init_detectors()
            self.top.geometry("420x500")
            self.top.protocol("WM_DELETE_WINDOW", self.done)

        self.top.focus()

    def init_observed(self):
        frame = LabelFrame(self.top, text='Observed', padx=5, pady=5)
        # Reason label and OptionMenu
        Label(frame, text=f'Source: {self.data["source"]}',
              anchor='w').grid(row=0, column=0, padx=5, pady=5, sticky='ew')
        Label(frame, text=f'Az: {self.data["azimuth"]}').grid(row=0, column=1, padx=5, pady=5, sticky='ew')
        Label(frame, text=f'El: {self.data["elevation"]}').grid(row=0, column=2, padx=5, pady=5, sticky='ew')
        Label(frame, text=f'{self.data["observed"]:%Y-%m-%d %H:%M}',
              anchor='e').grid(row=0, column=3, padx=5, pady=5, sticky='we')
        for col in range(4):
            frame.columnconfigure(col, weight=1)
        frame.pack(expand=NO, fill=BOTH)

    def init_detectors(self):
        header = {'De': (50, W, NO), 'I': (20, CENTER, NO), 'P': (20, CENTER, NO), 'Freq': (75, E, NO),
                  'TSYS': (75, E, NO), 'SEFD': (75, E, YES)}
        width, height = sum([info[0] for info in header.values()]), 150
        frame = LabelFrame(self.top, text='Detectors', height=height, width=width + 20, padx=5, pady=5)
        # Add a Treeview widget
        tree = ttk.Treeview(frame, column=list(header.keys()), show='headings', height=15)
        tree.place(width=width, height=height)
        names = ['device', 'input', 'polarization', 'frequency', 'tsys', 'sefd']
        for info in self.data['detectors']:
            tree.insert('', 'end', info['device'], values=[info[name] for name in names])
        vsb = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        vsb.place(width=20, height=height)
        vsb.pack(side='right', fill='y')
        tree.configure(yscrollcommand=vsb.set)
        tree.tag_configure('cancelled', background="red")

        for col, (key, info) in enumerate(header.items(), 0):
            tree.column(f"{col}", anchor=info[1], minwidth=0, width=info[0], stretch=info[2])
            tree.heading(f"{col}", text=key)
        tree.pack(expand=YES, fill=BOTH)
        frame.pack(expand=YES, fill=BOTH)

    def done(self):
        self.top.destroy()
        self.top = None


class StationLog:
    def __init__(self, app, sta_id):
        self.app, self.sta_id, self.top = app, sta_id, None
        self.box, self.text = None, StringVar()
        self.data = []

    def show(self):
        if not self.top:
            self.top = Toplevel(self.app.root, padx=10, pady=10)
            self.top.title(f'{self.sta_id} - events')
            self.box = scrolledtext.ScrolledText(self.top, font=("TkFixedFont",))
            self.box.pack(expand=TRUE, fill=BOTH)
            self.box.configure(state='disabled')
            self.top.geometry("650x200")
            self.top.protocol("WM_DELETE_WINDOW", self.done)
            for utc, text in self.data:
                self.insert(utc, text)
        self.top.focus()

    def done(self):
        self.top.destroy()
        self.top = None

    def insert(self, utc, text):
        self.box.configure(state='normal')
        self.box.insert(END, f'{utc:%Y-%m-%d %H:%M:%S} - {text}\n')
        self.box.configure(state='disabled')

    def add(self, utc, text):
        self.data.append((utc, text))
        if self.top:
            self.insert(utc, text)


# Dashboard displaying session activities.
class Dashboard:

    def __init__(self, ses_id):
        self.vcc = VCC('DB')
        self.api = self.vcc.get_api()
        self.session = self.get_session(ses_id)
        self.root = Tk()
        self.root.protocol("WM_DELETE_WINDOW", self.done)
        self.network, self.start, self.status_text, self.schedule = StringVar(), StringVar(), StringVar(), StringVar()
        self.utc = StringVar()

        self.network.set(self.session.network)
        self.start.set(f'{self.session.start:%Y-%m-%d %H:%M}')
        self.status = self.st_label = None
        self.stations = None
        self.timer = None  # Timer(self.utc, self.update_status)
        self.stopped = threading.Event()
        self.sefds = {}
        self.messages = queue.Queue()
        self.inbox = Inbox(ses_id, self.vcc, self.messages)
        self.logs = {sta_id: StationLog(self, sta_id) for sta_id in self.session.network}
        self.scans = {}

    def init_wnd(self):
        # Set the size of the tkinter window
        self.root.title(f'VLBI Dashboard V1.0')

        style = ttk.Style(self.root)
        style.theme_use('clam')
        style.map('W.Treeview', background=[('selected', 'white')], foreground=[('selected', 'black')])
        # Add a frame for TreeView
        main_frame = Frame(self.root, padx=5, pady=5)
        width = max(750, self.init_session(main_frame).winfo_reqwidth())
        width = max(width, self.init_stations(main_frame).winfo_reqwidth())
        width = max(width, self.init_done(main_frame).winfo_reqwidth())
        main_frame.pack(expand=YES, fill=BOTH)
        self.root.geometry(f"{width}x330")

    def init_session(self, main_frame):
        frame = LabelFrame(main_frame, text=self.session.code.upper(), padx=5, pady=5)
        # Reason label and OptionMenu
        Label(frame, text="Network", anchor='w').grid(row=0, column=0, padx=10, pady=5)
        Label(frame, textvariable=self.network, borderwidth=2, relief="sunken"
              , anchor='w').grid(row=0, column=1, columnspan=5, padx=5, pady=5, sticky='we')
        Label(frame, text="Start time", anchor='w').grid(row=1, column=0, padx=5, pady=5)
        self.st_label = Label(frame, textvariable=self.start, anchor='w', relief='sunken')
        self.st_label.grid(row=1, column=1, columnspan=2, padx=5, pady=5, sticky='we')
        self.status = Label(frame, textvariable=self.status_text, anchor='w', relief='sunken')
        self.status.grid(row=1, column=4, columnspan=2, padx=5, pady=5, sticky='we')
        Label(frame, text="Schedule", anchor='w').grid(row=2, column=0, padx=5, pady=5)
        Label(frame, textvariable=self.schedule, anchor='w', relief='sunken'
              ).grid(row=2, column=1, columnspan=3, padx=5, pady=5, sticky='we')
        for col in range(5):
            frame.columnconfigure(col, uniform='a')

        frame.columnconfigure(5, weight=1)
        frame.pack(expand=NO, fill=BOTH)
        return frame

    def station_clicked(self, event):
        row, col = self.stations.identify_row(event.y), self.stations.identify_column(event.x)
        if row:
            if col == '#3' and self.sefds.get(row):
                self.sefds[row].show()
            elif col == '#5':
                self.logs[row].show()

    def init_stations(self, main_frame):
        header = {'Station': (75, W, NO), 'Schedule': (100, CENTER, NO), 'SEFD': (150, CENTER, NO),
                  'Scans': (100, E, NO), 'Status': (300, W, YES)}
        width, height = sum([info[0] for info in header.values()]), 150
        frame = Frame(main_frame, height=height, width=width+20)
        # Add a Treeview widget
        self.stations = ttk.Treeview(frame, column=list(header.keys()), show='headings', height=5, style='W.Treeview')
        self.stations.place(width=width, height=height)

        vsb = ttk.Scrollbar(frame, orient="vertical", command=self.stations.yview)
        vsb.place(width=20, height=height)
        vsb.pack(side='right', fill='y')
        self.stations.configure(yscrollcommand=vsb.set)
        self.stations.tag_configure('cancelled', background="red")

        for col, (key, info) in enumerate(header.items(), 0):
            self.stations.column(f"{col}", anchor=info[1], minwidth=0, width=info[0], stretch=info[2])
            self.stations.heading(f"{col}", text=key)

        for sta in self.session.network:
            self.stations.insert('', 'end', sta.capitalize(), values=(sta.capitalize(), 'None', 'N/A'), tags=('all',))
        self.stations.tag_configure('all', background='white')
        self.stations.bind('<ButtonRelease-1>', self.station_clicked)
        self.stations.pack(expand=YES, fill=BOTH)
        frame.pack(expand=YES, fill=BOTH)
        return frame

    def init_done(self, main_frame):
        frame = Frame(main_frame, padx=5, pady=5)
        button = Button(frame, text="Done", command=self.done)
        button.pack(side=LEFT)
        Label(frame, textvariable=self.utc, anchor='e', font=("TkFixedFont",)).pack(side=RIGHT)
        frame.configure(height=button.winfo_reqheight()+10)
        frame.pack(expand=NO, fill=BOTH)
        return frame

    def update_status(self, utc):
        status = self.session.get_status()
        if status == 'waiting':
            dt = (self.session.start - utc).total_seconds()
            if dt > 3600:
                hours, minutes = divmod(int(dt / 60), 60)
                text = f'Starting in {hours:d} hour{"s" if hours > 1 else ""} and {minutes:02d} minutes'
            elif dt > 60:
                minutes = math.ceil(dt / 60)
                text = f'Starting in {minutes:d} minute{"s" if minutes > 1 else ""}'
            else:
                seconds = math.ceil(dt)
                s = 's' if seconds > 1 else ''
                text = f'Starting in {seconds:02d} second{"s" if seconds > 1 else ""}'

            color = 'black' if dt > 600 else 'red'
        else:
            color, text = 'black', status.capitalize()
        self.status_text.set(text)
        self.status.configure(fg=color)

    def get_session(self, ses_id):
        for n in range(3):
            try:
                rsp = self.api.get(f'/sessions/{ses_id}')
            except VCCError as exc:
                continue
            if not rsp:
                raise VCCError(f'{ses_id} not found')
            return Session(json_decoder(rsp.json()))

    def get_sefds(self, sta_id):
        for n in range(3):
            try:
                rsp = self.api.get(f'/data/onoff/{sta_id}')
                if rsp:
                    data = json_decoder(rsp.json())
                    self.sefds[sta_id] = SEFDViewer(self, data)
                    self.stations.set(sta_id.capitalize(), '#3', f'{data["observed"]:%Y-%m-%d %H:%M}')
                break
            except VCCError:
                pass

    def get_schedule(self):
        for n in range(3):
            try:
                rsp = self.api.get(f'/schedules/{self.session.code.lower()}', params={'select': 'summary'})
                if rsp:
                    data = json_decoder(rsp.json())
                    self.session.update_schedule(data)
                    self.schedule.set(self.session.sched_version)
                    self.scans = {info['station']: {'last': 0, 'total': info['nbr_scans'], 'list': set()}
                                  for info in self.session.schedule.scheduled}
                    for sta_id, nbr in self.scans.items():
                        self.update_station_info(sta_id, '#4', f'{nbr["last"]}/{nbr["total"]}')

                break
            except VCCError:
                pass

    def done(self):
        try:
            self.inbox.stop()
            self.inbox.join()
            self.root.destroy()
        except Exception as exc:
            sys.exit(0)

    def run_timer(self):
        waiting_time = 1.0 - datetime.utcnow().timestamp() % 1
        try:
            while not self.stopped.is_set():
                dt = datetime.utcnow().timestamp() % 1
                waiting_time = 1.0 if dt < 0.001 else 1.0 - dt
                threading.Event().wait(waiting_time)
                utc = datetime.utcnow()
                self.utc.set(f'{utc:%Y-%m-%d %H:%M:%S} UTC')
                self.update_status(utc)
        except Exception as exc:
            print('timer loop failed', str(exc))

    def update_clock(self):
        utc = datetime.utcnow()
        self.utc.set(f'{utc:%Y-%m-%d %H:%M:%S} UTC')
        self.update_status(utc)
        dt = datetime.utcnow().timestamp() % 1
        waiting_time = 1.0 if dt < 0.001 else 1.0 - dt
        self.root.after(int(waiting_time*1000), self.update_clock)

    def update_station_info(self, sta_id, col, text):
        self.stations.set(sta_id, col, text)

    def process_sta_info(self, headers, data):
        sta_id = data.get('station', None)
        sta_id = sta_id.capitalize() if sta_id else headers.get('sender', '__').capitalize()

        ses_id = data.get('session', None)
        ses_id = ses_id.upper() if ses_id else headers.get('session', '__').upper()
        utc = datetime.fromisoformat(headers.get('utc', datetime.utcnow()))

        # Check if valid station and session id
        if sta_id not in self.session.network or (ses_id not in ['__', self.session.code.upper()]):
            return
        if 'sefd' in data:
            self.get_sefds(station=sta_id)
            self.logs.get(sta_id).add(utc, 'new SEFD values')
        elif 'status' in data:
            text = data['status']
            if 'ses-info' in text:
                text = text.replace('ses-info:', '').replace(data['session'], '').replace(',,', ',')
            text = text[1:] if text.startswith(',') else text
            if 'scan_name' in text:
                self.update_scan(sta_id, utc, text)
            else:
                self.logs.get(sta_id).add(utc, text)
                self.update_station_info(sta_id, '#5', text)
        elif 'schedule' in data:
            text = f'V{data["version"]} fetched'
            self.logs.get(sta_id).add(utc, text)
            self.update_station_info(sta_id, '#5', text)
            self.update_station_info(sta_id, '#2', f'V{data["version"]}')

    def update_scan(self, sta_id, utc, text):
        scan_name = text.split('=')[-1]
        if sta_id not in self.scans:
            self.scans[sta_id] = {'last': 0, 'total': '?????', 'list': set()}
        scans = self.scans.get(sta_id)
        if scan_name not in scans['list']:
            scans['list'].add(scan_name)
            scans['last'] += 1
            self.update_station_info(sta_id, '#4', f'{scans["last"]}/{scans["total"]}')
            self.logs.get(sta_id).add(utc, text)
            self.update_station_info(sta_id, '#5', text)

    def process_master(self, headers, data):
        status = data.get(self.session.code.upper(), None)
        if status == 'cancelled':
            messagebox.showerror(self.session.code, f'{self.session.code} has been cancelled')
        elif status == 'updated':
            messagebox.showinfo(self.session.code, f'{self.session.code} was updated\nYpu should restart Dashboard')

    def process_schedule(self, headers, data):
        threading.Thread(target=self.get_schedule).start()

    def process_messages(self):
        while not self.messages.empty():
            headers, command = self.messages.get()
            # Decode command
            if headers['format'] == 'json':
                command = json.loads(command)
                text = ', '.join([f'{key}={val}' for key, val in command.items()])
            else:
                text = command
            code = headers['code']
            msg, name = f'{code} {text}', f'process_{code}'
            # Call function for this specific code
            if hasattr(self, name):
                getattr(self, name)(headers, command)

        self.root.after(100, self.process_messages)

    def exec(self):
        self.init_wnd()
        threading.Thread(target=self.get_schedule).start()
        for sta_id in self.session.network:
            threading.Thread(target=self.get_sefds, args=(sta_id,)).start()
        self.inbox.start()
        dt = datetime.utcnow().timestamp() % 1
        waiting_time = 1.0 if dt < 0.001 else 1.0 - dt
        self.root.after(int(waiting_time*1000), self.update_clock)
        self.root.after(100, self.process_messages)
        self.root.mainloop()


def test(value, stop):
    waiting_time = 1.0 - datetime.utcnow().timestamp() % 1
    while not stop.wait(waiting_time):
        utc = datetime.utcnow()
        value.set(f'{utc:%Y-%m-%d %H:%M:%S} UTC')
        dt = datetime.utcnow().timestamp() % 1
        waiting_time = 1.0 if dt < 0.001 else 1.0 - dt


def main():
    import argparse

    parser = argparse.ArgumentParser(description='Edit Station downtime')
    parser.add_argument('-c', '--config', help='config file', required=False)
    parser.add_argument('session', help='station code', nargs='?')

    args = settings.init(parser.parse_args())

    try:
        Dashboard(args.session).exec()
    except VCCError as exc:
        messagebox.showerror(f'{args.session.upper()} failed', str(exc))

if __name__ == '__main__':

    sys.exit(main())
