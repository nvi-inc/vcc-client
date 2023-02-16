from datetime import datetime

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QWidget, QMessageBox, QStyle, QLabel, QVBoxLayout, QGroupBox, QGridLayout

from vcc.processes import HSeparator


# Popup window to display station message.
def StationMessage(parent, headers, data, urgent=True):
    sta_id = data.get('station', headers.get('station', '__')).capitalize()
    title = f'{parent.session.code.upper()} {"Urgent message" if urgent else "Message"} from {sta_id}'
    lines = data['msg'].splitlines()
    line_length = max(len(title)+50, len(max(lines, key=len)))

    msg = QMessageBox(parent)
    msg.setIcon(QMessageBox.Critical if urgent else QMessageBox.Warning)

    msg.setText('{:}\n\n{}'.format(lines[0].ljust(line_length), '\n'.join(lines[1:])))
    msg.setGeometry(QStyle.alignedRect(Qt.LeftToRight, Qt.AlignCenter, msg.size(), parent.geometry()))
    msg.setWindowTitle(title)

    msg.exec_()


# Window to display SEFD values
class SEFDs(QWidget):
    def __init__( self, parent, sefd):
        super().__init__(parent, Qt.Window)       # <<<=== Qt.Window

        self.setWindowTitle(f'SEFD {sefd["sta_id"].capitalize()}')
        self.resize(300, 100)

        layout = QVBoxLayout()
        layout.addWidget(self.show_general_info(sefd))
        layout.addWidget(self.show_detectors(sefd))
        self.setLayout(layout)

    def show_general_info(self, sefd):

        observed = datetime.fromisoformat(sefd['observed']).strftime('%Y-%m-%d %H:%M')
        groupbox = QGroupBox()
        box = QGridLayout()
        box.addWidget(QLabel(f'Source: {sefd["source"]}'), 0, 0, 1, 2)
        box.addWidget(QLabel(f'Az: {sefd["azimuth"]}'), 0, 3)
        box.addWidget(QLabel(f'El: {sefd["elevation"]}'), 0, 4)
        box.addWidget(QLabel(observed), 0, 5, 1, 2)
        groupbox.setLayout(box)
        return groupbox

    def show_detectors(self, sefd):
        groupbox = QGroupBox()

        box = QGridLayout()
        for col, label in enumerate(['De', 'I', 'P', 'Freq', 'TSYS', 'SEFD']):
            box.addWidget(QLabel(label), 0, col)
        # Add separator
        box.addWidget(HSeparator(5), 1, 0, 1, 6)

        names = ['device', 'input', 'polarization', 'frequency', 'tsys', 'sefd']
        for row, info in enumerate(sefd['detectors'], 2):
            for col, name in enumerate(names):
                box.addWidget(QLabel(str(info[name])), row, col)
        groupbox.setLayout(box)
        return groupbox

