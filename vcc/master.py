import re
import sys
from pathlib import Path
from datetime import datetime, timedelta

from PyQt5.QtWidgets import QApplication, QMainWindow, QWidget
from PyQt5.QtWidgets import QPushButton, QGridLayout, QLineEdit, QLabel, QSizePolicy, QCheckBox
from PyQt5.QtWidgets import QComboBox, QFrame, QMessageBox, QStyle, qApp
from PyQt5.QtCore import Qt

from vcc import json_decoder, VCCError
from vcc.server import VCC
from vcc.session import Session

COLUMNS = ['type', 'date', 'code', 'doy', 'time', 'duration', 'stations', 'operations',
           'correlator', 'status', 'dbc', 'analysis', 'del']

UNUSED = ['date', 'doy', 'time', 'status', 'del', 'dbc']
TYPES = {'INTENSIVES': 'intensive'}


# Update VCC Network stations with local file
def update_network(lines):

    # Extract data from file
    is_station = re.compile(' (?P<code>\w{2}) (?P<name>.{8}) (?P<domes>.{9}) (?P<cdp>.{4}) (?P<description>.+)$').match
    network = {rec['code']: rec.groupdict() for line in lines if (rec := is_station(line))}
    # Set flag for VLBA stations
    vlba = network['Va']['description'] + 'Va'
    network = {sta: dict(**data, **{'is_vlba': sta in vlba}) for (sta, data) in network.items()}

    # Get existing information from VOC
    try:
        with VCC('CC') as vcc:
            api = vcc.get_api()
            rsp = api.get('/stations')
            if not rsp:
                raise VCCError(rsp.text)
            old = {data['code']: data for data in rsp.json() if data.pop('updated')}
            if network == old:
                raise VCCError('No changes in network stations')
            added = {code: value for (code, value) in network.items() if old.get(code) != value}
            if added:
                rsp = api.post('/stations', data=added)
                if not rsp:
                    raise VCCError(rsp.text)
                [print(f'{index:4d} {sta} {status}') for index, (sta, status) in enumerate(rsp.json().items(), 1)]
            for index, sta_id in enumerate([code for code in old if code not in network], 1):
                rsp = api.delete(f'/stations/{sta_id}')
                if not rsp:
                    raise VCCError(rsp.text)
                print(f'{index:4d} {sta_id} {rsp.json()[sta_id]}')
    except VCCError as exc:
        print(str(exc))


# Update codes for centers or dbc
def update_codes(lines):
    codes = {'SKED CODES': 'operations', 'SUBM CODES': 'analysis', 'CORR CODES': 'correlator'}

    # Read file and extract data
    data, in_section = {}, False
    key = None
    for line in lines:
        if in_section:
            if key in line:
                in_section = False
            else:
                code = line.strip().split()[0].strip()
                data[key][code] = {'code': code, 'description': line.strip()[len(code):].strip()}
        elif keys := [key for key in codes if key in line]:
            in_section = True
            key = keys[0]
            data[key] = {}

    if data:
        try:
            with VCC('CC') as vcc:
                api = vcc.get_api()
                for key, name in codes.items():
                    rsp = api.post(f'/catalog/{name}', data=data[key])
                    if not rsp:
                        raise VCCError(rsp.text)
                    print(f'{len([code for code, status in rsp.json().items() if status == "updated"])} '
                          f'of {len(data[key])} {key} where updated')
        except VCCError as exc:
            print(str(exc))


def decode_duration(text):
    hours, minutes = [float(txt.strip() or '0') for txt in text.split(':')]
    return int(hours * 3600 + minutes * 60)


def encode_duration(seconds):
    hours = int(seconds / 3600)
    minutes = int((seconds - hours * 3600) / 60)
    return f'{hours:02d}:{minutes:02d}'


# Update sessions using local master file
def update_master(lines):

    header = re.compile(r'\s*(?P<year>\d{4})\sMULTI-AGENCY (?P<master>INTENSIVES)? ?SCHEDULE')
    now = datetime.utcnow()

    # Read master file
    sessions = {}
    for line in lines:
        if line.startswith('|'):
            data = dict(zip(COLUMNS, list(map(str.strip, line.strip(' \n|').split('|')))))
            start = datetime.strptime(f'{data["date"]} {data["time"]}', '%Y%m%d %H:%M')
            data['duration'] = decode_duration(data['duration'])
            if (start + timedelta(seconds=data['duration'])) > now:
                # Clean some unused data
                data = {key: value for key, value in data.items() if key not in UNUSED}
                sessions[data['code']] = dict(**data, **{'start': start, 'master': master})
        elif info := header.match(line):
            # Read multi agency line
            master = TYPES.get(info.group('master'), 'standard')

    # Post data to VCC
    try:
        vcc = VCC('CC')
        rsp = vcc.get_api().post('/sessions', data=sessions)
        if not rsp:
            raise VCCError(rsp.text)
        for ses_id, status in rsp.json().items():
            print(ses_id, status)
    except VCCError as exc:
        print(str(exc))


