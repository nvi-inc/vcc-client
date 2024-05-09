import json
import sys

from tkinter import *
from tkinter import ttk

from vcc import json_decoder, vcc_cmd
from vcc.windows import MessageBox


class Sessions:
    header = {'ID': (25, E, NO), 'CODE': (100, W, NO), 'TYPE': (125, W, NO), 'DATE': (100, CENTER, NO),
              'TIME': (50, CENTER, NO), 'DUR': (50, CENTER, NO),
              'STATIONS': (300, W, YES), 'SKED': (50, CENTER, NO), 'CORR': (50, CENTER, NO),
              'SUBM': (50, CENTER, NO)}

    def __init__(self, title, sessions, master=False, display=None):
        if master:
            self.header['STATUS'] = (100, W, NO)
        width = sum([info[0] for info in self.header.values()])
        height = 350 if len(sessions) > 7 else 200
        root = Tk(screenName=display)
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
            stations = f"{''.join(ses['included'])} -{''.join(ses['removed'])}" \
                if ses['removed'] else ''.join(ses['included'])
            stations = f"{stations} Cancelled" if cancelled else stations
            values = [str(row), ses['code'], ses['type'], ses['start'].strftime('%Y-%m-%d'),
                      ses['start'].strftime('%H:%M'), f'{h:02d}:{int(sec/60):02d}', stations, ses['operations'],
                      ses['correlator'], ses['analysis']]
            if master:
                values.append(ses.get('status', ''))
            self.tree.insert('', 'end', text="1", values=values, tag="cancelled" if cancelled else "")

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
        vcc_cmd('vcc dashboard', item["values"][1])


def main():
    import argparse

    parser = argparse.ArgumentParser(description='Display message')
    parser.add_argument('-M', '--master', help='show sessions', action='store_true', required=False)
    parser.add_argument('-t', '--title', help='title', required=True)
    parser.add_argument('-m', '--message', help='message', required=True)
    parser.add_argument('-D', '--display', help='display', required=False)

    args = parser.parse_args()
    data = json_decoder(json.loads(args.message))
    Sessions(args.title, data, args.master, args.display)


if __name__ == '__main__':

    sys.exit(main())
