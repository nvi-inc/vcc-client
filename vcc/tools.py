import json
import sys
from subprocess import Popen

from tkinter import *
from tkinter import ttk
from tkinter import messagebox

from vcc import json_decoder
from vcc.windows import MessageBox


class Sessions:
    header = {'ID': (25, E, NO), 'CODE': (100, W, NO), 'TYPE': (125, W, NO), 'DATE': (100, CENTER, NO),
              'TIME': (50, CENTER, NO), 'DUR': (50, CENTER, NO),
              'STATIONS': (300, W, YES), 'SKED': (50, CENTER, NO), 'CORR': (50, CENTER, NO),
              'SUBM': (50, CENTER, NO), 'STATUS': (100, W, NO)}

    def __init__(self, title, sessions, master=False, dashboard=False):
        if not master:
            self.header.pop('STATUS')
        width, height = sum([info[0] for info in self.header.values()]), 150
        root = Tk()
        # Set the size of the tkinter window
        root.geometry(f"{width+20}x{height+30}")
        root.title(title)

        style = ttk.Style(root)
        style.theme_use('clam')

        # Add a frame for TreeView
        frame1 = Frame(root, height=height)
        # Add a Treeview widget
        self.tree = ttk.Treeview(frame1, column=list(self.header.keys()), show='headings', height=5)
        self.tree.place(width=width, height=height)

        vsb = ttk.Scrollbar(frame1, orient="vertical", command=self.tree.yview)
        vsb.place(width=20, height=height)
        vsb.pack(side='right', fill='y')
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.tag_configure('cancelled', background="red")

        for col, (key, info) in enumerate(self.header.items(), 1):
            self.tree.column(f"# {col}", anchor=info[1], minwidth=0, width=info[0], stretch=info[2])
            self.tree.heading(f"# {col}", text=key)

        for row, ses in enumerate(sessions, 1):
            # Insert the data in Treeview widget
            h, sec = divmod(ses['duration'], 3600)
            cancelled = len(ses['included']) < 2
            if cancelled and not master:
                stations, ses['operations'], ses['correlator'], ses['analysis'] = 'Cancelled', '', '', ''
            else:
                stations = f"{''.join(ses['included'])} -{''.join(ses['removed'])}" if ses['removed'] \
                    else ''.join(ses['included'])
            values = [str(row), ses['code'], ses['type'], ses['start'].strftime('%Y-%m-%d'),
                      ses['start'].strftime('%H:%M'), f'{h:02d}:{int(sec/60):02d}', stations, ses['operations'],
                      ses['correlator'], ses['analysis'], ses.get('status', '')]
            if not master:
                values = values[:-1]
            self.tree.insert('', 'end', text="1", values=values, tag="cancelled" if cancelled else "")

        if dashboard:
            self.tree.bind("<Double-1>", self.on_double_click)

        self.tree.pack(expand=YES, fill=BOTH)
        frame1.pack(expand=YES, fill=BOTH)

        frame2 = Frame(root, height=30)

        exit_button = Button(frame2, text="Done", command=root.destroy)
        exit_button.pack(pady=5)
        frame2.pack(expand=NO, fill=BOTH)

        root.mainloop()

    def on_double_click(self, event):
        item = self.tree.item(self.tree.identify('row', event.x, event.y))
        try:
            cmd = f'dashboard {item["values"][1]}'
            Popen([cmd], shell=True, stdin=None, stdout=None, stderr=None, close_fds=True)
        except IndexError:
            pass


def show_message(title, message, icon):
    #root = Tk()
    #root.withdraw()
    #messagebox.showinfo(title, message.replace('<br>', '\n'))
    root = Tk()
    root.withdraw()
    MessageBox(root, title, message, icon=icon, exit_on_close=True)
    root.mainloop()


def main():
    import argparse

    parser = argparse.ArgumentParser(description='Display message')
    parser.add_argument('-s', '--sessions', help='show sessions', action='store_true', required=False)
    parser.add_argument('-m', '--master', help='show sessions', action='store_true', required=False)
    parser.add_argument('-db', '--dashboard', help='launch dashboard', action='store_true', required=False)

    parser.add_argument('title')
    parser.add_argument('message')
    parser.add_argument('icon', nargs='?')

    args = parser.parse_args()

    if args.sessions or args.master:
        sessions = json_decoder(json.loads(args.message))
        Sessions(args.title, sessions, args.master, args.dashboard)
    else:
        show_message(args.title, args.message, args.icon)


if __name__ == '__main__':

    sys.exit(main())
