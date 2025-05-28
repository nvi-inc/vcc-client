import sys
from datetime import datetime, timedelta
from threading import Thread, Event
from subprocess import Popen


from tkinter import *
from tkinter import ttk, font, messagebox

from vcc import settings, VCCError
from vcc.client import VCC
from vcc.session import Session


class Sessions(Thread):

    def __init__(self, tree, master):
        super().__init__()
        self.tree = tree
        today = datetime.utcnow().date()
        self.begin, self.end = today - timedelta(days=2), today + timedelta(days=7)
        self.master = {'std': 'std', 'int': 'int'}.get(master, 'all')
        self.codes = []

    def run(self):
        for ses in self.get_sessions():
            self.tree.insert('', 'end', text="1",
                             values=(ses.code, ses.type, ses.start_date, ses.start_time, ses.dur, ses.network,
                                     ses.operations, ses.correlator, ses.analysis))
        self.tree.insert('', 'end', text="1", values=())

    def get_sessions(self):
        # Get session information from VLBI web service (vws)
        try:
            vcc = VCC()
            rsp = vcc.get('/sessions', params={'begin': self.begin, 'end': self.end, 'master': self.master})
            if rsp:
                self.codes = rsp.json()
                for ses_id in self.codes:
                    rsp = vcc.get(f'/sessions/{ses_id}')
                    if rsp:
                        session = Session(rsp.json())
                        rsp = vcc.get(f'/schedules/{ses_id}', params={'select': 'summary'})
                        if rsp:
                            session.update_schedule(rsp.json())
                        yield session
        except VCCError as exc:
            print(str(exc))


