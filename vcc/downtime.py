import json
import sys
import tkinter as tk
from datetime import datetime, timedelta
from functools import partial
from tkinter import messagebox, ttk

from vcc import VCCError, json_decoder, settings, vcc_cmd
from vcc.client import VCC
from vcc.xwidget import XDate, XEntry, XMenu


def sdate(value, default=''):
    try:
        return value.strftime("%Y-%m-%d")
    except AttributeError:
        return default


class Editor(ttk.LabelFrame):

    def __init__(self, parent, reasons, state):

        self.ok, self.need_save = None, False

        super().__init__(parent, text="Record", padding=(0, 0, 5, 0))

        self.default_state = state
        self.record_id = -1
        self.previous = {'start': None, 'end': None}

        # Labels for all fields
        ttk.Label(self, text="Issue", style="LLabel.TLabel").grid(row=0, column=0, sticky="W")
        ttk.Label(self, text="Start", style="LLabel.TLabel").grid(row=0, column=2, sticky='W')
        ttk.Label(self, text="End", style="LLabel.TLabel").grid(row=0, column=4, sticky='W')
        ttk.Label(self, text="Comment", style="LLabel.TLabel").grid(row=1, column=0, sticky='W')

        self.reason = XMenu(self, 'Select..', *reasons, command=lambda *args: self.on_change('reason'),
                            style='Options.TMenubutton')
        self.reason.configure(width=len(max(reasons, key=len)), state=self.default_state)
        self.reason.grid(row=0, column=1, sticky='w')

        # Begin and end combo box
        self.start = XDate(self, partial(self.on_change, 'start'))
        self.start.grid(row=0, column=3, padx=5, sticky='W')

        self.end = XDate(self, partial(self.on_change, 'end'))
        self.end.grid(row=0, column=5, sticky='W')

        self.comment = XEntry(self, on_change=lambda *args: self.on_change('comment'))
        self.comment.grid(row=1, column=1, padx=0, pady=5, columnspan=6, sticky='we')

        self.action = ttk.Button(self, text="Update", style='Action.TButton')
        self.action.grid(row=0, column=6, padx=(5, 0), sticky='E')
        self.columnconfigure(6, weight=1)
        self.pack(expand=tk.NO, fill=tk.BOTH)
        self.update()
        self.reset()

    def reset(self):
        self.reason.reset('Select...', state=self.default_state)
        for widget in [self.start, self.end]:
            widget.reset('disabled', datetime.now(), None)
        self.comment.reset('', 'disabled')
        self.action.configure(state='disabled', text='Update')
        self.previous = {'start': None, 'end': None}

    def on_change(self, code, *events):
        if code == 'reason':
            self.start.reset('normal', datetime.utcnow().date(), datetime.utcnow().date())
        elif code == 'start':
            self.end.reset('normal', self.start.get_date(), self.end.get_date())
            self.comment.configure(state='normal')
            self.action.configure(state='normal', text='Update')
        else:
            self.action.configure(state='normal', text='Update')

    @property
    def record(self):
        return dict(reason=self.reason.get(), start=self.start.get_datetime(), end=self.end.get_datetime(),
                    comment=self.comment.get(), id=self.record_id)

    @record.setter
    def record(self, record):
        self.reason.reset(text=record['reason'], state='disabled')
        self.start.reset('normal', min(record['start'], datetime.utcnow()), record['start'])
        self.end.reset('normal', record['start'], record['end'])
        self.comment.reset(record['comment'], state='normal')
        self.action.configure(state='normal', text='Cancel')
        self.record_id = record.get('id', -1)
        self.previous['start'], self.previous['end'] = record['start'], record['end']

    def bind(self, fnc):
        self.action.bind('<Button-1>', lambda event: fnc(self.action['text']))

    def refresh(self, style):
        self.action.state(['!pressed', 'disabled'])
        style.configure('Action.TButton', relief=tk.RAISED)


