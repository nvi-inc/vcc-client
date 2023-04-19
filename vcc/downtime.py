import json
import sys
from datetime import datetime

from tkinter import *
from tkinter import ttk, font, messagebox
from tkcalendar import DateEntry
from tabulate import tabulate

from vcc import settings, VCCError, json_decoder, groups
from vcc.server import VCC
from vcc.ns import notify


class VCCDateEntry(DateEntry):

    def __init__(self, frame, callback):
        self.value = StringVar()

        super().__init__(frame, selectmode='day', date_pattern='yyyy-MM-dd', textvariable=self.value)

        self.default_parse_date, self.parse_date = self.parse_date, self.modified_parse_date
        self.bind("<<DateEntrySelected>>", callback)
        self.value.trace_variable('w', callback)
        self.set_date(None)

    def set_date(self, date):
        old = self.cget('state')
        self.configure(state='normal')
        super().set_date(date) if date else self._set_text('')
        self.configure(state=old)

    def reset(self, state, min_date, value):
        self.configure(state=state, mindate=min_date)
        self.set_date(value)

    def _validate_date(self):
        return super()._validate_date() if self.get() else True

    def modified_parse_date(self, text):
        return self.default_parse_date(text) if text else None


class VCCComment(Entry):
    def __init__(self, frame, on_edited):
        self.value = StringVar()
        super().__init__(frame, textvariable=self.value)
        self.value.trace_variable('w', on_edited)

    def reset(self, state, text):
        self.value.set(text)
        self.configure(state=state)

    def get_text(self):
        return self.value.get()


class VCCReason(OptionMenu):
    def __init__(self, frame, reasons, callback):
        self.value = StringVar()
        super().__init__(frame, self.value, *reasons, command=callback)

        f = font.nametofont(self.cget("font"))
        self.config(width=int(f.measure(max(reasons, key=len)) / f.measure("0")) + 1, anchor='w')

    def get_text(self):
        return self.value.get()

    def reset(self, state, text):
        self.value.set(text)
        self.configure(state=state)


