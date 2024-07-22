import json
import sys
from datetime import datetime
from threading import Thread, Event
import queue

import tkinter as tk
from tkinter import ttk

from vcc import settings, VCCError, vcc_cmd, vcc_groups
from vcc.client import VCC, RMQclientException
from vcc.session import Session
from vcc.utils import messagebox
from vcc.windows import MessageBox
from vcc.xwidget import FakeEntry


# Dashboard displaying session activities.
class Listener(Thread):

    def __init__(self, groud_id, messages):
        super().__init__()

        self.stopped = Event()
        self.vcc, self.rmq_client, self.messages = vcc, None, messages

    def connect(self):
        try:
            self.rmq_client = self.vcc.get_rmq_client()
        except VCCError:
            self.rmq_client = None

    def run(self):
        self.connect()
        try:
            while True:
                try:
                    self.rmq_client.monit(self.process_message)
                except (RMQclientException, Exception):
                    if self.stopped.is_set():
                        break
                    Event().wait(10)
                    self.connect()
        except Exception as exc:
            pass

    def stop(self):
        self.stopped.set()
        self.rmq_client.close()

    def process_message(self, headers, data):
        self.messages.put((headers, data))  # Send message to parent
        self.rmq_client.acknowledge_msg()  # Always acknowledge message


class Monitoring(ttk.LabelFrame):
    def __init__(self, parent, groups, on_selected):

        super().__init__(parent, text=f'Monitoring', padding=(0, 0, 0, 0))

        self.status = {}

        for row, grp in enumerate(groups):
            ttk.Checkbutton(text=f"{settings.get_user_code(grp)} {vcc_groups[grp]}").grid(row=row, column=0)
            ttk.Label(text='Status').grid(row=row, column=1)
            self.status[grp] = status = FakeEntry(self, width=25, anchor='e')
            status.grid(row=row, column=2)

        self.pack(expand=tk.NO, fill=tk.BOTH)
        self.update()

    def set_status(self, grp, text):
        self.status[grp].set(text)


class Inbox(tk.Tk):

    def __init__(self):
        super().__init__()
        self.groups = [grp for grp in vcc_groups.keys() if grp != 'DB' and settings.check_privilege(grp)]
        if not self.groups:
            messagebox('INBOX error', f'No valid groups in Signatures', icon='warning')
            sys.exit(0)
        # Define some styles for ttk widgets
        self.style = ttk.Style(self)
        self.style.theme_use('default')
        self.style.configure('LLabel.TLabel', anchor='west', padding=(5, 5, 5, 5))
        self.style.configure('TButton', anchor='center', padding=(5, 5, 5, 5))
        self.style.configure('Options.TMenubutton', anchor='west', padding=(5, 0, 5, 0))
        self.style.configure('Scans.TCombobox', anchor='west', padding=(5, 0, 5, 0))

        # Draw main frame with all sections
        main_frame = ttk.Frame(self, padding=(5, 5, 5, 5))
        self.selections = Monitoring(main_frame, self.groups, self.on_click)
        self.done, self.hide = self.done_area(main_frame)
        # Set the size of the tkinter window
        self.title(f'VCC Inbox Monitoring')

        main_frame.pack(expand=tk.YES, fill=tk.BOTH)
        main_frame.update()
        self.minsize(main_frame.winfo_reqwidth(), main_frame.winfo_reqheight())

        self.deiconify()  # Ok to show it

    def on_click(self, *args):
        print(args)

    def done_area(self, main_frame):
        frame = ttk.Frame(main_frame, padding=(0, 5, 0, 5))
        done = ttk.Button(frame, text="Done", command=self.destroy, style="TButton")
        done.pack(side='left')
        save = ttk.Button(frame, text="No problems to report", command=self.on_click, style="TButton")
        save.pack(side='right')
        frame.pack(fill=tk.BOTH)
        frame.update()
        return done, save

    def done(self):
        try:
            self.listener.stop()
            self.listener.join()
            self.vcc.close()
            self.destroy()
        except Exception as exc:
            sys.exit(0)

    def process_messages(self):
        while not self.messages.empty():
            headers, data = self.messages.get()
            code = headers['code']
            name = f'process_{code}'
            # Call function for this specific code
            if hasattr(self, name):
                getattr(self, name)(headers, json.loads(data))
        self.after(100, self.process_messages)

    def process_master(self, headers, data):
        msg = '\n'.join([f'{ses_id} : {status}' for ses_id, status in data.items()])
        msg = f"{msg}\n\nsent: {datetime.fromisoformat(headers.get('utc')):%Y-%m-%d %H:%M:%S} UTC"
        MessageBox(self, 'Master was updated', msg, icon='warning')

    def process_urgent(self, headers, data):
        msg = data.get('message', "Message was empty")
        msg = f"{msg}\n\nsent: {datetime.fromisoformat(headers.get('utc')):%Y-%m-%d %H:%M:%S} UTC"
        MessageBox(self, f'Urgent message sent by {data["fr"]}', msg, icon='urgent')

    def process_schedule(self, headers, data):
        status = 'updated' if data['version'] > 1.01 else 'ready'
        msg = f"Schedule version {data['version']} for {data['session']} is available"
        msg = f"{msg}\n\nsent: {datetime.fromisoformat(headers.get('utc')):%Y-%m-%d %H:%M:%S} UTC"
        MessageBox(self, f'Schedule {status}', msg, icon='urgent')

    def process_downtime(self, headers, data):
        start = datetime.fromisoformat(data['start']).strftime('%Y-%m-%d')
        end = datetime.fromisoformat(data['end']).strftime('%Y-%m-%d') if data['end'] else 'unknown'
        sta_id = data['station'].capitalize()
        rsp = self.vcc.api.get(f'/sessions/next/{sta_id}', params={'begin': start, 'end': end})
        sessions = [dict(**data, **{'status': f"{sta_id} {'down' if sta_id in data['removed'] else 'available'}"})
                    for data in rsp.json()]
        title = f"{sta_id} downtime modified. List of affected sessions " \
                f"(sent: {datetime.fromisoformat(headers.get('utc')):%Y-%m-%d %H:%M:%S} UTC)"
        message = json.dumps(sessions)
        options = f"-t '{title}' -m '{message}'"
        vcc_cmd('sessions-wnd', options)

    def process_sta_info(self, headers, data):
        if 'schedule' in data:
            msg = f"Schedule {data['session']} ({data['version']} downloaded by {data['station']}"
        else:
            msg = str(data)

        msg = f"{msg}\n\nsent: {datetime.fromisoformat(headers.get('utc')):%Y-%m-%d %H:%M:%S}"
        MessageBox(self, f"Information from {data['station']}", msg, icon='urgent')

    def exec(self):
        self.init_wnd()
        self.listener.start()
        self.after(100, self.process_messages)
        self.mainloop()


