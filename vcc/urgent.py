import sys
from datetime import date
import tkinter as tk
from tkinter import ttk, messagebox

from vcc import settings, VCCError, vcc_groups
from vcc.client import VCC
from vcc.xwidget import XMenu, FakeEntry, AutoComplete, ToolTip


def clean(x):
    return x.strip().capitalize()


class FromWnd(ttk.LabelFrame):

    def __init__(self, parent):
        super().__init__(parent, text='Sender Information', padding=(0, 0, 5, 0))

        self.groups = {key: info[0] for key in vcc_groups.keys() if key != 'DB'
                       and (info := getattr(settings.Signatures, key, None))}
        keys = [f'{key} {vcc_groups[key]}' for key in self.groups.keys()]
        ttk.Label(self, text="My group", style="LLabel.TLabel").grid(row=0, column=0, sticky="W", padx=5, pady=5)
        self.menu = XMenu(self, keys[0], *keys, command=self.group_changed)
        self.menu.grid(row=0, column=1, padx=5, pady=5)
        ttk.Label(self, text="My organization", style="LLabel.TLabel").grid(row=1, column=0, sticky='W', padx=5, pady=5)
        self.organization = FakeEntry(self, self.groups[keys[0].split()[0]], width=6)
        self.organization.grid(row=1, column=1, sticky="W", padx=5, pady=5)
        #self.pack(expand=tk.NO, fill=tk.BOTH)
        self.update()

    def group_changed(self, selected):
        key = selected.split()[0]
        self.organization.set(self.groups.get(key))

    def get(self):
        return self.menu.get().split()[0]


class DestWnd(ttk.LabelFrame):

    def __init__(self, parent):
        super().__init__(parent, text='Destinations', padding=(0, 0, 5, 0))
        self.groups, self.sessions = self.get_groups()
        self.menu = {}
        # AutoComplete box for sessions
        ttk.Label(self, text='Session', style="LLabel.TLabel").grid(row=0, column=0, sticky='W', padx=5, pady=5)
        self.menu['session'] = AutoComplete(self, '', self.sessions)
        self.menu['session'].grid(row=0, column=1, sticky='W', padx=5, pady=5)
        self.menu['session'].bind('<FocusOut>', self.test_session)
        ToolTip(self.menu['session'], text='Select session to contact all stations and centers involved in session')
        # AutoComplete box for stations
        ttk.Label(self, text=vcc_groups['NS'], style="LLabel.TLabel").grid(row=1, column=0, sticky='W', padx=5, pady=5)
        self.menu['NS'] = AutoComplete(self, '', self.groups['NS'], separator=',')
        self.menu['NS'].grid(row=1, column=1, sticky='W', padx=5, pady=5)
        self.menu['NS'].bind('<FocusOut>', self.test_stations)
        ToolTip(self.menu['NS'], text='Input many stations by using comma as separator')
        # Menu for other groups
        self.add_group('CC', vcc_groups['CC'], 2, 0)
        self.add_group('OC', vcc_groups['OC'], 3, 0)
        self.add_group('CO', vcc_groups['CO'], 4, 0)
        self.add_group('AC', vcc_groups['AC'], 5, 0)

        self.update()

    def add_group(self, key, info, row, column):
        ttk.Label(self, text=info, style="LLabel.TLabel").grid(row=row, column=column, sticky='W', padx=5, pady=5)
        self.menu[key] = XMenu(self, 'Select...', *(self.groups[key] + ['all', 'Clear']),
                               command=lambda selection: self.group_changed(key, selection))
        self.menu[key].grid(row=row, column=column+1, sticky='W', padx=5, pady=5)

    def group_changed(self, key, selection):
        if selection == 'Clear':
            self.menu[key].reset(text='Select...')

    def test_session(self, event):
        if ses_id := (widget := self.menu['session']).get():
            if widget.lost_focus() and ses_id.lower() not in self.sessions:
                messagebox.showerror('Session not valid', f'{ses_id} not an IVS session')
                widget.focus_set()

    def test_stations(self, event):
        if text := (widget := self.menu['NS']).get():
            if widget.lost_focus():
                if bad := [sta_id for sta_id in list(map(clean, text.split(','))) if sta_id not in self.groups['NS']]:
                    messagebox.showerror('Invalid stations', f'{",".join(bad)} are not valid station codes')
                    widget.focus_set()

    @staticmethod
    def get_groups():
        groups = {}
        try:
            with VCC() as vcc:
                groups['CC'] = [center['code'] for center in vcc.get('/catalog/coordinating').json()]
                groups['OC'] = [center['code'] for center in vcc.get('/catalog/operations').json()]
                groups['CO'] = [center['code'] for center in vcc.get('/catalog/correlator').json()]
                groups['AC'] = [center['code'] for center in vcc.get('/catalog/analysis').json()]
                groups['NS'] = [sta['code'] for sta in vcc.get('/stations').json()]

                begin, end = date(1979, 1, 1), date(2100, 1, 1)
                sessions = sorted(vcc.get('/sessions', params={'begin': begin, 'end': end}).json())
                return groups, sessions
        except VCCError as err:
            messagebox.showerror('VCC problem', f'{str(err)}')
            sys.exit(1)

    def get(self):
        lst = []
        for group, widget in self.menu.items():
            if group == 'session':
                if ses_id := widget.get():
                    lst.append((group, ses_id))
            elif group == 'NS':
                if text := widget.get():
                    lst.extend([(group, code) for code in list(map(clean, text.split(',')))])
            elif not (text := widget.get()).startswith('Select'):
                groups = self.groups[group] if text == 'all' else [text]
                lst.extend([(group, code) for code in groups])
        return lst

    def focus_set(self):
        self.menu['session'].focus_set()


