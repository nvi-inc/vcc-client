import re
from datetime import datetime

import tkinter as tk
from tkinter import ttk
from tkcalendar import DateEntry


class XCombobox(ttk.Combobox):
    def __init__(self, parent, **kwargs):
        self.var = tk.StringVar(parent)
        kwargs['textvariable'] = self.var
        if 'postcommand' in kwargs:
            self.var.trace('w', callback=kwargs['postcommand'])
            kwargs['postcommand'] = None

        super().__init__(parent, **kwargs)

    def reset(self, text='', state='disabled', values=None):
        if values:
            self['values'] = values
            self.configure(values=values)
        self.var.set(text)
        self.configure(state=state)

    def get(self):
        return self.var.get()

    def set(self, value):
        return self.var.set(value)


class XEntry(tk.Entry):
    def __init__(self, parent, text='', on_change=None, **kwargs):
        self.var = tk.StringVar(parent, text)
        if on_change:
            self.var.trace('w', on_change)
        kwargs['textvariable'] = self.var
        super().__init__(parent, **kwargs)

    def reset(self, text='', state='disabled'):
        self.var.set(text)
        self.configure(state=state)

    def get(self):
        return self.var.get()

    def set(self, value):
        self.var.set(value)


class FakeEntry(tk.Label):
    def __init__(self, parent, text='', **kwargs):
        super().__init__(parent, text=text, borderwidth=1, height=1, **kwargs)
        self.bg, self.fg = self['background'], self['foreground']
        self.configure(relief='sunken')
        self.configure(background='light gray', foreground=self.fg)

    def reset(self, text='', state='disabled'):
        self.configure(text=text)

        if state == 'normal':
            self.configure(background="white", foreground="black")
        else:
            self.configure(background='light gray', foreground=self.fg)

    def set(self, value):
        self.configure(text=value)


class XMenu(ttk.OptionMenu):
    def __init__(self, parent, text, *values, **kwargs):
        self.var = tk.StringVar(parent)
        super().__init__(parent, self.var, text, *values, **kwargs)
        width = max(len(max(values, key=len)), len(text))
        self.configure(width=width)

    def reset(self, text='', state='normal'):
        self.var.set(text)
        self.configure(state=state)

    def get(self):
        return self.var.get()

    def set(self, value):
        return self.var.set(value)


class XDate(DateEntry):

    def __init__(self, frame, callback):
        self.value = tk.StringVar()

        super().__init__(frame, selectmode='day', date_pattern='yyyy-MM-dd', textvariable=self.value)

        self._set_text('')

        self.default_parse_date, self.parse_date = self.parse_date, self.modified_parse_date
        self.bind("<<DateEntrySelected>>", callback)
        self.value.trace_variable('w', callback)

    def set_date(self, date):
        old = self.cget('state')
        self.configure(state='normal')
        super().set_date(date) if date else self._set_text('')
        self.configure(state=old)

    def get_datetime(self):
        return datetime.fromisoformat(t.isoformat()) if (t := self.get_date()) else None

    def reset(self, state, min_date, value):
        self.configure(state=state, mindate=min_date)
        self.set_date(value)

    def _validate_date(self):
        return super()._validate_date() if self.get() else True

    def modified_parse_date(self, text):
        return self.default_parse_date(text) if text else None