def read_messages(group_id):
    def process_msg(headers, body):
        utc = datetime.fromisoformat(headers['utc']).strftime('%Y-%m-%d %H:%M:%S')
        data = json.loads(body)
        if (code := headers['code']) == 'urgent':
            print(f"{utc} {data['fr']:<10s} {data['message']}")
        elif code == 'master':
            print(f"{utc} {'VCC':<10s} Master file was updated")
            for ses_id, status in data.items():
                print(f"{utc} {'VCC':<10s} {ses_id:<12s} {status}")
        elif code == 'sta_info':
            if 'schedule' in data:
                print(f"{utc} {'VCC':<10s} Schedule {data['session']} ({data['version']}) "
                      f"downloaded by {data['station']}")
            else:
                print(f"{utc} {'VCC':<10s} sta_info {data}")
        elif code == 'schedule':
            print(f"{utc} {'VCC':<10s} Schedule version {data['version']} for {data['session']} is available")
        elif code == 'downtime':
            start = datetime.fromisoformat(data['start']).strftime('%Y-%m-%d')
            end = datetime.fromisoformat(data['end']).strftime('%Y-%m-%d') if data['end'] else 'unknown'
            sta_id = data['station']
            status = ' [CANCELLED]' if data.get('cancelled', False) else ''
            print(f"{utc} {'VCC':<10s} {sta_id} downtime has been modified{status}")
            print(f"{' ' * 30} Period from {start} to {end} {data['reason']} {data['comment']}")
            rsp = vcc.api.get(f'/sessions/next/{sta_id}', params={'begin': data['start'], 'end': data['end']})
            print('\n'.join([f"{' ' * 30} {Session(data).short()}" for data in rsp.json()]))
        else:
            print(f"{utc} {code} {data}")

        rmq.acknowledge_msg()  # Always acknowledge message

    print(f'Reading {group_id}-{settings.get_user_code(group_id)} inbox')
    with VCC(group_id) as vcc:
        rmq = vcc.get_rmq_client()
        rmq.get(process_msg)
    print('end of messages')


def check_inbox(read=False):
    groups = {grp: name for grp, name in vcc_groups.items() if grp != 'DB' and settings.check_privilege(grp)}
    print(groups)
    for grp, name in groups.items():
        print(grp, settings.get_user_code(grp), vcc_groups[grp])


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Access VCC functionalities', exit_on_error=False)
    parser.add_argument('-c', '--config', help='config file', required=False)

    settings.init(parser.parse_args())

    Inbox()