class MsgWnd(ttk.LabelFrame):
    def __init__(self, parent):
        super().__init__(parent, text='Message', padding=(0, 0, 5, 0))

        frame = ttk.Frame(self, padding=(5, 5, 5, 5))
        scroll_bar = tk.Scrollbar(frame, orient='horizontal')
        scroll_bar.pack(side=tk.BOTTOM, fill=tk.X)
        self.text = tk.Text(frame, height=3, width=40, wrap=tk.NONE, xscrollcommand=scroll_bar.set)
        scroll_bar.configure(command=self.text.xview)
        self.text.pack(expand=True, fill='both')
        frame.pack(expand=True, fill='both')
        self.button = ttk.Button(self, text="Send", style='Send.TButton', padding=(5, 5, 5, 5))
        self.button.pack()
        self.update()

    def bind(self, fnc):
        self.button.bind('<Button-1>', lambda event: fnc(self.text.get("1.0", tk.END).strip()))

    def disable(self, style):
        self.button.state(['pressed', 'disabled'])
        style.configure('Send.TButton', relief=tk.SUNKEN)

    def enable(self, style):
        self.button.state(['!pressed', '!disabled'])
        style.configure('Send.TButton', relief=tk.RAISED)

    def focus_set(self):
        self.text.focus_force()


class VCCMessage(tk.Tk):

    def __init__(self):

        super().__init__()

        self.withdraw()  # To avoid window to show before fully designed

        self.title(f"Send Message")

        # Define some styles for ttk widgets
        self.style = ttk.Style(self)
        self.style.theme_use('classic')
        self.style.configure('LLabel.TLabel', anchor='west', padding=(5, 5, 5, 5))
        self.style.configure('Send.TButton', anchor='center', padding=(5, 5, 5, 5))

        # Draw main frame with all sections
        main_frame = ttk.Frame(self, padding=(5, 5, 5, 5))
        self.from_wnd = FromWnd(main_frame)
        self.from_wnd.grid(row=0, column=0, sticky='nsew')
        self.dest_wnd = DestWnd(main_frame)
        self.dest_wnd.grid(row=1, column=0, sticky='nsew')
        self.msg_wnd = MsgWnd(main_frame)
        self.msg_wnd.grid(row=0, column=1, rowspan=2, sticky='nsew')
        self.msg_wnd.bind(self.send_msg_delay)
        main_frame.grid_rowconfigure(1, weight=1)
        main_frame.grid_columnconfigure(1, weight=1)
        main_frame.pack(expand=tk.YES, fill=tk.BOTH)
        main_frame.update()
        self.minsize(main_frame.winfo_reqwidth(), main_frame.winfo_reqheight())

        self.deiconify()  # Ok to show it

    def send_msg(self, msg):
        if not msg:
            messagebox.showerror('No message', 'You must write a message')
            return self.msg_wnd
        if not (targets := self.dest_wnd.get()):
            messagebox.showerror('No recipients', 'You must select at least one recipient from destination groups')
            return self.dest_wnd
        try:
            data = {'message': msg, 'targets': targets}
            with VCC(self.from_wnd.get()) as vcc:
                rsp = vcc.post('/messages/urgent', data=data)
                messagebox.showinfo('Message sent', rsp.json().capitalize() if rsp else rsp.text)
        except VCCError as exc:
            messagebox.showerror('Problem sending message', f'Failed uploading urgent message [{str(exc)}]')
        return None

    def send_msg_delay(self, msg):
        self.msg_wnd.disable(self.style)
        if wnd := self.send_msg(msg):
            wnd.focus_set()
        self.after(300, lambda: self.msg_wnd.enable(self.style))

    def exec(self):
        self.mainloop()
