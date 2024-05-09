import time
import pkg_resources
import sys
import os
import psutil

from tkinter import *
from tkinter import ttk
from tkinter import font
import signal

from threading import Thread, Event


class MessageBox(Toplevel):
    icons = dict(info='info', warning='warning', urgent='urgent')

    def __init__(self, root, title, message, icon=None, exit_on_close=False):

        super().__init__(root)
        message = message.replace("<br>", "\n")

        stl = ttk.Style(self)
        stl.configure('TButton', anchor='south')

        icon = self.icons.get(icon, self.icons['info'])
        self.pic = PhotoImage(file=pkg_resources.resource_filename(__name__, f'images/{icon}.png'))
        self.msg_icon = Label(self, image=self.pic)
        self.msg_icon.grid(row=0, column=0, padx=5, pady=5, sticky='nw')
        fd = font.nametofont("TkDefaultFont").actual()
        subject_font = font.Font(name='subject', family=fd['family'], size=fd['size']+6, weight='bold')
        self.subject = Label(self, text=title, anchor='w', font=subject_font)
        self.subject.grid(row=0, column=1, padx=5, pady=5, sticky='nsew')
        msg_font = font.Font(name='msg', family=fd['family'], size=fd['size'], weight='bold')
        self.message = Label(self, text=message, anchor='nw', justify=LEFT, font=msg_font)
        self.message.grid(row=1, column=1, padx=5, sticky='new')
        self.done = ttk.Button(self, text='Ok', command=self.destroy, style='TButton')  #anchor='s')  #
        self.done.grid(row=2, column=0, columnspan=2, padx=5, pady=5, sticky='s')
        self.columnconfigure(1, weight=1)
        self.rowconfigure(2, weight=1)
        self.update()
        height = self.msg_icon.winfo_reqheight() + self.message.winfo_reqheight()
        height += self.done.winfo_reqheight() + 30
        width = max(self.subject.winfo_reqwidth(), self.message.winfo_reqwidth()) + 10
        width = max(400, self.msg_icon.winfo_reqwidth() + width + 10)
        self.geometry(f"{width}x{height}")
        self.opened = True

    def destroy(self):
        super().destroy()
        self.opened = False


def get_displays(all_users=False, display=None):

    displays = [display if display else os.environ.get('DISPLAY', None)]
    if all_users:
        oper = [user.pid for user in psutil.users() if user.name == 'oper']
        for prc in psutil.process_iter():
            for parent in prc.parents():
                if parent.pid in oper:
                    try:
                        displays.append(prc.environ().get('DISPLAY', None))
                    finally:
                        break

    return list(filter(None, list(set(displays))))


class Test(Thread):

    def __init__(self, title, message, icon):
        super().__init__()

        signal.signal(signal.SIGTERM, self.terminate)

        self.title, self.message, self.icon = title, message, icon

        self.stopped = Event()

    def terminate(self, sig, alarm):
        self.stopped.set()

    def run(self):

        n = 0

        main_wnd = Tk()
        main_wnd.withdraw()
        while not self.stopped.wait(0.1):
            main_wnd.update()
            if not n % 100:
                MessageBox(main_wnd, self.title, f'{self.message}\nstep {n}', icon=self.icon)
            n += 1


def main():
    import argparse

    parser = argparse.ArgumentParser(description='Display message')
    parser.add_argument('title')
    parser.add_argument('message')
    parser.add_argument('icon', nargs='?')

    args = parser.parse_args()

    test = Test(args.title, args.message, args.icon)
    test.run()


if __name__ == '__main__':

    sys.exit(main())