class Viewer(ttk.Frame):
    header = {'Problem': (100, tk.W, tk.NO), 'Start': (100, tk.CENTER, tk.NO), 'End': (100, tk.CENTER, tk.NO),
              'Comments': (500, tk.W, tk.YES)}

    def __init__(self, parent, records):
        width, height = sum([info[0] for info in self.header.values()]), 150
        self.records = records

        super().__init__(parent, height=height, width=width+20, padding=(0, 5, 0, 5))

        # Add a Treeview widget
        self.tree = ttk.Treeview(self, column=list(self.header.keys()), show='headings', height=5)
        self.tree.place(width=width, height=height)
        # Add a vertical scrollbar
        vsb = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        vsb.place(width=20, height=height)
        vsb.pack(side='right', fill='y')
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.tag_configure('cancelled', background="red")

        for col, (key, info) in enumerate(self.header.items(), 1):
            self.tree.column(f"# {col}", anchor=info[1], minwidth=0, width=info[0], stretch=info[2])
            self.tree.heading(f"# {col}", text=key)

        for rec in self.records:
            self.tree.insert('', 'end', text="1", values=self.extract(rec))

        self.tree.insert('', 'end', text="1", values=())
        self.tree.pack(expand=tk.YES, fill=tk.BOTH)
        self.pack(expand=tk.YES, fill=tk.BOTH)
        self.update()

    @staticmethod
    def extract(record):
        return record['reason'], sdate(record['start']), sdate(record['end']), record['comment']

    @property
    def selected(self):
        return self.tree.index(self.tree.focus())

    def update_record(self, record):
        item = self.tree.selection()[0]
        self.tree.item(item, values=self.extract(record))
        self.select_record()

    def add_record(self, record):
        index = self.tree.index(self.tree.focus())
        self.tree.insert('', index, text="1", values=self.extract(record))
        self.select_record()

    def cancel_record(self, record):
        self.tree.delete(self.tree.focus())
        self.select_record()

    def select_record(self, index=-1):
        self.tree.focus(item := self.tree.get_children()[index])
        self.tree.selection_set(item)

    def bind(self, fnc):
        self.tree.bind('<<TreeviewSelect>>', fnc)


class Downtime(tk.Tk):
    def __init__(self, sta_id):

        super().__init__()

        self.withdraw()  # To avoid window to show before fully designed

        self.records, self.station, self.reasons = [], {}, []
        self.can_update = settings.check_privilege(['NS', 'CC'])

        self.group = 'NS' if hasattr(settings.Signatures, "NS") else 'CC' if self.can_update else None
        self.sta_id = settings.Signatures.NS[0].lower() if self.group == 'NS' else sta_id
        if not self.sta_id:
            messagebox.showerror('No station code', 'You need station code as input parameter')
            sys.exit(1)
        self.vcc = VCC(self.group)
        try:
            self.vcc.connect()
            self.get_information()
        except VCCError as exc:
            messagebox.showerror('VCC problem', f'{str(exc)}')
            sys.exit(1)

        # Define some styles for ttk widgets
        self.style = ttk.Style(self)
        self.style.theme_use('clam')
        self.style.configure('LLabel.TLabel', anchor='west', padding=(5, 5, 5, 5))
        self.style.configure('Action.TButton', anchor='center', padding=(5, 5, 5, 5))
        self.style.configure('TButton', anchor='center', padding=(5, 5, 5, 5))
        self.style.configure('Options.TMenubutton', anchor='west', padding=(5, 0, 5, 0))
        self.style.configure('Scans.TCombobox', anchor='west', padding=(5, 0, 5, 0))
        # Draw main frame with all sections
        main_frame = ttk.Frame(self, padding=(5, 5, 5, 5))
        self.viewer = Viewer(main_frame, self.records)
        self.editor = Editor(main_frame, self.reasons, 'normal' if self.can_update else 'disabled')
        # self.done, self.done_button = self.done_area(main_frame)
        self.title(f"Downtime for {self.sta_id.capitalize()} {self.station.get('name', '')}")

        if self.can_update:
            self.editor.bind(self.record_edited)
            self.viewer.bind(self.selection_changed)
        self.viewer.select_record()

        main_frame.pack(expand=tk.YES, fill=tk.BOTH)
        main_frame.update()
        self.minsize(main_frame.winfo_reqwidth(), main_frame.winfo_reqheight())

        self.deiconify()  # Ok to show it

    def __del__(self):
        del self.unsent
        if self.vcc:
            self.vcc.close()

    def get_information(self):
        if not (rsp := self.vcc.api.get(f'/stations/{self.sta_id}')):
            raise VCCError(f'{self.sta_id.capitalize()} does not exist!')
        self.station = json_decoder(rsp.json())

        self.reasons = json_decoder(self.vcc.api.get(f'/downtime/').json())
        rsp = self.vcc.api.get(f'/downtime/{self.sta_id}')
        records = json_decoder(rsp.json()) if rsp else []
        today = datetime.utcnow().date()
        self.records = [rec for rec in records if not rec['end'] or rec['end'].date() >= today]

    def exec(self):
        self.mainloop()

    def done_area(self, main_frame):
        frame = ttk.Frame(main_frame, padding=(0, 5, 0, 5))
        done_button = ttk.Button(frame, text="Done", command=self.destroy, style="TButton")
        done_button.pack()
        frame.pack(fill=tk.BOTH)
        frame.update()
        return frame, done_button

    def selection_changed(self, *args):
        if (index := self.viewer.selected) < len(self.records):
            self.editor.record = self.records[index]
            self.editor.action.configure(text="Cancel")
        else:
            self.editor.reset()

    def record_edited(self, action):
        if self.editor.action.instate(['disabled']):
            return
        record = self.editor.record
        if (index := self.viewer.selected) < len(self.records):
            record = {key: record[key] if key in record else value for key, value in self.records[index].items()}
            if action == 'Cancel':
                record['cancelled'], update_viewer = True, self.viewer.cancel_record
                self.records.pop(index)
            else:
                record['cancelled'], update_viewer = False, self.viewer.update_record
                self.records[index] = record
        else:
            # Check that period does not overlap with existing period
            for rec in self.records:
                end = rec['end'] if rec['end'] else rec['start'] + timedelta(days=14)
                if rec['start'] <= record['start'] <= end:
                    if not rec['end']:
                        messagebox.showerror("Invalid downtime period",
                                             f"You must set a close time for {rec['reason']} starting {rec['start']}")
                    else:
                        messagebox.showerror("Invalid downtime period",
                                             f"This period conflict with {rec['reason']} starting {rec['start']}")
                    return
                end = record['end'] if record['end'] else record['start'] + timedelta(days=14)
                if end >= rec['start'] > record['start']:
                    messagebox.showerror("Invalid downtime period",
                                         f"This period conflict with {rec['reason']} starting {rec['start']}")
                    return

            self.records.append(record)
            update_viewer = self.viewer.add_record
        try:
            record['id'] = self.update_vcc_record(record)
            update_viewer(record)
            if action == 'Cancel':
                self.editor.reset()
            self.show_affected_sessions(record)
        except VCCError as exc:
            messagebox.showerror('Could not update record on VCC', str(exc))
        self.after(300, lambda: self.editor.refresh(self.style))

    def update_vcc_record(self, record):
        if not self.vcc.is_available:
            self.vcc.connect()
        ans = self.vcc.api.put(f'/downtime/{self.sta_id}', data=record).json()
        if 'update' not in ans:
            raise VCCError(ans.get('error', 'unknown error'))
        return ans['update']

    def show_affected_sessions(self, record):

        first = self.editor.previous['start'] if self.editor.previous['start'] else record['start']
        last = self.editor.previous['end'] if self.editor.previous['end'] else record['end']
        last = last if last else first + timedelta(days=14)
        end = record['end'] if record['end'] else record['start'] + timedelta(days=14)
        first, last = min(first, record['start']), max(last, end)
        rsp = self.vcc.api.get(f'/sessions/next/{self.sta_id}', params={'begin': first, 'end': last})
        sessions = [data for data in rsp.json()]
        end = sdate(record['end'], 'unknown')
        title = f"{self.sta_id.capitalize()} down {sdate(record['start'])} to {end}. List of affected sessions"
        vcc_cmd('sessions-wnd', f"-t '{title}' -m '{json.dumps(sessions)}'")


