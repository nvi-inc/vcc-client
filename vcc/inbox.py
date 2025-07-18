import json
import os
import signal
import traceback
from threading import Thread, Event
import tempfile
import time
import fcntl

import sys
from datetime import datetime, timedelta
from pathlib import Path
from operator import itemgetter

import tkinter as tk
from tkinter import ttk, messagebox, TclError
from tkinter import font

from vcc import settings, VCCError, json_encoder, json_decoder, vcc_groups, get_inboxes
from vcc.client import VCC
from vcc.windows import MessageBox
from vcc.xtools import Sessions
from vcc.xwidget import XEntry, FakeEntry


def show_inbox(pid):
    os.kill(pid, signal.SIGUSR1)


class BaseMessage:
    def __init__(self, utc, code, status, data):
        self._utc, self._code, self._status = utc, code, status
        self._data = data
        info = "\n".join([f"{key}:{val}" for key, val in data.items()])
        self._details = f"Details of message\n\n{info}"
        self._title = data.get('message', 'Unknown message').splitlines()[0]

    def __str__(self):
        return f"{self.utc} - {self._title} - {self.status}"

    def datetime(self):
        return self._utc

    @property
    def utc(self):
        return self._utc.strftime('%Y-%m-%d %H:%M:%S')

    @property
    def values(self):
        return self.utc, self._code, self.title

    @property
    def status(self):
        return self._status

    @status.setter
    def status(self, status):
        self._status = status

    @property
    def title(self):
        return self._title

    def show(self, parent, group_id):
        msg = f"{self._details}\n\nsent: {self._utc:%Y-%m-%d %H:%M:%S} UTC"
        MessageBox(parent, self.title, msg, icon='info')

    def data(self):
        return self._utc, self._code, self.status, {k: v for k, v in self._data.items()}


class UrgentMsg(BaseMessage):

    def __init__(self, utc, code, status, data):
        super().__init__(utc, code, status, data)

        self._title = f"Urgent message sent by {data.get('fr', '??')}"

    def show(self, parent, group_id):
        msg = f"{self._data.get('message', 'Message was empty')}\n\nsent: {self._utc:%Y-%m-%d %H:%M:%S} UTC"
        MessageBox(parent, self.title, msg, icon='urgent')


class StaInfoMsg(BaseMessage):

    def __init__(self, utc, code, status, data):
        super().__init__(utc, code, status, data)

        self._title, self._msg = f"Message from station {data['station']}", self._details
        if data.get('schedule'):
            self._title = self._msg = f"{data['station']} downloaded schedule {data['session']} ({data['version']})"

    def show(self, parent, group_id):
        msg = f"{self._msg}\n\nsent: {self._utc:%Y-%m-%d %H:%M:%S} UTC"
        MessageBox(parent, f"Information from station {self._data['station']}", msg, icon='urgent')


class ScheduleMsg(BaseMessage):

    def __init__(self, utc, code, status, data):
        super().__init__(utc, code, status, data)
        self._title = self._msg = f"Schedule {data['session']} version {data['version']} is available"

    def show(self, parent, group_id):
        status = 'updated' if self._data['version'] > 1.01 else 'ready'
        msg = f"{self._msg}\n\nSchedule updated at {self._data['updated']:%Y-%m-%d %H:%M:%S} UTC"
        if extra := self._data.get('processed'):
            msg = f"{msg}\n\n{extra}"
        MessageBox(parent, f"{self._data['session']} schedule {status}", msg, icon='urgent')


class MasterMsg(BaseMessage):

    def __init__(self, utc, code, status, data):
        super().__init__(utc, code, status, data)

        self._sessions, nbr = [], len(data)
        self._title = f"Master was updated. {nbr} session{'s' if nbr > 1 else ''} updated."

    def show(self, parent, group_id):
        if not self._sessions:
            with VCC(group_id) as vcc:
                for ses_id, status in self._data.items():
                    try:
                        rsp = vcc.get(f'/sessions/{ses_id}')
                        session = json_decoder(rsp.json())
                        session['status'] = status
                        self._sessions.append(session)
                    except Exception:
                        pass
        Sessions(parent, f'Master was updated ({self._utc:%Y-%m-%d})', self._sessions)