# Popup window to display error message with icon.
def error_message(text, critical=True):
    msg = QMessageBox()
    msg.setIcon(QMessageBox.Critical if critical else QMessageBox.Information)
    msg.setText(text)

    msg.setGeometry(
        QStyle.alignedRect(Qt.LeftToRight, Qt.AlignCenter, msg.size(), qApp.desktop().availableGeometry(),))
    msg.setWindowTitle('Fatal Error')
    msg.exec_()


# Create a read-only QLineEdit with size based on length of text
class TextBox(QLineEdit):
    def __init__(self, text, readonly=False, parent=None):
        super().__init__(text, parent)
        self.setSizePolicy(QSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred))
        self.parent = parent
        self.setReadOnly(readonly)

    def sizeHint(self):
        if not self.parent:
            return super().sizeHint()
        return self.parent.size()


# Class used to draw horizontal separator
class HSeparator(QFrame):
    def __init__(self):
        super().__init__()
        self.setMinimumWidth(1)
        self.setFixedHeight(20)
        self.setFrameShape(QFrame.HLine)
        self.setFrameShadow(QFrame.Sunken)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)


class SessionViewer(QMainWindow):

    def __init__(self, ses_id):

        super().__init__()

        try:
            self.vcc = VCC('CC')
            self.api = self.vcc.get_api()
        except VCCError as exc:
            error_message(str(exc), critical=True)
            sys.exit(0)

        self.session = self.get_session(ses_id)
        self.operations = self.make_combobox('/catalog/operations', self.session.operations)
        self.correlator = self.make_combobox('/catalog/correlator', self.session.correlator)
        self.analysis = self.make_combobox('/catalog/analysis', self.session.analysis)

        self.stations = self.get_stations()

        self.setWindowFlags(Qt.CustomizeWindowHint | Qt.WindowCloseButtonHint | Qt.WindowMinimizeButtonHint)
        self.setWindowTitle(f'Session {self.session.code}')

        widget = QWidget()
        self.grid = self.make_user_interface()
        widget.setLayout(self.grid)
        self.setCentralWidget(widget)

        self.resize(20, 20)
        self.move(300, 150)

    def closeEvent(self, event):
        QApplication.quit()

    def make_user_interface(self):

        grid = QGridLayout()

        grid.addWidget(QLabel("Code"), 0, 0)
        grid.addWidget(TextBox(self.session.code, readonly=True), 0, 1, 1, 2)
        grid.addWidget(QLabel("Type"), 0, 3)
        grid.addWidget(TextBox(self.session.type), 0, 4, 1, 2)
        is_intensive = QCheckBox("Intensive")
        is_intensive.setChecked(self.session.master == 'intensive')
        is_intensive.setLayoutDirection(Qt.RightToLeft)
        grid.addWidget(is_intensive, 0, 6, 1, 2)
        grid.addWidget(QLabel("Start"), 1, 0)
        grid.addWidget(TextBox(self.session.start.strftime('%Y-%m-%d %H:%M')), 1, 1, 1, 2)
        grid.addWidget(QLabel("Duration (HH:MM)"), 1, 3, 1, 2)
        grid.addWidget(TextBox(encode_duration(self.session.duration)), 1, 5)
        grid.addWidget(QLabel("Operations Center"), 2, 0, 1, 2)
        grid.addWidget(self.operations, 2, 2)
        grid.addWidget(QLabel("Correlator"), 2, 3)
        grid.addWidget(self.correlator, 2, 4)
        grid.addWidget(QLabel("Analysis"), 2, 5)
        grid.addWidget(self.analysis, 2, 6)
        grid.addWidget(HSeparator(), 3, 0, 1, 7)
        grid.addWidget(QLabel("Stations"), 4, 0)
        grid.addWidget(self.station_list(), 4, 1, 1, 6)
        grid.addWidget(HSeparator(), 5, 0, 1, 7)
        button = QPushButton('Quit')
        button.clicked.connect(self.close)
        grid.addWidget(button, 6, 0)
        button = QPushButton('Submit')
        button.clicked.connect(self.submit)
        grid.addWidget(button, 6, 6)

        return grid

    def submit(self):
        def get_text(row, col):
            return self.grid.itemAtPosition(row, col).widget().text()

        # Check if name is not empty
        self.session.type = get_text(0, 4).strip()
        if not self.session.type:
            error_message('Session type is empty')
            self.grid.itemAtPosition(0, 4).widget().setFocus()
            return
        # Get session type
        self.session.master = 'intensive' if self.grid.itemAtPosition(0, 6).widget().isChecked() else 'standard'
        # Check if start time is valid
        try:
            self.session.start = datetime.strptime(get_text(1, 1).strip(), '%Y-%m-%d %H:%M')
            if self.session.start < datetime.utcnow():
                error_message('Start time in the past')
                self.grid.itemAtPosition(1, 1).widget().setFocus()
                return
        except Exception as exc:
            error_message(f'Invalid start time [{str(exc)}]')
            self.grid.itemAtPosition(1, 1).widget().setFocus()
            return
        # Check if duration is at least 1 minute
        self.session.duration = decode_duration(get_text(1, 5))
        if self.session.duration < 60:
            error_message(f'Duration is less than 1 minute')
            self.grid.itemAtPosition(1, 4).widget().setFocus()
            return
        # Check if centers are selected
        for (name, line, label) in [('operations', 2, 0), ('correlator', 2, 3), ('analysis', 2, 5)]:
            item = getattr(self, name).currentText()
            if not item:
                error_message(f'Please select {get_text(line, label)}')
                self.operations.setFocus()
                return
            setattr(self.session, name, item)
        # Check station list
        network = get_text(4, 1).split(' -')
        self.session.included = [code.capitalize() for code in re.findall('..', network[0])]
        self.session.removed = [code.capitalize() for code in re.findall('..', network[1])] if len(network) > 1 else []
        if len(self.session.included) + len(self.session.removed) < 2:
            error_message('Not enough stations')
            self.grid.itemAtPosition(4, 1).widget().setFocus()
            return
        not_valid = [sta_id for sta_id in self.session.included+self.session.removed if sta_id not in self.stations]
        if not_valid:
            error_message(f'Not valid stations\n{"".join(not_valid)}')
            self.grid.itemAtPosition(4, 1).widget().setFocus()
            return
        # Update information on VCC
        try:
            data = {code: getattr(self.session, code) for code in COLUMNS if hasattr(self.session, code)}
            data = dict(**data, **{'start': self.session.start, 'master': self.session.master,
                                   'stations': get_text(4, 1)})
            rsp = self.api.put(f'/sessions/{self.session.code}', data=data)
            if not rsp:
                raise VCCError(f'VCC response {rsp.status_code}\n{rsp.text}')
            status = json_decoder(rsp.json())[self.session.code]
            error_message(f'{self.session.code.upper()} not updated\nSame information already on VCC'
                          if status == 'same' else f'{self.session.code.upper()} {status}', critical=False)
        except VCCError as exc:
            error_message(f'Problem updating {self.session.code}\n{str(exc)}')

    def get_session(self, ses_id):
        try:
            rsp = self.api.get(f'/sessions/{ses_id}')
            if rsp:
                return Session(json_decoder(rsp.json()))
        except VCCError:
            pass
        return Session({'code': ses_id})

    def get_stations(self):
        try:
            rsp = self.api.get(f'/stations')
            if rsp:
                return [sta['code'].capitalize() for sta in json_decoder(rsp.json())]
        except VCCError:
            pass
        return []

    def make_combobox(self, url, selection):
        cb = QComboBox()
        try:
            rsp = self.api.get(url)
            if rsp:
                [cb.addItem(item['code'].strip()) for item in json_decoder(rsp.json())]
        except VCCError:
            pass
        cb.setCurrentIndex(cb.findText(selection))
        return cb

    def station_list(self):
        lst = [code.capitalize() for code in self.session.included]
        if self.session.removed:
            lst.append(' -')
            lst.extend([code.capitalize() for code in self.session.removed])
        return TextBox(''.join(lst))


def view_session(ses_id):
    app = QApplication(sys.argv)
    viewer = SessionViewer(ses_id)
    viewer.show()
    sys.exit(app.exec_())


def main():
    import argparse
    from vcc import settings

    parser = argparse.ArgumentParser(description='Access VCC functionalities')
    parser.add_argument('-c', '--config', help='config file', required=False)
    parser.add_argument('param', help='master file or session code')

    args = settings.init(parser.parse_args())

    # Check that user has right privileges
    if not settings.check_privilege('CC'):
        print(f'Only Coordinating center can update master data on VCC')
        return

    path = Path(args.param)
    if path.exists():
        # Open file and get what type of file
        with open(path) as f:
            data = f.read()
        if 'MULTI-AGENCY' in data:
            update_master(data.splitlines())
        elif 'ns-codes.txt' in data:
            update_codes(data.splitlines())
        elif 'IVS Master File Format Definition' in data:
            update_network(data.splitlines())
        else:
            print(f'{path.name} is not a valid master, master-format or ns-codes file.')
    elif args.param == path.stem:  # This most be a session
        view_session(args.param)


if __name__ == '__main__':

    sys.exit(main())