def report(sta_id):
    if not (sta_id := settings.Signatures.NS[0].lower() if not sta_id else sta_id):
        print('You need station code as input parameter')
    else:
        with VCC() as vcc:
            if not (rsp := vcc.api.get(f'/stations/{sta_id}')):
                print(f'Station {sta_id.capitalize()} does not exist')
            else:
                rsp = vcc.api.get(f'/downtime/{sta_id}')
                records = json_decoder(rsp.json()) if rsp else []
                today = datetime.utcnow().date()
                if not (records := [rec for rec in records if not rec['end'] or rec['end'].date() >= today]):
                    print(f'No downtime records for {sta_id.capitalize()}')
                else:
                    print(f'Downtime for {sta_id.capitalize()}')
                    for record in records:
                        print(f"{record['reason']:20s} {sdate(record['start'])} {sdate(record['end'],' '*10)} "
                              f"{record['comment']}")


def downtime(sta_id, want_report=False):
    report(sta_id) if want_report else Downtime(sta_id).exec()


def main():
    import argparse

    parser = argparse.ArgumentParser(description='Edit Station downtime')
    parser.add_argument('-c', '--config', help='config file', required=False)
    parser.add_argument('-r', '--report', help='output data in csv format', action='store_true')
    parser.add_argument('station', help='station code', nargs='?')

    args = settings.init(parser.parse_args())

    if args.report:
        report(args.station)
    else:
        Downtime(args.station).exec()


if __name__ == '__main__':

    sys.exit(main())