class DowntimeMsg(BaseMessage):
    def __init__(self, utc, code, status, data):
        super().__init__(utc, code, status, data)

        self._sta_code = data['station'].capitalize()
        self.cancelled = data.get('cancelled', False)
        self._start, self._end = self.start(data['start']), self.end(data['end'])
        self._sessions = []
        self._title = f"{self._sta_code} downtime {self._start} to {self._end}{' - CANCELLED' if self.cancelled else ''}"

    def start(self, value):
        if isinstance(value, str):
            return datetime.strptime(value, '%Y-%m-%d').date()
        return value.date() if isinstance(value, datetime) else value

    def end(self, value):
        if not value:
            return self._start + timedelta(days=14)
        if isinstance(value, str):
            return datetime.strptime(value, '%Y-%m-%d').date()
        return value.date() if isinstance(value, datetime) else value

    def show(self, parent, group_id):
        if not self._sessions:
            with VCC(group_id) as vcc:
                if not (sessions := self._data.get('sessions', [])):
                    rsp = vcc.get(f"/sessions/next/{self._data['station']}",
                                  params={'begin': self._start, 'end': self._end})
                    sessions = rsp.json()
                for ses_id in sessions:
                    session = json_decoder(vcc.get(f'/sessions/{ses_id}').json())
                    session['status'] = (f"{self._sta_code} "
                                         f"{'down' if self._sta_code in session['removed'] else 'available'}")
                    self._sessions.append(session)

        title = f"{self._sta_code} downtime {'CANCELLED' if self.cancelled else 'modified'}. List of affected sessions."
        Sessions(parent, title, self._sessions, master=True, header_wnd=self.header_wnd)

    def header_wnd(self, main_frame):
        frame = tk.LabelFrame(main_frame, text=f"{self._sta_code} downtime{' CANCELLED' if self.cancelled else ''}"
                              , padx=5, pady=5)
        ttk.Label(frame, text="Message sent", style='LLabel.TLabel').grid(row=0, column=0, sticky="W")
        XEntry(frame, text=f"{self._utc:%Y-%m-%d %H:%M:%S} UTC").grid(row=0, column=1, columnspan=2,
                                                                      padx=5, pady=5, sticky='we')
        ttk.Label(frame, text="Issue", style='LLabel.TLabel').grid(row=1, column=0, sticky="W")
        XEntry(frame, text=self._data['reason']).grid(row=1, column=1, sticky="W")
        ttk.Label(frame, text="Start", style='LLabel.TLabel').grid(row=1, column=2, sticky='W')
        XEntry(frame, text=self._start).grid(row=1, column=3, sticky="W")
        ttk.Label(frame, text="End", style='LLabel.TLabel').grid(row=1, column=4, sticky='W')
        XEntry(frame, text=self._end).grid(row=1, column=5, sticky="W")
        ttk.Label(frame, text="Comment", style='LLabel.TLabel').grid(row=2, column=0, sticky='W')
        XEntry(frame, text=self._data['comment']).grid(row=2, column=1, columnspan=4, sticky="we")
        frame.columnconfigure(5, weight=1)
        frame.update()
        return frame


message_dict = dict(downtime=DowntimeMsg, master=MasterMsg, schedule=ScheduleMsg, sta_info=StaInfoMsg,
                    urgent=UrgentMsg)


def make_msg_record(utc, code, status, data):
    return message_dict.get(code, BaseMessage)(utc, code, status, data)


class InboxWatcher(Thread):

    def __init__(self, group_id, update_fnc, status, period=5):
        super().__init__()

        self.stopped = Event()
        self.group_id, self.update_fnc, self.status = group_id, update_fnc, status
        self.period = period
        self.vcc = VCC(self.group_id)
        self.vcc.connect()

        self.status.set('Not connect to vcc')

    def check_inbox(self):
        t = time.time()
        try:
            self.status.set('Checking inbox')
            self.status.set(f'Updated at {datetime.utcnow():%H:%M:%S} UTC')
            if rsp := self.vcc.get(f'/messages'):
                for headers, data in rsp.json():
                    utc, code = datetime.fromisoformat(headers['utc']), headers['code']
                    status = 'urgent' if code == 'urgent' else 'unread'
                    self.update_fnc(make_msg_record(utc, code, status, json.loads(data)), new_msg=True)
            else:
                self.status.set('Error connecting to vcc')
        except Exception as exc:
            print('EXC', str(exc))
            try:
                self.vcc.connect()
            except VCCError:
                Event().wait(timeout=1)
        return time.time() - t

    def run(self):
        try:
            dt = self.check_inbox()
            while not self.stopped.wait(self.period - min(self.period, dt)):
                dt = self.check_inbox()
        except Exception as exc:
            print('EXC', str(exc))

    def stop(self):
        self.stopped.set()


