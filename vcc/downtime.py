import sys
from datetime import datetime

from tabulate import tabulate
from PyQt5.QtCore import Qt, QDate
from PyQt5.QtWidgets import QMainWindow, QApplication, QWidget, QLineEdit, QStyle, qApp
from PyQt5.QtWidgets import QLabel, QVBoxLayout, QHBoxLayout, QGridLayout, QPushButton
from PyQt5.QtWidgets import QComboBox, QDateTimeEdit

from vcc import settings, VCCError, json_decoder, groups, message_box, error_box
from vcc.server import VCC


# Extract datetime object from QDateTimeEdit
def get_datetime(item):
    try:
        return datetime.strptime(item.text().strip(), '%Y-%m-%d %H:%S UTC')
    except ValueError:
        return None


# Format datetime and return default string on error
def datetime_str(value, default=''):
    try:
        return value.strftime("%Y-%m-%d %H:%M UTC")
    except AttributeError:
        return default


# Class holding all Qt widgets and relation for a downtime record
class DowntimeRecord:

    reasons = []
    names = ['reason', 'start', 'end', 'comment']
    # Functions from main application to update data
    add_row = None
    update_information = None

    def __init__(self, record):
        self.reason = QComboBox()
        self.start, self.end = QDateTimeEdit(calendarPopup=True), QDateTimeEdit(calendarPopup=True)
        self.comment, self.update = QLineEdit(record['comment'] if record else ''), QPushButton('Update')
        self.saved = record

        new = not record

        today = datetime.utcnow()
        today = QDate(today.year, today.month, today.day)

        self.reason.clear()
        self.reason.addItems(self.reasons + ['Select...'])
        self.reason.setCurrentIndex(self.reasons.index(record['reason']) if record else len(self.reasons))
        self.reason.view().setRowHidden(len(self.reasons), True)
        self.reason.activated.connect(lambda: self.activate_fields(today))
        self.reason.setEnabled(new)

        self.start.dateTimeChanged.connect(lambda: self.end.setMinimumDateTime(self.start.dateTime()))
        self.start.setDisplayFormat('yyyy-MM-dd hh:mm UTC')
        self.start.setEnabled(False)
        if record:
            self.start.setDateTime(record['start'])
        else:
            self.start.setMinimumDate(today)
            self.start.setSpecialValueText(' ')
            self.start.setDate(QDate(1900, 1, 1))

        self.end.dateTimeChanged.connect(self.data_changed)
        self.end.calendarWidget().clicked.connect(lambda: self.end.setSpecialValueText(''))
        self.end.setDisplayFormat('yyyy-MM-dd hh:mm UTC')
        if record and record['end']:
            self.end.setDateTime(record['end'])
            self.end.setMinimumDateTime(self.start.dateTime())
        else:
            self.end.setMinimumDate(today)
            self.end.setSpecialValueText(' ')
            self.end.setDate(QDate(1900, 1, 1))
        self.end.setEnabled(not new)
        self.comment.setEnabled(not new)
        self.comment.textChanged.connect(self.data_changed)
        self.update.setEnabled(False)
        self.update.clicked.connect(self.update_vcc)

    # Activate widgets after 'reason' has been selected
    def activate_fields(self, today):
        [item.setEnabled(True) for item in [self.start, self.end, self.comment, self.update]]
        self.start.setSpecialValueText('')
        self.start.setDate(today)
        self.start.setFocus()

    # Create a new record with data from widgets
    def get_new_data(self):
        return {'reason': self.reason.currentText(), 'start': get_datetime(self.start),
                'end': get_datetime(self.end), 'comment': self.comment.text().strip()[:100]}

    # Event indicating that data has changed
    def data_changed(self):
        rec = self.get_new_data()  # get new data
        # Check if different than what is already stored
        changed = not self.saved or any([self.saved[name] != rec[name] for name in self.names])
        self.update.setEnabled(changed)  # Enable/disable 'update' widget

    # Update the VCC with new data
    def update_vcc(self):
        rec = self.get_new_data()
        if self.update_information(rec):
            if not self.saved:  # This was a new record. Add new row
                self.add_row()
            self.saved = rec
            [item.setEnabled(False) for item in [self.reason, self.start, self.update]]


