import json
import sys
from datetime import datetime
from threading import Thread, Event
import queue

import tkinter as tk
from tkinter import ttk, messagebox

from vcc import settings, VCCError, vcc_cmd, vcc_groups, json_encoder
from vcc.client import VCC, RMQclientException
from vcc.session import Session
from vcc.windows import MessageBox


# Dashboard displaying session activities.
class Listener(Thread):

    def __init__(self, group_id, messages):
        super().__init__()

        self.stopped = Event()
        self.group_id, self.rmq_client, self.messages = group_id, None, messages

    def connect(self):
        try:
            vcc = VCC(self.group_id)
            vcc.connect()
            self.rmq_client = vcc.get_rmq_client()
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


class Watcher(Thread):

    def __init__(self, group_id, messages, period=5):
        super().__init__()

        self.stopped = Event()
        self.group_id, self.messages, self.period = group_id, messages, period

    def run(self):
        try:
            while not self.stopped.wait(self.period):
                print('check inbox', datetime.now())
                try:
                    with VCC(self.group_id) as vcc:
                        if rsp := vcc.api.get(f'/messages'):
                            for headers, data in rsp.json():
                                self.messages.put((headers, data))
                        else:
                            print('ERROR', rsp.text)
                except Exception as exc:
                    print('EXC', str(exc))

        except Exception as exc:
            print('EXC', str(exc))

    def stop(self):
        self.stopped.set()


class Inbox(tk.Tk):

    def __init__(self, group_id, interval, once):
        super().__init__()
        self.withdraw()
        self.group_id, self.once = group_id, once
        if not settings.check_privilege(group_id):
            messagebox.showerror(self, f'No signature for {group_id}.')
            sys.exit(0)
        self.code = getattr(settings.Signatures, group_id)[0]
        self.messages = self.listener = None
        if not once:
            self.messages = queue.Queue()
            self.listener = Watcher(group_id, self.messages, interval) if interval \
                else Listener(group_id, self.messages)

        self.archive = []

    def init_wnd(self):
        self.protocol("WM_DELETE_WINDOW", self.done)
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
        self.deiconify()  # Ok to show it

    def done(self):
        with open('archive.json', 'w') as ar:
            ar.write(json.dumps(self.archive, default=json_encoder))
        try:
            self.listener.stop()
            self.listener.join()
            self.destroy()
        except Exception as exc:
            sys.exit(0)

    def process_messages(self):
        while not self.messages.empty():
            properties, data = self.messages.get()
            headers = properties.headers
            code = headers['code']
            name = f'process_{code}'
            self.archive.append((headers, json.loads(data)))
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
        sessions = []
        with VCC(self.group_id) as vcc:
            rsp = vcc.api.get(f'/sessions/next/{sta_id}', params={'begin': start, 'end': end})
            for ses_id in rsp.json():
                data = vcc.api.get(f'/sessions/{ses_id}').json()
                sessions.append((ses_id, f"{sta_id} {'down' if sta_id in data['removed'] else 'available'}"))

        title = f"{sta_id} downtime modified. List of affected sessions " \
                f"(sent: {datetime.fromisoformat(headers.get('utc')):%Y-%m-%d %H:%M:%S} UTC)"
        message = json.dumps(sessions)
        options = f"-c '{settings.args.config}' -M -t '{title}' -m '{message}'"
        vcc_cmd('sessions-wnd', options)

    def process_sta_info(self, headers, data):
        if 'schedule' in data:
            msg = f"Schedule {data['session']} ({data['version']} downloaded by {data['station']}"
        else:
            msg = str(data)

        msg = f"{msg}\n\nsent: {datetime.fromisoformat(headers.get('utc')):%Y-%m-%d %H:%M:%S}"
        MessageBox(self, f"Information from {data['station']}", msg, icon='urgent')

    def read_once(self):
        with VCC(self.group_id) as vcc:
            if rsp := vcc.api.get(f'/messages'):
                if messages := rsp.json():
                    for headers, data in messages:
                        name = f"process_{headers['code']}"
                        # Call function for this specific code
                        if hasattr(self, name):
                            getattr(self, name)(headers, json.loads(data))
                else:
                    MessageBox(self, f"INBOX", 'No messages in your inbox')
            else:
                MessageBox(self, "INBOX error", rsp.text, icon='urgent')
        # Wait that all child windows are closed
        while lst := [x for x in self.winfo_children() if isinstance(x, tk.Toplevel)]:
            self.wait_window(lst[0])
        self.destroy()

    def exec(self):
        if self.once:
            self.after(100, self.read_once())
        else:
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


def check_inbox(group_id, interval, read_once):

    Inbox(group_id, interval, read_once).exec()
