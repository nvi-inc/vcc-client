import sys
from datetime import datetime
from pathlib import Path
from collections import defaultdict

from tkinter import *
from tkinter import ttk, font, messagebox

from vcc import settings, VCCError
from vcc.server import VCC


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


class VCCOption(OptionMenu):
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


class VCCScan(ttk.Combobox):
    def __init__(self, frame, scans, callback):
        self.value, self.scans, names = StringVar(), scans, list(scans.keys())

        super().__init__(frame, textvariable=self.value, values=names, postcommand=callback)

        self.first, last = self.scans[names[0]][0], self.scans[names[0]][0]
        self.bind("<Escape>", self.on_change)
        self.bind("<<ComboboxSelected>>", self.on_change)
        self.bind("<Return>", self.on_change)
        self.bind("<FocusOut>", self.focus_out)

        #f = font.nametofont(self.cget("font"))
        #self.config(width=int(f.measure(max(names, key=len)) / f.measure("0")) + 1, anchor='w')

    def on_change(self, event=None):
        print('combobox', event)

    def focus_out(self, event=None):
        print('focus_out', event)

    def get_text(self):
        return self.value.get()

    def reset(self, state, text):
        self.value.set(text)
        self.configure(state=state)


class SessionReport:

    key_words: set = {'warm', 'missed', 'issue', 'fmout-gps', 'gps-fmout', 'late', 'μs'}
    fmout: set = {'fmout-gps', 'gps-fmout'}

    def __init__(self, session):
        if not hasattr(settings.Signatures, "NS"):
            print('No valid NS group in configuration file')
            exit(0)
        self.sta_id, self.session = settings.Signatures.NS[0].lower(), session.lower()
        self.station = self.api = self.reasons = self.records = None
        self.scans = defaultdict(list)
        self.title = f'Report for {self.sta_id.capitalize()} - {self.session.upper()}'
        self.root = None
        self.tree = self.reason = self.first = self.last = self.comment = self.update = None
        self.records = []

    def read_snp(self):
        path = Path(settings.Folders.snap, f'{self.session}{self.sta_id}.snp')
        if not path.exists():
            print(f'{path.name} does not exists!')
            exit(0)
        last_time = name = None
        with open(path) as snp:
            for line in snp.read().splitlines():
                if line.startswith('!'):
                    last_time = datetime.strptime(line[1:], '%Y.%j.%H:%M:%S')
                elif line.startswith('scan_name'):
                    name = line[10:].split(',')[0]
                elif line.startswith('data_valid'):
                    self.scans[name].append(last_time)

    def init_wnd(self):
        self.root = Tk()
        # Set the size of the tkinter window
        self.root.title(self.title)

        style = ttk.Style(self.root)
        style.theme_use('clam')

        # Add a frame for TreeView
        main_frame = Frame(self.root, padx=5, pady=5)
        frame_0 = self.init_summary(main_frame)
        width, height = frame_0.winfo_reqwidth(), frame_0.winfo_reqheight()
        print('0', width, height)
        frame_1 = self.init_records(main_frame)
        width = max(frame_1.winfo_reqwidth(), width)
        height += frame_1.winfo_reqheight()
        print('1', width, height)
        frame_2 = self.init_editor(main_frame)
        height += frame_2.winfo_reqheight()
        print('2', width, height)
        frame_3 = self.init_done(main_frame)
        height += frame_3.winfo_reqheight()
        print('3', width, height)
        main_frame.pack(expand=YES, fill=BOTH)

        #self.select_record()

        self.root.geometry(f"{width}x{height+30}")
        self.root.mainloop()

    def init_summary(self, main_frame):
        frame = LabelFrame(main_frame, text=f'{self.session}{self.sta_id}', pady=5)
        names = list(self.scans.keys())
        start, end, nbr, time_format = StringVar(), StringVar(), StringVar(), '%Y.%j.%H:%M:%S'
        start.set(self.scans[names[0]][0].strftime(time_format))
        end.set(self.scans[names[-1]][-1].strftime(time_format))
        nbr.set(f'{len(self.scans)}')
        # Reason label and OptionMenu
        Label(frame, text="Start", anchor='w').grid(row=0, column=0, padx=5, pady=5)
        entry_1 = Entry(frame, textvariable=start, state=DISABLED)
        entry_1.configure(disabledbackground="white", disabledforeground="black")
        entry_1.grid(row=0, column=1, padx=5, pady=5)
        Label(frame, text="End", anchor='w').grid(row=0, column=2, padx=5, pady=5)
        entry_2 = Entry(frame, textvariable=end, state=DISABLED)
        entry_2.configure(disabledbackground="white", disabledforeground="black")
        entry_2.grid(row=0, column=3, padx=5, pady=5)
        Label(frame, text="Number scans", anchor='w').grid(row=0, column=4, padx=5, pady=5)
        entry_3 = Entry(frame, textvariable=nbr, state=DISABLED)
        entry_3.configure(disabledbackground="white", disabledforeground="black")
        entry_3.grid(row=0, column=5, padx=5, pady=5)
        frame.configure(height=entry_1.winfo_reqheight()+10)
        frame.pack(expand=NO, fill=BOTH)

        return frame

    def init_records(self, main_frame):
        header = {'Problem': (100, W, NO), 'Start': (100, CENTER, NO), 'End': (100, CENTER, NO),
                  'Comments': (500, W, YES)}
        width, height = sum([info[0] for info in header.values()]), 150
        frame = Frame(main_frame, height=height, width=width+20, pady=5)
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
        frame = LabelFrame(main_frame, text="Record", pady=5)
        # Reason label and OptionMenu
        Label(frame, text="Reason", anchor='w').grid(row=0, column=0, padx=5, sticky="W")
        self.reason = VCCOption(frame, self.key_words, self.new_information)
        self.reason.grid(row=0, column=1, padx=5)
        # Start label and date entry
        Label(frame, text="Beginning", anchor='w').grid(row=0, column=2, padx=5, sticky='W')
        self.first = VCCScan(frame, self.scans, self.first_has_changed)
        self.first.grid(row=0, column=3, padx=5, sticky='W')
        # End label and date entry
        Label(frame, text="End", anchor='w').grid(row=0, column=4, padx=5, sticky='W')
        self.last = VCCScan(frame, self.scans, self.last_has_changed)
        self.last.grid(row=0, column=5, padx=5, sticky='W')
        # Update button
        self.update = Button(frame, text="Save", command=self.update_record)
        self.update.grid(row=0, column=6, padx=5, sticky='E')
        # Comment label and text entry
        Label(frame, text="Comment", anchor='w').grid(row=1, column=0, padx=5, pady=5, sticky='W')
        self.comment = VCCComment(frame, self.comment_has_changed)
        self.comment.grid(row=1, column=1, padx=5, pady=5, columnspan=6, sticky='we')

        frame.configure(height=self.reason.winfo_reqheight() + self.comment.winfo_reqheight() + 15)
        frame.columnconfigure(6, weight=1)
        frame.pack(expand=NO, fill=BOTH)

        return frame

    def init_done(self, main_frame):
        frame = Frame(main_frame, padx=5, pady=5)
        button = Button(frame, text="Done", command=self.root.destroy, pady=10)
        button.pack()
        frame.configure(height=button.winfo_reqheight()+10)
        frame.pack(expand=NO, fill=BOTH)
        return frame

    def new_information(self, event):
        pass

    def first_has_changed(self, event):
        pass

    def last_has_changed(self, event):
        pass

    def comment_has_changed(self, event):
        pass

    def selection_changed(self, a):
        print('selection', a, self.records)

    def update_record(self, event):
        pass

    def exec(self):
        with VCC("NS") as vcc:
            self.api = vcc.get_api()
            # self.get_information()  # Get existing data

        self.read_snp()
        self.init_wnd()


def main():
    import argparse

    parser = argparse.ArgumentParser(description='Edit Station downtime')
    parser.add_argument('-c', '--config', help='config file', required=False)
    parser.add_argument('session', help='session code', nargs='?')

    args = settings.init(parser.parse_args())

    try:
        SessionReport(args.session).exec()
    except VCCError as exc:
        print(str(exc))


if __name__ == '__main__':

    sys.exit(main())