class AutoComplete(tk.Entry):

    def __init__(self, parent, text, choices, max_rows=5, separator='', **kwargs):
        self.bindings = {}
        self.var = tk.StringVar(parent, text)
        super().__init__(parent, textvariable=self.var, **kwargs)

        self.choices, self.max_rows, self.separator = choices, max_rows, separator
        self.frame = None
        self.listbox = self.scrollbar = None
        self.var.trace('w', self.changed)
        self.bind_entry()
        self.bind('<FocusOut>', self.focus_out, is_outside=False)

    def bind_entry(self):
        self.bind("<Return>", self.selection, is_outside=False)
        self.bind("<Up>", self.arrow, is_outside=False)
        self.bind("<Down>", self.arrow, is_outside=False)

    def unbind_entry(self):
        self.unbind("<Return>")
        self.unbind("<Up>")
        self.unbind("<Down>")

    def filter(self):
        if not (text := self.var.get()) or (self.separator and not (text := text.split(self.separator)[-1])):
            return []
        pattern = re.compile(fr'{text}.*', re.IGNORECASE)
        return [w for w in self.choices if re.match(pattern, w)]

    def show_scrollbar(self):
        if not self.scrollbar:
            self.scrollbar = tk.Scrollbar(self.frame)
            self.scrollbar.configure(width=15)
            self.scrollbar.pack(side=tk.RIGHT, fill=tk.BOTH)
            self.listbox.configure(yscrollcommand=self.scrollbar.set)
            self.scrollbar.configure(command=self.listbox.yview)

    def hide_scrollbar(self):
        if self.scrollbar:
            self.scrollbar.destroy()
            self.scrollbar = None
            self.listbox.configure(yscrollcommand="")

    def changed(self, *args):

        if words := self.filter():
            if not self.frame:  # _up:
                self.frame = tk.Canvas()  # self.winfo_parent())
                x, y = self.master.winfo_x() + self.winfo_x() + 5, self.master.winfo_y() + self.winfo_y()
                self.frame.place(x=x, y=y + self.winfo_height())

                self.listbox = tk.Listbox(self.frame, borderwidth=0, highlightthickness=0)
                self.listbox.bind("<Double-Button-1>", self.selection)
                self.listbox.bind("<Return>", self.selection)
                self.listbox.bind("<Escape>", self.selection)
                self.listbox.bind("<FocusOut>", self.focus_out)
                self.listbox.configure(height=min(self.max_rows, len(words)))
                self.listbox.pack(side=tk.LEFT, fill=tk.BOTH)
                self.bind_entry()
            elif len(words) != self.listbox.size():
                self.listbox.configure(height=min(len(words), self.max_rows))

            self.listbox.delete(0, tk.END)
            self.show_scrollbar() if len(words) > self.max_rows else self.hide_scrollbar()
            self.listbox.insert(tk.END, *words)
            self.listbox.selection_set(first=0)
        elif self.frame:  # _up
            self.unbind_entry()
            self.frame.destroy()
            self.frame = self.listbox = self.scrollbar = None

    def bind(self, event, fnc, is_outside=True):
        if not is_outside:
            self.bindings[event] = self.bindings.get(event, None)
            super().bind(event, fnc)
        elif event in self.bindings:
            self.bindings[event] = fnc
        else:
            self.bindings[event] = fnc
            super().bind(event, fnc)

    def selection(self, event):
        if self.frame:
            # Update text with listbox selection
            if event.keysym != 'Escape':
                text = self.listbox.get(tk.ACTIVE)
                if self.separator:
                    text = self.separator.join(self.var.get().split(self.separator)[:-1] + [text])
                self.var.set(text)
            # Close listbox
            self.close_listbox()
            self.focus_set()
        if fnc := self.bindings.get("<Return>", None):
            fnc(event)

    def close_listbox(self):
        if self.frame:
            self.icursor(tk.END)
            self.unbind_entry()
            self.frame.destroy()
            self.frame = self.listbox = self.scrollbar = None

    def arrow(self, event):
        index = 0 if event.keysym == 'Down' else tk.END
        self.listbox.selection_set(first=index)
        self.listbox.activate(index)
        self.listbox.see(index)
        self.listbox.focus_set()
        if fnc := self.bindings.get("<Down>", self.bindings.get("<Up>")):
            fnc(event)

    def focus_out(self, event):
        try:
            widget = self.nametowidget(name) if (name := self.focus_get()) else None
        except KeyError:
            widget = None
        if widget != self.listbox:
            self.close_listbox()
        if fnc := self.bindings.get("<FocusOut>", None):
            fnc(event)

    def lost_focus(self):
        widget = self.nametowidget(name) if (name := self.focus_get()) else None
        return widget != self.listbox


class ToolTip:
    def __init__(self, widget, text=None):

        self.widget, self.text = widget, text
        self.tooltip = None

        self.widget.bind('<Enter>', self.on_enter)
        self.widget.bind('<Leave>', self.on_leave)

    def on_enter(self, event):
        self.tooltip = tk.Toplevel()
        self.tooltip.overrideredirect(True)
        try:
            label = tk.Label(self.tooltip, text=self.text, borderwidth=0)
            label.pack()
            self.tooltip.update()
            y = self.widget.winfo_rooty() - label.winfo_height() - 2
            self.tooltip.geometry(f'+{self.widget.winfo_rootx()}+{y}')
        except tk.TclError:  # To avoid problems when moving pointer too fast
            pass

    def on_leave(self, event):
        self.tooltip.destroy()