class Messages(ttk.Treeview):
    def __init__(self, parent):
        self.records, self.id = {}, 0
        self.active_wnd_msg = None
        self.update_status_wnd = None
        self.last = datetime.utcnow() - timedelta(days=5)
        self.user_file = self.group_file = None

        header = {'Time': (150, tk.W, tk.NO), 'Category': (100, tk.CENTER, tk.NO), 'Title': (300, tk.W, tk.YES)}
        super().__init__(parent, column=list(header.keys()), show='headings', height=5, style='W.Treeview')
        fd = font.nametofont("TkDefaultFont").actual()

        width, height = sum([info[0] for info in header.values()]), 150
        self.place(width=width, height=height)

        vsb = ttk.Scrollbar(parent, orient="vertical", command=self.yview)
        vsb.place(width=20, height=height)
        vsb.pack(side='right', fill='y')
        self.configure(yscrollcommand=vsb.set)

        self.tag_configure('read', font=('', fd['size'], 'normal'), foreground="grey")
        self.tag_configure('unread', font=('', fd['size'] - 1, 'bold'), foreground='black')
        self.tag_configure('urgent', font=('', fd['size'] - 1, 'bold'), foreground='red')
        self.tag_configure('reverse', font=('', fd['size'], 'bold'), foreground="white", background='red')

        for col, (key, info) in enumerate(header.items(), 0):
            self.column(f"{col}", anchor=info[1], minwidth=0, width=info[0], stretch=info[2])
            self.heading(f"{col}", text=key)

    def add_item(self, record, new_msg=False):
        item = self.insert('', 0, str(self.id), values=record.values, tags=(record.status,))
        self.records[item] = record
        self.id += 1
        self.selection_set(item) # set the next row to be the current row
        self.see(item)
        print('NBR REC', len(self.records))
        for r in self.records.values():
            print(f'REC {r}')
        unread = [d for d in self.records.values() if d.status != 'read']
        if new_msg:
            utc = max(d.utc for d in unread) if unread else datetime.utcnow()
            title = f"You received a new message"
            message = f"You have {len(unread)} unread messages\nLast received email: {utc} UT"
            icon = 'urgent'

            if self.active_wnd_msg is None:
                self.active_wnd_msg = MessageBox(self, title, message, icon=icon, exec_fnc=self.remove_active_window)
            else:
                self.nametowidget(self.active_wnd_msg).refresh(title, message, icon)
        self.display_msg(f'{len(unread)} unread messages')

        return item

    def display_msg(self, text):
        if self.update_status_wnd:
            self.update_status_wnd(text)

    def set_status_window(self, fnc):
        self.update_status_wnd = fnc
        unread = [d for d in self.records.values() if d.status != 'read']
        self.display_msg(f'{len(unread)} unread messages')

    def remove_active_window(self):
        self.active_wnd_msg = None

    def open(self, parent, group_id, item):
        rec = self.records[item]
        rec.status = 'read'
        rec.show(parent, group_id)
        self.set_status([item], rec.status)

    def delete_items(self, selection):
        for item in selection:
            self.delete(item)
            self.records.pop(item)
        unread = [d for d in self.records.values() if d.status == 'unread']
        self.display_msg(f'{len(unread)} unread messages')

    def set_status(self, selection, status):
        for item in selection:
            self.records[item].status = status
            self.item(item, tags=(status,))
        unread = [d for d in self.records.values() if d.status == 'unread']
        self.display_msg(f'{len(unread)} unread messages')

    def read(self, user_file):
        item = ''
        if user_file.exists():
            with open(user_file) as f:
                data = json_decoder(json.loads(f.read()))
                self.last = data['last']
                print(f"last {self.last} {type(self.last)}")
                if records := data['records']:
                    for utc, code, status, data in sorted(records, key=itemgetter(0)):
                        item = self.add_item(make_msg_record(utc, code, status, data))

        self.selection_set(item)
        self.see(item)

    def read_group_messages(self, group_file):
        if group_file.exists():
            with open(group_file) as f:
                records = []
                for headers, info in json_decoder((json.loads(f.read()))):
                    print(f"last {self.last} {type(self.last)}")
                    print(f"utc {headers['utc']} {type(headers['utc'])}")
                    if (utc := headers['utc']) > self.last:
                        status = 'urgent' if headers['code'] == 'urgent' else 'unread'
                        records.append((utc, headers['code'], status, info))
                if records:
                    records = [make_msg_record(*data) for data in sorted(records, key=itemgetter(0))]
                    for record in records[:-1]:
                        self.add_item(record)
                    item = self.add_item(records[-1], new_msg=True)
                    self.last = records[-1].datetime()
                    print(f"last record {self.last} {type(self.last)}")

                    self.selection_set(item)
                    self.see(item)

    def save(self, archive):
        with (open(archive, 'w') as ar):
            data = {'last': self.last, 'records': [rec.data() for rec in self.records.values()]}
            ar.write(json.dumps(data, default=json_encoder))


