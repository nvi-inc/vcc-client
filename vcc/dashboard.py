import json
import math
import sys
from datetime import datetime, timedelta
import threading
import queue

import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, TclError

from vcc import settings, VCCError, json_decoder, vcc_cmd
from vcc.client import VCC, RMQclientException
from vcc.session import Session
from vcc.windows import MessageBox


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
        self.rmq_client.acknowledge_msg()  # Always acknowledge message
        print('headers', headers)
        print('data', data)
        self.messages.put((headers, data))  # Send message to dashboard


class Urgent(tk.Toplevel):

    def __init__(self, root, title, message):
        super().__init__(root)

        self.title(title)
        box = scrolledtext.ScrolledText(self)
        box.pack(expand=tk.TRUE, fill=tk.BOTH)
        box.configure(state='normal')
        box.insert(tk.END, f'{message}\n')
        box.configure(state='disabled')
        self.geometry("400x100")


# Class to display SEFD for specific station
class SEFDViewer:
    def __init__(self, app, data):
        self.app, self.data, self.top = app, data, None

    def show(self):
        if not self.top:
            self.top = tk.Toplevel(self.app, padx=10, pady=10)
            self.top.title(f'SEFD {self.data["sta_id"]}')
            self.init_observed()
            self.init_detectors()
            self.top.geometry("420x500")
            self.top.protocol("WM_DELETE_WINDOW", self.done)

        self.top.focus()

    def init_observed(self):
        frame = tk.LabelFrame(self.top, text='Observed', padx=5, pady=5)
        # Reason label and OptionMenu
        tk.Label(frame, text=f'Source: {self.data["source"]}',
              anchor='w').grid(row=0, column=0, padx=5, pady=5, sticky='ew')
        tk.Label(frame, text=f'Az: {self.data["azimuth"]}').grid(row=0, column=1, padx=5, pady=5, sticky='ew')
        tk.Label(frame, text=f'El: {self.data["elevation"]}').grid(row=0, column=2, padx=5, pady=5, sticky='ew')
        tk.Label(frame, text=f'{self.data["observed"]:%Y-%m-%d %H:%M}',
              anchor='e').grid(row=0, column=3, padx=5, pady=5, sticky='we')
        for col in range(4):
            frame.columnconfigure(col, weight=1)
        frame.pack(expand=tk.NO, fill=tk.BOTH)

    def init_detectors(self):
        header = {'De': (50, tk.W, tk.NO), 'I': (20, tk.CENTER, tk.NO), 'P': (20, tk.CENTER, tk.NO),
                  'Freq': (75, tk.E, tk.NO), 'TSYS': (75, tk.E, tk.NO), 'SEFD': (75, tk.E, tk.YES)}
        width, height = sum([info[0] for info in header.values()]), 150
        frame = tk.LabelFrame(self.top, text='Detectors', height=height, width=width + 20, padx=5, pady=5)
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
        tree.pack(expand=tk.YES, fill=tk.BOTH)
        frame.pack(expand=tk.YES, fill=tk.BOTH)

    def done(self):
        self.top.destroy()
        self.top = None


class StationLog:
    def __init__(self, app, sta_id):
        self.app, self.sta_id, self.top = app, sta_id, None
        self.box, self.text = None, tk.StringVar()
        self.data = []

    def show(self):
        if not self.top:
            self.top = tk.Toplevel(self.app, padx=10, pady=10)
            self.top.title(f'{self.sta_id} - events')
            self.box = scrolledtext.ScrolledText(self.top, font=("TkFixedFont",))
            self.box.pack(expand=tk.TRUE, fill=tk.BOTH)
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
        self.box.insert(tk.END, f'{utc:%Y-%m-%d %H:%M:%S} - {text}\n')
        self.box.configure(state='disabled')

    def add(self, utc, text):
        self.data.append((utc, text))
        if self.top:
            self.insert(utc, text)


