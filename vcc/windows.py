import tkinter

from pathlib import Path
#import pkg_resources
from importlib import resources
import sys

from tkinter import *
from tkinter import font


class MessageBox(Toplevel):
    icons = dict(info='info', warning='warning', urgent='urgent')

    def __init__(self, root, title, message, icon=None, exit_on_close=False, exec_fnc=None):
        super().__init__(root)

        self.exit_on_close = exit_on_close
        self.exec_function = exec_fnc

        print('in message box')
        message = message.replace("<br>", "\n")

        icon = self.icons.get(icon, self.icons['info'])
        #self.pic = PhotoImage(file=pkg_resources.resource_filename(__name__, f'images/{icon}.png'))
        self.pic = PhotoImage(file=Path(resources.files('vcc'), 'images', f'{icon}.png'))
        self.msg_icon = Label(self, image=self.pic)
        self.msg_icon.grid(row=0, column=0, padx=5, pady=5, sticky='nw')
        fd = font.nametofont("TkDefaultFont").actual()
        subject_font = font.Font(name='subject', family=fd['family'], size=fd['size']+6, weight='bold')
        self.subject = Label(self, text=title, anchor='w', font=subject_font)
        self.subject.grid(row=0, column=1, padx=5, pady=5, sticky='nsew')
        msg_font = font.Font(name='msg', family=fd['family'], size=fd['size'], weight='bold')
        self.message = Label(self, text=message, anchor='nw', justify=LEFT, font=msg_font)
        self.message.grid(row=1, column=1, padx=5, sticky='new')
        self.done = Button(self, text='Ok', command=self.destroy, anchor='s')
        self.done.grid(row=2, column=0, columnspan=2, padx=5, pady=5, sticky='s')
        self.columnconfigure(1, weight=1)
        self.rowconfigure(2, weight=1)
        self.update()
        height = self.msg_icon.winfo_reqheight() + self.message.winfo_reqheight()
        height += self.done.winfo_reqheight() + 30
        width = max(self.subject.winfo_reqwidth(), self.message.winfo_reqwidth()) + 10
        width = max(400, self.msg_icon.winfo_reqwidth() + width + 10)
        self.geometry(f"{width}x{height}")

    def destroy(self):
        super().destroy()
        if self.exit_on_close:
            self.master.destroy()
        if self.exec_function:
            self.exec_function()

    def refresh(self, title, message, icon=None):

        icon = self.icons.get(icon, self.icons['info'])
        self.pic = PhotoImage(file=Path(resources.files('vcc'), 'images', f'{icon}.png'))
        self.msg_icon.config(image=self.pic)
        self.subject.config(text=title)
        self.message.config(text=message.replace("<br>", "\n"))
        self.update()
        height = self.msg_icon.winfo_reqheight() + self.message.winfo_reqheight()
        height += self.done.winfo_reqheight() + 30
        width = max(self.subject.winfo_reqwidth(), self.message.winfo_reqwidth()) + 10
        width = max(400, self.msg_icon.winfo_reqwidth() + width + 10)
        self.geometry(f"{width}x{height}")
        self.wm_attributes("-topmost", True)
        self.focus()
        self.wm_attributes("-topmost", False)

def main():

    import argparse

    parser = argparse.ArgumentParser(description='Display message')
    parser.add_argument('-t', '--title', help='title', required=True)
    parser.add_argument('-m', '--message', help='message', required=True)
    parser.add_argument('-i', '--icon', help='icon', default='info', required=False)
    parser.add_argument('-D', '--display', help='display', required=False)

    args = parser.parse_args()

    try:
        root = Tk(screenName=args.display)
    except tkinter.TclError:
        return
    root.withdraw()
    MessageBox(root, args.title, args.message, args.icon, exit_on_close=True)
    root.mainloop()




if __name__ == '__main__':

    sys.exit(main())
