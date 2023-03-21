import json
import sys
from datetime import datetime

from tkinter import *
from tkinter import ttk
from tkinter import messagebox

from vcc import json_decoder


def show_sessions(title, sessions, master=False):
    header = {'ID': (25, E, NO), 'CODE': (100, W, NO), 'TYPE': (125, W, NO), 'DATE': (100, CENTER, NO),
              'TIME': (50, CENTER, NO), 'DUR': (50, CENTER, NO),
              'STATIONS': (300, W, YES), 'SKED': (50, CENTER, NO), 'CORR': (50, CENTER, NO),
              'SUBM': (50, CENTER, NO), 'STATUS': (100, W, NO)}
    if not master:
        header.pop('STATUS')
    width, height = sum([info[0] for info in header.values()]), 150
    root = Tk()
    # Set the size of the tkinter window
    root.geometry(f"{width+20}x{height+30}")
    root.title(title)

    style = ttk.Style(root)
    style.theme_use('clam')

    # Add a frame for TreeView
    frame1 = Frame(root, height=height)
    # Add a Treeview widget
    tree = ttk.Treeview(frame1, column=list(header.keys()), show='headings', height=5)
    tree.place(width=width, height=height)

    vsb = ttk.Scrollbar(frame1, orient="vertical", command=tree.yview)
    vsb.place(width=20, height=height)
    vsb.pack(side='right', fill='y')
    tree.configure(yscrollcommand=vsb.set)
    tree.tag_configure('cancelled', background="red")

    for col, (key, info) in enumerate(header.items(), 1):
        tree.column(f"# {col}", anchor=info[1], minwidth=0, width=info[0], stretch=info[2])
        tree.heading(f"# {col}", text=key)

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
        tree.insert('', 'end', text="1", values=values, tag="cancelled" if cancelled else "")

    tree.pack(expand=YES, fill=BOTH)
    frame1.pack(expand=YES, fill=BOTH)

    frame2 = Frame(root, height=30)

    exit_button = Button(frame2, text="Done", command=root.destroy)
    exit_button.pack(pady=5)
    frame2.pack(expand=NO, fill=BOTH)

    root.mainloop()


def show_message(title, message):
    root = Tk()
    root.withdraw()
    messagebox.showinfo(title, message.replace('<br>', '\n'))


def get_sessions():
    data = """[{"code": "v23079", "operations": "NASA", "start": "2023-03-20T18:30:00", "master": "intensive", "correlator": "WASH", "correlated": null, "updated": "2023-03-14T16:22:51", "analysis": "NASA", "type": "VGOS-INT-A", "duration": 3600, "analyzed": null, "scheduled": null, "included": ["K2", "Oe"], "removed": [], "schedule": null, "has_vlba": false}, {"code": "v23080", "operations": "NASA", "start": "2023-03-21T18:30:00", "master": "intensive", "correlator": "WASH", "correlated": null, "updated": "2023-03-14T16:22:52", "analysis": "NASA", "type": "VGOS-INT-A", "duration": 3600, "analyzed": null, "scheduled": null, "included": ["K2", "Oe"], "removed": [], "schedule": null, "has_vlba": false}, {"code": "vo3081", "operations": "NASA", "start": "2023-03-22T18:00:00", "master": "standard", "correlator": "HAYS", "correlated": null, "updated": "2023-03-14T16:03:06", "analysis": "NASA", "type": "VGOS-OPS", "duration": 86400, "analyzed": null, "scheduled": null, "included": ["Gs", "Hb", "K2", "Ke", "Mg", "Nn", "Oe", "Wf", "Yj"], "removed": ["Ow", "Ws"], "schedule": null, "has_vlba": false}, {"code": "v23081", "operations": "NASA", "start": "2023-03-22T18:30:00", "master": "intensive", "correlator": "WASH", "correlated": null, "updated": "2023-03-14T16:22:52", "analysis": "NASA", "type": "VGOS-INT-A", "duration": 3600, "analyzed": null, "scheduled": null, "included": ["K2", "Oe"], "removed": [], "schedule": null, "has_vlba": false}, {"code": "v23082", "operations": "NASA", "start": "2023-03-23T18:30:00", "master": "intensive", "correlator": "WASH", "correlated": null, "updated": "2023-03-14T16:22:52", "analysis": "NASA", "type": "VGOS-INT-A", "duration": 3600, "analyzed": null, "scheduled": null, "included": ["K2", "Oe"], "removed": [], "schedule": null, "has_vlba": false}, {"code": "v23083", "operations": "NASA", "start": "2023-03-24T18:45:00", "master": "intensive", "correlator": "WASH", "correlated": null, "updated": "2023-03-14T16:22:52", "analysis": "NASA", "type": "VGOS-INT-A", "duration": 3600, "analyzed": null, "scheduled": null, "included": ["K2", "Oe"], "removed": [], "schedule": null, "has_vlba": false}]
"""
    return json_decoder(json.loads(data))


def main():
    import argparse

    parser = argparse.ArgumentParser(description='Display message')
    parser.add_argument('-s', '--sessions', help='show sessions', action='store_true', required=False)
    parser.add_argument('-m', '--master', help='show sessions', action='store_true', required=False)
    parser.add_argument('title')
    parser.add_argument('message')

    args = parser.parse_args()

    if args.sessions or args.master:
        sessions = json_decoder(json.loads(args.message))
        show_sessions(args.title, sessions, args.master)
    else:
        show_message(args.title, args.message)


if __name__ == '__main__':

    sys.exit(main())