# Dashboard displaying session activities.
class Dashboard(tk.Tk):

    def __init__(self, ses_id):
        try:
            super().__init__()
        except TclError as exc:
            print(f'Dashboard fatal error - {str(exc)}')
            sys.exit(1)

        self.vcc = VCC('DB')
        self.vcc.connect()
        self.session = self.get_session(ses_id)

        self.protocol("WM_DELETE_WINDOW", self.done)
        self.network, self.start = tk.StringVar(), tk.StringVar()
        self.status_text, self.schedule = tk.StringVar(), tk.StringVar()
        self.utc = tk.StringVar()

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
        self.title(f'VLBI Dashboard V1.0')

        style = ttk.Style(self)
        style.theme_use('clam')
        style.map('W.Treeview', background=[('selected', 'white')], foreground=[('selected', 'black')])
        # Add a frame for TreeView
        main_frame = tk.Frame(self, padx=5, pady=5)
        width = max(750, self.init_session(main_frame).winfo_reqwidth())
        width = max(width, self.init_stations(main_frame).winfo_reqwidth())
        width = max(width, self.init_done(main_frame).winfo_reqwidth())
        main_frame.pack(expand=tk.YES, fill=tk.BOTH)
        self.geometry(f"{width}x330")

    def init_session(self, main_frame):
        frame = tk.LabelFrame(main_frame, text=self.session.code.upper(), padx=5, pady=5)
        # Reason label and OptionMenu
        tk.Label(frame, text="Network", anchor='w').grid(row=0, column=0, padx=10, pady=5)
        tk.Label(frame, textvariable=self.network, borderwidth=2, relief="sunken"
                 , anchor='w').grid(row=0, column=1, columnspan=5, padx=5, pady=5, sticky='we')
        tk.Label(frame, text="Start time", anchor='w').grid(row=1, column=0, padx=5, pady=5)
        self.st_label = tk.Label(frame, textvariable=self.start, anchor='w', relief='sunken')
        self.st_label.grid(row=1, column=1, columnspan=2, padx=5, pady=5, sticky='we')
        self.status = tk.Label(frame, textvariable=self.status_text, anchor='w', relief='sunken')
        self.status.grid(row=1, column=4, columnspan=2, padx=5, pady=5, sticky='we')
        tk.Label(frame, text="Schedule", anchor='w').grid(row=2, column=0, padx=5, pady=5)
        tk.Label(frame, textvariable=self.schedule, anchor='w', relief='sunken'
                 ).grid(row=2, column=1, columnspan=3, padx=5, pady=5, sticky='we')
        for col in range(5):
            frame.columnconfigure(col, uniform='a')

        frame.columnconfigure(5, weight=1)
        frame.pack(expand=tk.NO, fill=tk.BOTH)
        return frame

    def station_clicked(self, event):
        row, col = self.stations.identify_row(event.y), self.stations.identify_column(event.x)
        if row:
            if col == '#3' and self.sefds.get(row):
                self.sefds[row].show()
            elif col == '#5':
                self.logs[row].show()

    def init_stations(self, main_frame):
        header = {'Station': (75, tk.W, tk.NO), 'Schedule': (100, tk.CENTER, tk.NO), 'SEFD': (150, tk.CENTER, tk.NO),
                  'Scans': (100, tk.E, tk.NO), 'Status': (300, tk.W, tk.YES)}
        width, height = sum([info[0] for info in header.values()]), 150
        frame = tk.Frame(main_frame, height=height, width=width+20)
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
        self.stations.pack(expand=tk.YES, fill=tk.BOTH)
        frame.pack(expand=tk.YES, fill=tk.BOTH)
        return frame

    def init_done(self, main_frame):
        frame = tk.Frame(main_frame, padx=5, pady=5)
        button = tk.Button(frame, text="Done", command=self.done)
        button.pack(side=tk.LEFT)
        tk.Label(frame, textvariable=self.utc, anchor='e', font=("TkFixedFont",)).pack(side=tk.RIGHT)
        frame.configure(height=button.winfo_reqheight()+10)
        frame.pack(expand=tk.NO, fill=tk.BOTH)
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
        if rsp := self.vcc.api.get(f'/sessions/{ses_id}'):
            return Session(json_decoder(rsp.json()))
        vcc_cmd('message-box', f'-t "Session {ses_id} not found" -m "" -i "warning"')
        sys.exit(1)

    def get_sefds(self, sta_id):
        for n in range(3):
            try:
                rsp = self.vcc.api.get(f'/data/onoff/{sta_id}')
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
                if rsp := self.vcc.api.get(f'/schedules/{self.session.code.lower()}', params={'select': 'summary'}):
                    self.session.update_schedule(json_decoder(rsp.json()))
                    self.schedule.set(self.session.sched_version)
                    self.scans = {info['station']: {'last': 0, 'total': info['nbr_scans'], 'version': info['version'],
                                                    'list': set()}
                                  for info in self.session.schedule.scheduled}
                    for sta_id, nbr in self.scans.items():
                        self.update_station_info(sta_id, '#4', f'{nbr["last"]}/{nbr["total"]}')
                        if nbr['version']:
                            self.update_station_info(sta_id, '#2', f'V{nbr["version"]}')

                break
            except VCCError:
                pass

    def done(self):
        try:
            self.inbox.stop()
            self.inbox.join()
            self.destroy()
        except Exception as exc:
            sys.exit(0)

    def run_timer(self):
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
        self.after(int(waiting_time*1000), self.update_clock)

    def update_station_info(self, sta_id, col, text):
        try:
            self.stations.set(sta_id, col, text)
        except TclError:
            pass

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
            if 'urgent' in text:
                Urgent(self, f'URGENT message from {sta_id}', text.replace('urgent:', ''))
            text = text[1:] if text.startswith(',') else text
            if 'scan_name' in text:
                self.update_scan(sta_id, utc, text)
            else:
                self.update_station_info(sta_id, '#5', text)
                self.logs.get(sta_id).add(utc, text)
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
            self.update_station_info(sta_id, '#5', text)
            self.logs.get(sta_id).add(utc, text)

    def process_master(self, headers, data):
        status = data.get(self.session.code.upper(), None)

        msg = f'{self.session.code} was {status}'
        if status == 'updated':
            msg += '\nYou should restart Dashboard'
        subject = 'Message from VCC'
        MessageBox(self, subject, msg, icon='urgent')

    def process_schedule(self, headers, data):
        threading.Thread(target=self.get_schedule).start()

    def process_urgent(self, headers, data):
        subject = f'Urgent message from {data["fr"]}'
        msg = data.get('message', "None")
        MessageBox(self, subject, msg, icon='warning')

    def process_messages(self):
        nbr = 0
        while not self.messages.empty():
            nbr += 1
            headers, command = self.messages.get()
            print('process headers', headers)
            print('process command', command)
            # Decode command
            if headers['format'] == 'json':
                command = json.loads(command)
            code = headers['code']
            name = f'process_{code}'
            print('process', name)
            # Call function for this specific code
            if hasattr(self, name):
                getattr(self, name)(headers, command)

        self.after(10 if nbr else 100, self.process_messages)

    def exec(self):
        self.init_wnd()
        threading.Thread(target=self.get_schedule).start()
        for sta_id in self.session.network:
            threading.Thread(target=self.get_sefds, args=(sta_id,)).start()
        self.inbox.start()
        dt = datetime.utcnow().timestamp() % 1
        waiting_time = 1.0 if dt < 0.001 else 1.0 - dt
        self.after(int(waiting_time*1000), self.update_clock)
        self.after(100, self.process_messages)
        self.mainloop()


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
