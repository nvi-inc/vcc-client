import json
import sys
from datetime import datetime

from tkinter import *
from tkinter import ttk
from tkinter import messagebox

from vcc import settings, VCCError
from vcc.server import VCC


class Downtime:
    def __init__(self, sta_id):
        self.station = sta_id
        self.api = None
        self.title = f''

    def init_wnd(self, title):
        header = {'Problem': (100, E, NO), 'Start': (100, W, NO), 'End': (250, W, YES)}
        width, height = sum([info[0] for info in header.values()]), 150
        root = Tk()
        # Set the size of the tkinter window
        root.geometry(f"{width + 20}x{height + 30}")
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
                      ses['start'].strftime('%H:%M'), f'{h:02d}:{int(sec / 60):02d}', stations, ses['operations'],
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

    def get_information(self):
        try:
            rsp = self.api.get(f'/stations/{self.sta_id}')
            if not rsp:
                raise VCCError(rsp.text)
            self.station = json_decoder(rsp.json())
            rsp = self.api.get(f'/downtime/')
            if not rsp:
                raise VCCError(rsp.text)
            DowntimeRecord.reasons = json_decoder(rsp.json())
            rsp = self.api.get(f'/downtime/{self.sta_id}')
            records = json_decoder(rsp.json()) if rsp else []
            today = datetime.utcnow().replace(hour=0, minute=0, second=0)
            self.downtime = [rec for rec in records if not rec['end'] or rec['end'] >= today]
            return True
        except VCCError as exc:
            print(f'Failed to get information from VCC for {self.sta_id}! [{str(exc)}]')
            return False

    def exec(self):
        try:
            # Connect to VCC
            with VCC(self.group_id) as vcc:
                self.api = vcc.get_api()
                self.get_information()  # Get existing data

                if self.edit and self.can_update:
                    self.use_interface()  # Popup window interface
                elif not self.downtime:  # Print row for every downtime record
                    print(f'\nNO downtime period scheduled for {self.sta_id.capitalize()} - {self.station["name"]}\n')
                elif self.csv:
                    [print(f'{dt["reason"]},{datetime_str(dt["start"])},'
                           f'{datetime_str(dt["end"], "unknown")},{dt["comment"]}') for dt in self.downtime]
                else:
                    title = f'Scheduled downtime for {self.sta_id.capitalize()} - {self.station["name"]}'

                    hdr = ['Problem', 'Start', 'End', 'Comment']
                    table = [[dt['reason'], datetime_str(dt['start']), datetime_str(dt['end'], 'unknown'),
                              dt['comment']] for dt in self.downtime]
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
    parser.add_argument('station', help='station code')

    args = settings.init(parser.parse_args())

    Downtime(args.station, args.edit, args.csv).exec()


if __name__ == '__main__':

    sys.exit(main())
