import os
from threading import Event
from datetime import datetime, date

from PyQt5.QtCore import QThread, Qt, pyqtSignal
from PyQt5.QtWidgets import qApp, QFrame, QWidget, QMessageBox, QVBoxLayout, QGridLayout, QGroupBox
from PyQt5.QtWidgets import QLabel, QSizePolicy, QStyle, QLineEdit

from vcc import settings, signature, VCCError
from vcc.session import Session
from vcc.server import VCC


# Class used to draw horizontal separator
class HSeparator(QFrame):
    def __init__(self, height=5):
        super().__init__()
        self.setMinimumWidth(1)
        self.setFixedHeight(height)
        self.setFrameShape(QFrame.HLine)
        self.setFrameShadow(QFrame.Sunken)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)


# Popup window to display error message with icon.
def ErrorMessage(app, text, info='', critical=False):
    if info:
        line_length = 0
        for line in info.splitlines():
            line_length = max(line_length, len(line))
        text = '{:}\n\n{}'.format(text.ljust(line_length), info)
    icon = QMessageBox.Critical if critical else QMessageBox.Warning
    msg = QMessageBox(icon, "app", text)
    msg.resize(100,50)

    msg.setGeometry(QStyle.alignedRect(Qt.LeftToRight, Qt.AlignCenter, msg.size(), qApp.desktop().availableGeometry()))
    msg.setWindowTitle(f'{app} {"Fatal Error" if critical else "error"}')
    msg.exec_()


# Create a read-only QLineEdit with size based on length of text
def make_text_box(text, readonly=True, fit=True):
    textbox = QLineEdit()
    textbox.setReadOnly(readonly)
    if fit:
        textbox.setAlignment(Qt.AlignCenter)
        fm = textbox.fontMetrics()
        w = fm.width(text) + 15
        textbox.setFixedWidth(w)
    textbox.setText(text)

    return textbox


class Timer(QThread):
    update = pyqtSignal(datetime)
    def __init__(self, on_update):
        super().__init__()
        self.stopped = Event()
        self.update.connect(on_update)

    def run(self):
        waiting_time = 1.0 - datetime.utcnow().timestamp() % 1
        while not self.stopped.wait(waiting_time):
            utc = datetime.utcnow()
            self.update.emit(utc)
            dt = utc.timestamp() % 1
            waiting_time = 1.0 if dt < 0.001 else 1.0 - dt

    def stop(self):
        self.stopped.set()


# Class to display list of incoming sessions
class SessionsViewer(QWidget):
    def __init__( self, parent, sessions):
        super().__init__(parent, Qt.Window)       # <<<=== Qt.Window

        self.schedules = {}
        self.sessions = sessions

        self.setWindowTitle(f"{parent.sta_id} upcoming sessions")
        self.resize(300, 100)

        layout = QVBoxLayout()
        layout.addWidget(self.show_sessions(sessions))
        self.setLayout(layout)

        self.check_schedules()

    def check_schedules(self):
        self.gets = []
        for ses in self.sessions:
            prc = Get(f'schedules/{ses["code"]}/exists')
            self.gets.append(prc)
            prc.on_finish(None, self.update_schedules)
            prc.start()

    def show_sessions(self, sessions):
        groupbox = QGroupBox()

        box = QGridLayout()
        box.addWidget(QLabel('Session'), 0, 0)
        box.addWidget(QLabel('Day'), 0, 2, 1, 2)
        box.addWidget(QLabel('Start'), 0, 4)
        box.addWidget(QLabel('COR'), 0, 7)
        box.addWidget(QLabel('SKED'), 0, 9)
        box.addWidget(QLabel('Status'), 0, 11, 1, 2)

        box.addWidget(HSeparator(5), 1, 0, 1, 14)

        for row, info in enumerate(sessions, 2):
            ses = Session(info)
            code = ses.code.lower()
            self.schedules[code] = {'version': QLabel('?'), 'status': QLabel('N/A')}
            box.addWidget(QLabel(code.upper()), row, 0, 1, 2)
            box.addWidget(QLabel(ses.start.strftime('%Y-%m-%d')), row, 3, 1, 2)
            box.addWidget(QLabel(ses.start.strftime('%H:%M')), row, 5)
            box.addWidget(QLabel(ses.correlator.upper()), row, 7)
            box.addWidget(self.schedules[code]['version'], row, 9)
            box.addWidget(self.schedules[code]['status'], row, 11, 1, 2)

        groupbox.setLayout(box)

        return groupbox

    def update_schedules(self, action, response, error):
        if response and response.status_code == HttpCodes.ok:
            for code, data in response.json().items():
                code = code.lower()
                if code not in self.schedules:
                    continue
                self.schedules[code]['version'].setText(data['version'])
                if data['file']:
                    # Check if file has been downloaded
                    path = os.path.join(settings.Folders.schedules, data['file'])
                    if os.path.exists(path):
                        with open(path) as sched:
                            for line in sched:
                                if line.startswith('SESSION:'):
                                    self.schedules[code]['status'].setText(f'{line.split("|")[-1].strip()} downloaded')


# Use different thread to get data from web service
class Get(QThread):
    finished = pyqtSignal(str, object, str)

    def __init__(self, vcc, path, params=None):
        super().__init__()

        self.vcc, self.path, self.params = vcc, path, params
        self.command = None

    def on_finish(self, command, function):
        self.command = command
        self.finished.connect(function)

    def run(self):
        try:
            response, error = self.vcc.get_api().get(self.path, self.params), None
        except VCCError as exc:
            response, error = None, str(exc)
        self.finished.emit(self.command, response, error)


# Use different thread to get data from web service
class Post(QThread):
    finished = pyqtSignal(object, str)

    def __init__(self, vcc, path, data=None, files=None):
        super().__init__()

        self.vcc, self.path, self.data, self.files = vcc, path, data, files

    def on_finish(self, function):
        self.finished.connect(function)

    def run(self):
        try:
            response, error = self.vcc.get_api().post(self.path, files=self.files, data=self.data), None
        except VCCError as exc:
            response, error = None, str(exc)
        self.finished.emit(response, error)

    @staticmethod
    def encoder(obj):
        if isinstance(obj, (date, datetime)):
            return obj.isoformat()


# Use different thread to get data from web service
class MultiGet(QThread):
    processed = pyqtSignal(str, object, str)
    finished = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, vcc):
        super().__init__()
        self.vcc = vcc
        self.actions = None

    def do_nothing(self):
        pass

    def set_requests(self, actions, on_reply, on_error, on_finished=None):
        self.actions = actions
        self.processed.connect(on_reply)
        self.error.connect(on_error)
        self.finished.connect(on_finished if on_finished else self.do_nothing)

    def run(self):
        try:
            for (sta_id, path, params) in self.actions:
                response = self.vcc.get_api().get(path, params)
                self.processed.emit(sta_id, response, '')
            self.finished.emit()
        except VCCError as exc:
            self.error.emit(str(exc))