class Downtime:
    def __init__(self, sta_id, edit, csv):
        self.edit, self.csv = edit, csv
        if hasattr(settings.Signatures, "NS"):
            self.group_id, self.sta_id = 'NS', (sta_id if sta_id else settings.Signatures.NS[0]).capitalize()
            self.can_update = self.sta_id == settings.Signatures.NS[0]
        elif not sta_id:
            raise VCCError('Need station code')
        elif hasattr(settings.Signatures, 'CC'):
            self.group_id, self.sta_id, self.can_update = 'CC', sta_id.capitalize(), True
        else:
            self.can_update = False
            ok = [group_id for group_id in groups if hasattr(settings.Signatures, group_id)]
            if not ok:
                raise VCCError('No valid groups in configuration file')
            self.group_id, self.sta_id = ok[0], sta_id.capitalize()
        self.station = self.api = self.reasons = self.records = None
        self.title = f'Downtime for {self.sta_id}'
        self.root = self.tree = self.reason = self.start = self.end = self.comment = self.update = None

    def init_wnd(self):
        self.root = Tk()
        # Set the size of the tkinter window
        self.root.title(self.title)

        style = ttk.Style(self.root)
        style.theme_use('clam')

        # Add a frame for TreeView
        main_frame = Frame(self.root, padx=5, pady=5)
        frame1 = self.init_treeview(main_frame)
        frame2 = self.init_editor(main_frame)
        frame3 = self.init_done(main_frame)
        main_frame.update()
        width, height = frame1.winfo_reqwidth(), frame1.winfo_reqheight()
        height += frame2.winfo_reqheight()
        height += frame3.winfo_reqheight()
        main_frame.pack(expand=YES, fill=BOTH)

        self.select_record()
        self.root.geometry(f"{width}x{height+30}")
        self.root.mainloop()

    def init_treeview(self, main_wnd):
        header = {'Problem': (100, W, NO), 'Start': (100, CENTER, NO), 'End': (100, CENTER, NO),
                  'Comments': (500, W, YES)}
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

        for rec in self.records:
            self.tree.insert('', 'end', text="1", values=(rec['reason'], rec['start'].strftime('%Y-%m-%d'),
                                                          rec['end'].strftime('%Y-%m-%d') if rec['end'] else '',
                                                          rec['comment'])
                             )
        self.tree.insert('', 'end', text="1", values=())
        self.tree.bind('<<TreeviewSelect>>', self.selection_changed)
        self.tree.pack(expand=YES, fill=BOTH)
        frame.pack(expand=YES, fill=BOTH)
        return frame

    def init_editor(self, main_frame):
        frame = LabelFrame(main_frame, text="Record", padx=5, pady=5)
        # Reason label and OptionMenu
        Label(frame, text="Reason", anchor='w').grid(row=0, column=0, padx=5, pady=5)
        self.reason = VCCReason(frame, self.reasons, self.new_information)
        self.reason.grid(row=0, column=1, padx=5, pady=5)
        # Start label and date entry
        Label(frame, text="Start", anchor='w').grid(row=0, column=2, padx=5, pady=5, sticky='NW')
        self.start = VCCDateEntry(frame, self.start_has_changed)
        self.start.grid(row=0, column=3, padx=5, pady=5, sticky='NW')
        # End label and date entry
        Label(frame, text="End", anchor='w').grid(row=0, column=4, padx=5, pady=5, sticky='NW')
        self.end = VCCDateEntry(frame, self.end_has_changed)
        self.end.grid(row=0, column=5, padx=5, pady=5, sticky='NW')
        # Update button
        self.update = Button(frame, text="Update", command=self.update_record)
        self.update.grid(row=0, column=6, sticky='NE')
        # Comment label and text entry
        Label(frame, text="Comment", anchor='w').grid(row=1, column=0, padx=5, pady=5, sticky='NW')
        self.comment = VCCComment(frame, self.comment_has_changed)
        self.comment.grid(row=1, column=1, padx=5, pady=5, columnspan=6, sticky='we')

        frame.columnconfigure(6, weight=1)
        frame.pack(expand=NO, fill=BOTH)
        return frame

    def init_done(self, main_frame):
        frame = Frame(main_frame, padx=5, pady=5)
        button = Button(frame, text="Done", command=self.root.destroy)
        button.pack()  #side='right')
        frame.configure(height=button.winfo_reqheight()+10)
        frame.pack(expand=NO, fill=BOTH)
        return frame

    def select_record(self, index=-1):
        item = self.tree.get_children()[index]
        self.tree.focus(item)
        self.tree.selection_set(item)

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

    def get_information(self):
        rsp = self.api.get(f'/stations/{self.sta_id}')
        if not rsp:
            raise VCCError(rsp.text)
        self.station = json_decoder(rsp.json())
        rsp = self.api.get(f'/downtime/')
        if not rsp:
            raise VCCError(rsp.text)
        self.reasons = json_decoder(rsp.json())
        rsp = self.api.get(f'/downtime/{self.sta_id}')
        today = datetime.utcnow().replace(hour=0, minute=0, second=0)
        records = json_decoder(rsp.json()) if rsp else []
        self.records = [rec for rec in records if not rec['end'] or rec['end'] > today]

    def update_information(self, record):
        try:
            rsp = self.api.put(f'/downtime/{self.sta_id}', data=record)
            try:
                answer = rsp.json()
            except ValueError:
                answer = {'error': rsp.text}
        except VCCError as exc:
            answer = {'error': str(exc)}

        if 'error' in answer:
            return False, answer["error"]
        # get list of sessions affected by this
        start = record['start']
        days = (record['end'] - start).days if record['end'] else 14
        rsp = self.api.get(f'/sessions/next/{self.sta_id}', params={'days': days})
        now = datetime.utcnow().date()
        status = f'{self.sta_id} down'
        sessions = [dict(**data, **{'status': status}) for data in rsp.json()
                    if datetime.fromisoformat(data['start']).date() >= now]
        message = json.dumps(sessions)
        end = record['end'].strftime('%Y-%m-%d') if record['end'] else 'unknown'
        notify(f'{self.sta_id} down for period {start:%Y-%m-%d} - {end}.', message, option='-m')
        return True, ''

    @staticmethod
    def date_str(value, default=''):
        try:
            return value.strftime("%Y-%m-%d")
        except AttributeError:
            return default

    def exec(self):
        try:
            # Connect to VCC
            with VCC(self.group_id) as vcc:
                self.api = vcc.get_api()
                self.get_information()  # Get existing data
                if self.edit and self.can_update:
                    self.init_wnd()  # Popup window interface
                elif not self.records:  # Print row for every downtime record
                    print(f'\nNO downtime period scheduled for {self.sta_id.capitalize()} - {self.station["name"]}\n')
                elif self.csv:
                    for dt in self.records:
                        print(f'{self.sta_id},{dt["reason"]},{self.date_str(dt["start"])},'
                              f'{self.date_str(dt["end"],"unknown")},{dt["comment"]}')
                else:
                    title = f'Scheduled downtime for {self.sta_id.capitalize()} - {self.station["name"]}'

                    hdr = ['Station', 'Problem', 'Start', 'End', 'Comment']
                    table = [[self.sta_id, dt['reason'], self.date_str(dt['start']),
                              self.date_str(dt['end'], 'unknown'), dt['comment']] for dt in self.records]
                    tb = tabulate(table, hdr, tablefmt='fancy_grid')
                    print(f'\n{title.center(len(tb.splitlines()[0]))}\n{tb}')
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
        Downtime(args.station, args.edit, args.csv).exec()
    except VCCError as exc:
        print(str(exc))


if __name__ == '__main__':

    sys.exit(main())
