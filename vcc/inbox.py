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
from vcc.windows import MessageBox


# Dashboard displaying session activities.
class Listener(threading.Thread):

    def __init__(self, vcc, messages):
        super().__init__()

        self.rmq_client, self.messages = vcc.get_rmq_client(), messages

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


class Inbox:

    def __init__(self, group_id):
        self.group_id = group_id
        if not hasattr(settings.Signatures, group_id):
            print(f'No signature for {group_id}')
            sys.exit(0)
        self.code = getattr(settings.Signatures, group_id)[0]
        self.vcc = VCC(group_id)
        self.api = self.vcc.get_api()
        self.root = Tk()
        self.root.protocol("WM_DELETE_WINDOW", self.done)
        self.messages = queue.Queue()
        self.listener = Listener(self.vcc, self.messages)

    def init_wnd(self):
        # Set the size of the tkinter window
        group_name = dict(CC='Coordinating Center', AC='Analysis Center', OC='Operations Center', CO='Correlator')
        self.root.title(f'Inbox {self.code} {group_name.get(self.group_id, "")}')

        style = ttk.Style(self.root)
        style.theme_use('clam')
        style.map('W.Treeview', background=[('selected', 'white')], foreground=[('selected', 'black')])
        # Add a frame for TreeView
        button = Button(self.root, text="Done", command=self.done)
        button.pack(side=BOTTOM)
        self.root.configure(padx=10, pady=10)
        self.root.geometry("300x75")

    def done(self):
        try:
            self.listener.stop()
            self.listener.join()
            self.root.destroy()
        except Exception as exc:
            sys.exit(0)

    def process_messages(self):
        while not self.messages.empty():
            headers, data = self.messages.get()
            code = headers['code']
            name = f'process_{code}'
            print(code, name, data)
            # Call function for this specific code
            if hasattr(self, name):
                getattr(self, name)(headers, json.loads(data))
        self.root.after(100, self.process_messages)

    def process_master(self, headers, data):
        msg = '\n'.join([f'{ses_id} : {status}' for ses_id, status in data.items()])
        MessageBox(self.root, 'Master updated', msg, icon='warning')

    def process_urgent(self, headers, data):
        msg = data.get('message', "Message was empty").replace('<br>', '\n')
        MessageBox(self.root, f'Urgent message sent by {data["fr"]}', msg, icon='urgent')

    def exec(self):
        self.init_wnd()
        self.listener.start()
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
    parser.add_argument('group', help='group id', nargs='?')

    args = settings.init(parser.parse_args())

    Inbox(args.group).exec()

if __name__ == '__main__':

    sys.exit(main())
