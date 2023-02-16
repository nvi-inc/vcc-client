from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtWidgets import QMessageBox, QStyle
from PyQt5.QtCore import Qt

from vcc import settings


# Class to monit RabbitMQ and send messages using QThread
class Accepting(QThread):

    _fnc = pyqtSignal(bool)

    def __init__(self, text, parent, processing_fnc):
        super().__init__()

        self.text = text
        self.parent = parent

        self._fnc.connect(processing_fnc)

    def run(self):
        # Start monitoring
        title = f'{settings.Identity.name} received message'
        line_length = len(self.text)+50

        box = QMessageBox()
        box.setIcon(QMessageBox.Warning)
        box.setStandardButtons(QMessageBox.Yes|QMessageBox.No)

        box.button(QMessageBox.Yes).setText('Process')
        box.button(QMessageBox.No).setText('Skip')

        box.setText('{:}'.format(self.text.ljust(line_length)))
        box.setGeometry(QStyle.alignedRect(Qt.LeftToRight, Qt.AlignCenter, box.size(), self.parent.geometry()))
        box.setWindowTitle(title)

        accept = box.exec() == QMessageBox.Yes
        self._fnc.emit(accept)