class SessionPicker:
    def __init__(self, master):
        self.station = self.reasons = self.records = None
        self.title = f'Session picker'
        self.root = self.tree = self.reason = self.start = self.end = self.comment = self.update = None
        today = datetime.utcnow().date()
        self.begin, self.end = today - timedelta(days=2), today + timedelta(days=7)
        self.master = master
        print('master', self.master)
        self.sessions = None

    def init_wnd(self):
        self.root = Tk()
        # Set the size of the tkinter window
        self.root.title(self.title)

        style = ttk.Style(self.root)
        style.theme_use('clam')

        # Add a frame for TreeView
        main_frame = Frame(self.root, padx=5, pady=5)
        frame1 = self.init_treeview(main_frame)
        width, height = frame1.winfo_reqwidth(), frame1.winfo_reqheight()
        # frame2 = self.init_editor(main_frame)
        # height += frame2.winfo_reqheight()
        frame3 = self.init_done(main_frame)
        height += frame3.winfo_reqheight()
        main_frame.pack(expand=YES, fill=BOTH)

        self.root.geometry(f"{width}x{height+30}")
        self.sessions = Sessions(self.tree, self.master)
        print('before start', datetime.now())
        self.sessions.start()
        print('after start', datetime.now())
        self.root.mainloop()

    def init_treeview(self, main_wnd):
        header = {'Code': (100, W, NO), 'Type': (100, W, NO), 'Date': (100, CENTER, NO), 'Time': (100, CENTER, NO),
                  'DUR': (50, CENTER, NO), 'Network': (500, W, YES), 'OC': (50, W, NO), 'CO': (50, W, NO),
                  'AC': (50, W, NO)
                  }
        width, height = sum([info[0] for info in header.values()]), 150
        frame = Frame(main_wnd, height=height, width=width+20)
        # Add a Treeview widget
        self.tree = ttk.Treeview(frame, column=list(header.keys()), show='headings', height=5)
        self.tree.place(width=width, height=height)

        vsb = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        vsb.place(width=20, height=height)
        vsb.pack(side='right', fill='y')
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.tag_configure('cancelled', background="red")

        for col, (key, info) in enumerate(header.items(), 1):
            self.tree.column(f"# {col}", anchor=info[1], minwidth=0, width=info[0], stretch=info[2])
            self.tree.heading(f"# {col}", text=key)

        self.tree.bind("<Double-1>", self.on_double_click)
        self.tree.pack(expand=YES, fill=BOTH)
        frame.pack(expand=YES, fill=BOTH)
        return frame

    def init_done(self, main_frame):
        frame = Frame(main_frame, padx=5, pady=5)
        button = Button(frame, text="Done", command=self.root.destroy)
        button.pack()
        frame.configure(height=button.winfo_reqheight()+10)
        frame.pack(expand=NO, fill=BOTH)
        return frame

    def select_record(self, index=-1):
        item = self.tree.get_children()[index]
        self.tree.focus(item)
        self.tree.selection_set(item)

    def on_double_click(self, event):
        item = self.tree.item(self.tree.identify('row', event.x, event.y))
        try:
            cmd = f'dashboard {item["values"][0]}'
            Popen([cmd], shell=True, stdin=None, stdout=None, stderr=None, close_fds=True)
        except IndexError:
            pass

    def selection_changed(self, a):
        index = self.tree.index(self.tree.focus())
        if index < len(self.records):
            record = self.records[index]
            self.reason.reset('disabled', record['reason'])
            self.start.reset('disabled', record['start'], record['start'])
            self.end.reset('normal', record['start'], record['end'])
            self.comment.reset('normal', record['comment'])
            self.update.configure(state='disabled', text='Update')
        else:
            self.reason.reset('active', 'Select..')
            self.start.reset('disabled', datetime.utcnow(), datetime.utcnow())
            self.end.reset('disabled', datetime.utcnow(), None)
            self.comment.reset('disabled', '')
            self.update.configure(state='disabled', text='Add')

    def new_information(self, event):
        self.start.configure(state='normal')
        self.end.configure(state='normal')
        self.comment.configure(state='normal')
        self.update.configure(state='active')

    def update_record(self):
        rec = dict(reason=self.reason.get_text(), start=self.start.get_date(), end=self.end.get_date(),
                   comment=self.comment.get_text())
        ok, err_msg = self.update_information(rec)
        if not ok:
            messagebox.showerror('VCC update failed', err_msg)
            return
        index = self.tree.index(self.tree.focus())
        if index < len(self.records):
            self.records[index] = rec
            item = self.tree.selection()[0]
            self.tree.item(item, values=(rec['reason'], rec['start'].strftime('%Y-%m-%d'),
                                         rec['end'].strftime('%Y-%m-%d') if rec['end'] else '', rec['comment'])
                           )
        else:
            self.records.append(rec)
            self.tree.insert('', len(self.records) - 1, text="1",
                             values=(rec['reason'], rec['start'].strftime('%Y-%m-%d'),
                                     rec['end'].strftime('%Y-%m-%d') if rec['end'] else '', rec['comment'])
                             )
        self.select_record()

    def start_has_changed(self, *event):
        if self.end:
            self.end.reset('normal', self.start.get_date(), self.end.get_date())

    def end_has_changed(self, *event):
        if self.update:
            self.update.configure(state='normal')

    def comment_has_changed(self, *args):
        if self.update:
            self.update.configure(state='normal')

    @staticmethod
    def date_str(value, default=''):
        try:
            return value.strftime("%Y-%m-%d")
        except AttributeError:
            return default

    def exec(self):
        try:
            self.init_wnd()

        except VCCError as exc:
            print(str(exc))

    def add_sessions(self):
        for session in self.get_sessions():
            self.tree.insert('', 'end', text="1", values=session.code)
        self.tree.insert('', 'end', text="1", values=())

    def get_sessions(self):
        # Get session information from VLBI web service (vws)
        try:
            vcc = VCC()
            rsp = vcc.get('/sessions', params={'begin': self.begin, 'end': self.end, 'master': 'all'})
            if rsp:
                for ses_id in rsp.json():
                    rsp = vcc.get(f'/sessions/{ses_id}')
                    if rsp:
                        session = Session(rsp.json())
                        rsp = vcc.get(f'/schedules/{ses_id}', params={'select': 'summary'})
                        if rsp:
                            session.update_schedule(rsp.json())
                        yield session
        except VCCError as exc:
            print(str(exc))


def main():
    import argparse

    parser = argparse.ArgumentParser(description='Edit Station downtime')
    parser.add_argument('-c', '--config', help='config file', required=False)
    parser.add_argument('-edit', help='use interface to edit downtime', action='store_true')
    parser.add_argument('-csv', help='output data in csv format', action='store_true')
    parser.add_argument('station', help='station code', nargs='?')

    args = settings.init(parser.parse_args())

    try:
        SessionPicker(args.station, args.edit, args.csv).exec()
    except VCCError as exc:
        print(str(exc))


if __name__ == '__main__':

    sys.exit(main())