# Class for downtime application
class Downtime(QMainWindow):

    def __init__(self, sta_id, edit, csv):

        self.sta_id, self.edit, self.csv = sta_id, edit, csv
        self.station, self.api, self.codes, self.downtime = None, None, [], []
        self.boxes = self.downtime_grid = None

        self.last_row, self.records = 0, []
        # Set function that will be call by DowntimeRecord to update the interface
        DowntimeRecord.add_row = self.add_downtime_row
        DowntimeRecord.update_information = self.update_information

        for group_id in groups:
            if hasattr(settings.Signatures, group_id):
                self.group_id = group_id
                break
        else:
            raise VCCError('No valid groups in configuration file')
        # Detect if user could update data on VCC
        self.can_update = (self.group_id == 'CC') or \
                          (self.group_id == 'NS' and settings.Signatures.NS[0].lower() == sta_id.lower())

    # Retrieve information from VCC
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

    # Update information on VCC
    def update_information(self, record):
        print(record)
        try:
            rsp = self.api.put(f'/downtime/{self.sta_id}', data=record)
            try:
                answer = rsp.json()
            except ValueError:
                answer = {'error': rsp.text}
        except VCCError as exc:
            answer = {'error': str(exc)}

        if 'error' in answer:
            error_box('Downtime problem', 'Failed updating downtime information', answer['error'])
            return False
        test = [datetime(2022, 10, day, 13, day).strftime('%Y-%m-%d %H:%M') for day in range(1, 15)]
        message_box('Downtime updated', f'Downtime for \"{record["reason"]}\" reason has been updated',
                    f'Starting {datetime_str(record["start"])} until {datetime_str(record["end"], "unknown")}'
                    f'\nSee details for affected sessions',
                    '\n'.join(test))
        return True

    # Init interface for application
    def init_wnd(self):
        super().__init__()

        self.setWindowFlags(Qt.WindowCloseButtonHint | Qt.WindowMinimizeButtonHint)
        self.setWindowTitle(f'Downtime for {self.sta_id.capitalize()} - {self.station["name"]}')
        self.resize(1000, 100)

        widget = QWidget()
        self.boxes = QVBoxLayout()
        self.boxes.addLayout(self.make_downtime_grid())
        self.boxes.addLayout(self.make_footer_box())
        widget.setLayout(self.boxes)
        self.setCentralWidget(widget)

        self.show()

    # Make QGridLayout storing Header row and DowntimeRecord
    def make_downtime_grid(self):
        self.downtime_grid = QGridLayout()
        # Make header
        columns = {'Problem': (0, 1), 'Start': (1, 1), 'End': (2, 1), 'Comment': (3, 5), 'Status': (8,1)}
        [self.downtime_grid.addWidget(QLabel(label), 0, col, 1, width) for label, (col, width) in columns.items()]
        # Insert row for every downtime event
        [self.add_downtime_row(downtime=rec) for rec in self.downtime]
        self.add_downtime_row()  # new empty row
        return self.downtime_grid

    # Add a new row to the downtime_grid
    def add_downtime_row(self, downtime=None):
        row = self.downtime_grid.rowCount()
        rec = DowntimeRecord(downtime)
        self.downtime_grid.addWidget(rec.reason, row, 0)
        self.downtime_grid.addWidget(rec.start, row, 1)
        self.downtime_grid.addWidget(rec.end, row, 2)
        self.downtime_grid.addWidget(rec.comment, row, 3, 1, 5)
        self.downtime_grid.addWidget(rec.update, row, 8)

    # Make footer containing the 'Done' button
    def make_footer_box(self):
        box = QHBoxLayout()
        # Add Done button
        done = QPushButton("Done")
        done.clicked.connect(self.close)
        box.addWidget(done)
        box.addStretch(1)
        return box

    # The application with interface was requested
    def use_interface(self):
        app = QApplication(sys.argv)
        self.init_wnd()
        sys.exit(app.exec_())

    # Execute application
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

    parser = argparse.ArgumentParser(description='Access VCC functionalities')
    parser.add_argument('-c', '--config', help='config file', required=False)
    parser.add_argument('-edit', help='use interface to edit downtime', action='store_true')
    parser.add_argument('-csv', help='output data in csv format', action='store_true')
    parser.add_argument('station', help='station code')

    args = settings.init(parser.parse_args())

    Downtime(args.station, args.edit, args.csv).exec()


if __name__ == '__main__':

    sys.exit(main())