# Window displaying all messages
class InboxWnd(tk.Tk):

    def __init__(self, group_id, interval=0, display=None):
        try:
            # Check if inbox is already running for this display.
            if display:
                visible = get_inboxes(os.getpid())
                if pid := visible.get(display, None):
                    show_inbox(pid)
                    print(f'Inbox already running for {display}')
                    exit(0)

            print(f'Start using {display}')
            super().__init__(screenName=display)
        except TclError as exc:
            print(f'Inbox fatal error - TLC - {str(exc)}')
            sys.exit(1)
        except Exception as exc:
            print(f'Inbox fatal error - EXC - {str(exc)}')
            sys.exit(1)
        if not settings.check_privilege(group_id):
            messagebox.showerror(self, f'No signature for {group_id}.')
            sys.exit(1)

        signal.signal(signal.SIGUSR1, self.goto_top)

        self.hidden = Path(Path(sys.prefix).parent, 'messages')
        self.last_modified = 0

        self.group_id, self.interval = group_id.upper(), interval
        self.protocol("WM_DELETE_WINDOW", self.done)
        self.records, self.record_id, self.messages = {}, 0, None
        self.utc = tk.StringVar()
        self.connection_status = None
        self.listener = None
        self.display = display

    def goto_top(self, sig_num, frame):
        self.wm_attributes('-topmost', True)

    def init_wnd(self):
        # Set the size of the tkinter window
        code = getattr(settings.Signatures, self.group_id)[0]
        self.title(f'Inbox {code} {vcc_groups.get(self.group_id, "")}')

        style = ttk.Style(self)
        style.theme_use('clam')
        style.configure('LLabel.TLabel', anchor='west', padding=(5, 5, 5, 5))

        style.map('W.Treeview', background=[('selected', 'grey')], foreground=[('selected', 'black')])
        # Add a frame for TreeView
        main_frame = tk.Frame(self, padx=5, pady=5)
        width = max(750, self.init_list(main_frame).winfo_reqwidth())
        width = max(width, self.init_done(main_frame).winfo_reqwidth())
        main_frame.pack(expand=tk.YES, fill=tk.BOTH)
        self.geometry(f"{width}x330")

        if self.display:
            self.messages.set_status_window(self.connection_status.set)
        else:
            self.listener = InboxWatcher(self.group_id, self.messages.add_item, self.connection_status, self.interval)

    def init_list(self, main_frame):
        #frame = tk.Frame(main_frame, height=height, width=width+20)
        frame = tk.Frame(main_frame)
        # Add a Treeview widget
        self.messages = Messages(frame)
        self.messages.read(self.user_archive)
        self.messages.read_group_messages(self.grp_archive)
        self.last_modified = self.get_last_mofified()

        self.messages.bind('<Double-1>', self.double_clicked)
        self.messages.bind('<Button-3>', self.popup_menu)
        self.messages.bind('<Return>', self.double_clicked)
        self.messages.bind('<Delete>', lambda event: self.messages.delete_items([i for i in self.messages.selection()]))
        self.messages.pack(expand=tk.YES, fill=tk.BOTH)
        frame.pack(expand=tk.YES, fill=tk.BOTH)
        return frame

    def init_done(self, main_frame):
        frame = tk.Frame(main_frame, padx=5, pady=5)
        button = tk.Button(frame, text="Done", command=self.done)
        button.grid(row=0, column=0, sticky="W")
        self.connection_status = FakeEntry(frame, "", anchor="w", justify="left")
        self.connection_status.grid(row=0, column=1, sticky='WE', padx=(100, 200))
        #button.pack(side=tk.LEFT)
        #tk.Label(frame, textvariable=self.utc, anchor='e', font=("TkFixedFont",)).pack(side=tk.RIGHT)
        tk.Label(frame, textvariable=self.utc, anchor='e', font=("TkFixedFont",)).grid(row=0, column=2, sticky='E')
        frame.configure(height=button.winfo_reqheight()+10)
        frame.columnconfigure(1, weight=1)
        frame.pack(expand=tk.NO, fill=tk.BOTH)
        return frame

    def get_last_mofified(self):
        return self.grp_archive.stat().st_mtime if self.grp_archive.exists() else 0

    @property
    def user_archive(self):
        if self.group_id == 'NS':
            return Path(self.hidden, f"ns-{self.display.split(':')[1]}.json")
        return Path(self.hidden, f"{self.group_id.lower()}-{os.getlogin()}.json")

    @property
    def grp_archive(self):
        return Path(self.hidden, f"{self.group_id.lower()}.json")

    def new_messages(self):
        if (last_modified := self.get_last_mofified()) > self.last_modified:
            self.messages.read_group_messages(self.grp_archive)
            self.last_modified = last_modified
        dt = time.time() % 1
        waiting_time = 1.0 if dt < 0.001 else 1.0 - dt
        self.after(int(waiting_time*1000), self.new_messages)

    def double_clicked(self, event):
        item = self.messages.identify('item', event.x, event.y)
        self.messages.open(self, self.group_id, item)

    def popup_menu(self, event):
        if not (selection := [i for i in self.messages.selection()]):
            selection = [self.messages.identify('item', event.x, event.y)]
            self.messages.selection_set(selection[0])

        m = tk.Menu(self, tearoff=0)
        if len(selection) == 1:
            m.add_command(label="Open", command=lambda: self.messages.open(self, self.group_id, selection[0]))
        m.add_command(label="Delete", command=lambda: self.messages.delete_items(selection))
        m.add_separator()
        m.add_command(label="Mark as read", command=lambda: self.messages.set_status(selection, 'read'))
        m.add_command(label="Mark as unread", command=lambda: self.messages.set_status(selection, 'unread'))
        try:
            m.tk_popup(event.x_root, event.y_root)
        finally:
            m.grab_release()

    def done(self):
        self.messages.save(self.user_archive)
        try:
            if self.listener:
                self.listener.stop()
                self.listener.join(5)
            self.quit()
            self.destroy()
        except Exception:
            pass
        sys.exit(0)

    def update_clock(self):
        utc = datetime.utcnow()
        self.utc.set(f'{utc:%Y-%m-%d %H:%M:%S} UTC')

        dt = datetime.utcnow().timestamp() % 1
        waiting_time = 1.0 if dt < 0.001 else 1.0 - dt
        self.after(int(waiting_time*1000), self.update_clock)

    def exec(self):
        self.init_wnd()
        if self.listener:
            self.listener.start()

        dt = datetime.utcnow().timestamp() % 1
        waiting_time = 1.0 if dt < 0.001 else 1.0 - dt
        self.after(int(waiting_time*1000), self.update_clock)
        self.after(int(waiting_time*1000), self.new_messages)
        self.mainloop()


def check_inbox(group_id, interval, display=None):

    if not settings.get_user_code('NS'):
        InboxWnd(group_id, interval=interval).exec()
    else:
        display = display or os.environ.get('DISPLAY')
        InboxWnd('NS', interval=interval, display=display).exec()
