import sys
from datetime import datetime, timedelta
from functools import partial
from subprocess import Popen, PIPE

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QMainWindow, QApplication, QWidget, QLayout
from PyQt5.QtWidgets import QLabel, QVBoxLayout, QHBoxLayout, QGroupBox, QGridLayout, QPushButton

from vcc import settings, VCCError
from vcc.session import Session
from vcc.server import VCC
from vcc.processes import Timer


# Class for showing all sessions
class SessionPicker(QMainWindow):

    def __init__(self, session_type):

        self.full_name = 'Session Picker'

        self.app = QApplication(sys.argv)

        today = datetime.utcnow().date()
        begin, end = today - timedelta(days=2), today + timedelta(days=7)

        super().__init__()

        self.setWindowFlags(Qt.WindowCloseButtonHint | Qt.WindowMinimizeButtonHint)
        self.setWindowTitle(self.full_name)
        self.resize(900, 100)

        # Make session box
        widget = QWidget()
        self.Vlayout = QVBoxLayout()
        self.Vlayout.addLayout(self.make_session_list(begin, end, session_type))

        self.Vlayout.addLayout(self.make_footer_box())
        widget.setLayout(self.Vlayout)
        self.setCentralWidget(widget)

        self.init_pos()

        self.show()

        # Start timer to update information
        self.timer = Timer(self.on_timer)
        self.timer.start()

    def init_pos(self):
        if hasattr(settings, 'Positions'):
            self.move(settings.Positions.x, settings.Positions.y)

    def make_footer_box(self):

        hbox = QHBoxLayout()
        cancelButton = QPushButton("Cancel")
        cancelButton.clicked.connect(self.close)
        hbox.addWidget(cancelButton)
        hbox.addStretch(1)
        self.utc_display = QLabel('YY')
        hbox.addWidget(self.utc_display)
        hbox.setContentsMargins(10, 5, 15, 5)
        hbox.setSizeConstraint(QLayout.SetNoConstraint)
        return hbox

    @staticmethod
    def get_sessions(begin, end, master):
        # Get session information from VLBI web service (vws)
        try:
            vcc = VCC('DB')
            api = vcc.get_api()
            rsp = api.get('/sessions', params={'begin': begin, 'end': end, 'master': master})

            print(rsp.text)
            if rsp:
                for ses_id in rsp.json():
                    rsp = api.get(f'/sessions/{ses_id}')
                    if rsp:
                        session = Session(rsp.json())
                        rsp = api.get(f'/schedules/{ses_id}', params={'select': 'summary'})
                        if rsp:
                            session.update_schedule(rsp.json())
                        yield session
        except VCCError:
            pass

    def app_button(self, title, code, app):
        button = QPushButton(title)
        button.clicked.connect(partial(self.launch_app, ses_id=code, app=app))
        return button

    def make_session_list(self, begin, end, master):

        box = QGridLayout()
        box.addWidget(QLabel('Session'), 0, 0, 1, 2)
        box.addWidget(QLabel('Day'), 0, 3, 1, 2)
        box.addWidget(QLabel('Start'), 0, 5)
        box.addWidget(QLabel('Network'), 0, 7, 1, 2)
        box.addWidget(QLabel('OC'), 0, 13)
        box.addWidget(QLabel('COR'), 0, 14)
        box.addWidget(QLabel('AC'), 0, 15)
        box.addWidget(QLabel('SCHED'), 0, 16)

        for row, ses in enumerate(self.get_sessions(begin, end, master), 1):
            print(row, ses)
            box.addWidget(QLabel(ses.code.upper()), row, 0, 1, 2)
            box.addWidget(QLabel(ses.start.strftime('%Y-%m-%d')), row, 3, 1, 2)
            box.addWidget(QLabel(ses.start.strftime('%H:%M')), row, 5)
            box.addWidget(QLabel(', '.join(ses.network)), row, 7, 1, 6)
            box.addWidget(QLabel(ses.operations.upper()), row, 13)
            box.addWidget(QLabel(ses.correlator.upper()), row, 14)
            box.addWidget(QLabel(ses.analysis.upper()), row, 15)
            box.addWidget(QLabel(ses.sched_version), row, 16)

            box.addWidget(self.app_button('Make SKD', ses.code, 'settings.Scripts.scheduler'), row, 17)
            box.addWidget(self.app_button('Monit', ses.code, 'settings.Scripts.dashboard'), row, 18)

        groupbox = QGroupBox()
        groupbox.setLayout(box)
        grid = QGridLayout()
        grid.addWidget(groupbox)
        return grid

    def launch_app(self, ses_id, app):

        command = f'vcc -c {settings.args.config} --dashboard {ses_id}'
        print(command)
        prc = Popen(command, shell=True, stdin=PIPE, stdout=PIPE, stderr=PIPE)
        stdout, stderr = prc.communicate()
        print(stdout.decode('utf-8'))
        print(stderr.decode('utf-8'))

    def on_timer(self):
        self.utc_display.setText(datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC'))

    def exec(self):
        sys.exit(self.app.exec_())

    def closeEvent(self,event):
        self.timer.stop()





