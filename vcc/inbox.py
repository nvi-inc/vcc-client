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


# Dashboard displaying session activities.
class Listener(Thread):

    def __init__(self, vcc, messages):
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


class Inbox(tk.Tk):

    def __init__(self, group_id):
        super().__init__()
        self.group_id = group_id
        if not hasattr(settings.Signatures, group_id):
            messagebox('INBOX input error', f'No signature for {group_id}', icon='warning')
            sys.exit(0)
        self.code = getattr(settings.Signatures, group_id)[0]
        self.vcc = VCC(group_id)
        self.vcc.connect()
        self.protocol("WM_DELETE_WINDOW", self.done)
        self.messages = queue.Queue()
        self.listener = Listener(self.vcc, self.messages)

    def init_wnd(self):
        # Set the size of the tkinter window
        self.title(f'Inbox {self.code} {vcc_groups.get(self.group_id, "")}')

        style = ttk.Style(self)
        style.theme_use('clam')
        style.map('W.Treeview', background=[('selected', 'white')], foreground=[('selected', 'black')])
        # Add a frame for TreeView
        button = ttk.Button(self, text="Done", command=self.done)
        button.pack(side=tk.BOTTOM)
        self.configure(padx=10, pady=10)
        self.geometry("300x75")

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


def check_inbox(group_id, read=False):
    if not settings.check_privilege(group_id):
        print(f'')
    if read:
        read_messages(group_id)
    else:
        Inbox(group_id).exec()
