import json
import sys
import tkinter

from datetime import datetime, timedelta

import tkinter as tk
from tkinter import ttk

from vcc import settings, json_decoder, vcc_cmd
from vcc.client import VCC
from vcc.utils import master_types, get_next_sessions


class Sessions(tk.Toplevel):
    header = {'ID': (25, tk.E, tk.NO), 'CODE': (100, tk.W, tk.NO), 'TYPE': (125, tk.W, tk.NO),
              'DATE': (100, tk.CENTER, tk.NO), 'TIME': (50, tk.CENTER, tk.NO), 'DUR': (50, tk.CENTER, tk.NO),
              'STATIONS': (300, tk.W, tk.YES), 'SKED': (50, tk.CENTER, tk.NO), 'CORR': (50, tk.CENTER, tk.NO),
              'SUBM': (50, tk.CENTER, tk.NO)}

    def __init__(self, root, title, sessions, master=False, header_wnd=None):
        super().__init__(root)
        if master:
            self.header['STATUS'] = (100, tk.W, tk.NO)
        width = sum([info[0] for info in self.header.values()])
        height = 350 if len(sessions) > 7 else 200
        extra_heigth = 0
        # Set the size of the tkinter window
        self.geometry(f"{width+20}x{height+30}")
        self.title(title)

        # Add a frame for header_wnd
        if header_wnd:
            frame_hdr = header_wnd(self)
            frame_hdr.pack(expand=tk.NO, fill=tk.BOTH)
            frame_hdr.update()
            extra_heigth = frame_hdr.winfo_reqheight()

        # Add a frame for TreeView
        frame1 = tk.Frame(self, height=height)
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
        self.tree.pack(expand=tk.YES, fill=tk.BOTH)
        frame1.pack(expand=tk.YES, fill=tk.BOTH)

        frame2 = tk.Frame(self, height=30)

        exit_button = tk.Button(frame2, text="Done", command=self.destroy)
        exit_button.pack(pady=5)
        frame2.pack(expand=tk.NO, fill=tk.BOTH)

        self.geometry(f"{width + 20}x{height + extra_heigth + 30}")
        self.update()

        #root.mainloop()

    def on_double_click(self, event):
        item = self.tree.item(self.tree.identify('row', event.x, event.y))
        vcc_cmd('vcc dashboard', item["values"][1])


def upcoming_sessions(ses_type, code, args):
    master = {'int': 'intensive', 'std': 'standard'}.get(ses_type, ('intensive', 'standard'))

    sta_id = code
    with VCC() as vcc:
        session_list, begin, end = get_next_sessions(vcc, sta_id, args.start, args.end, args.days)
        if not session_list:
            return
        now = datetime.utcnow()
        sessions = [json_decoder(rsp.json()) for code in session_list if (rsp := vcc.get(f'/sessions/{code}'))]
        data = [ses for ses in sessions if ses['start'] > now and ses['master'] in master]

        type_str = master_types.get(ses_type, '')
        sta_str = f' for {sta_id.capitalize()}' if sta_id else ''
        when = f" ({begin.date()} to {end.date()})" if sessions else ''
        title = f'List of {type_str}sessions{sta_str}{when}'
        display_option = f'{args.display}' if args.display else ''
        try:
            Sessions(title, data, display_option)
        except tkinter.TclError:
            return


def main():
    import argparse

    parser = argparse.ArgumentParser(description='Display message')
    parser.add_argument('-c', '--config', help='config file', required=True)
    parser.add_argument('-M', '--master', help='show sessions', action='store_true', required=False)
    parser.add_argument('-t', '--title', help='title', required=True)
    parser.add_argument('-m', '--message', help='message', required=True)
    parser.add_argument('-D', '--display', help='display', required=False)

    args = settings.init(parser.parse_args())
    data = []
    with VCC() as vcc, open('/tmp/vcc-wnd.txt', 'w') as f:
        for (code, status) in json_decoder(json.loads(args.message)):
            if rsp := vcc.get(f'/sessions/{code}'):
                data.append(dict(**json_decoder(rsp.json()), **{'status': status}))

    try:
        Sessions(args.title, data, args.master, args.display)
    except tkinter.TclError:
        return


if __name__ == '__main__':

    sys.exit(main())
