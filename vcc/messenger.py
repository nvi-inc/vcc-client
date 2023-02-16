from PyQt5.QtCore import QThread, pyqtSignal
from vcc.messaging import RMQclientException

# Class to monit RabbitMQ and send messages using QThread
class Messenger(QThread):

    _msg = pyqtSignal(dict, str)
    _ack = pyqtSignal()
    _close = pyqtSignal()
    _send = pyqtSignal(str, str, str, object)
    _ping = pyqtSignal(str)
    _pong = pyqtSignal(str, str, object)

    def __init__(self, vcc, processing_fnc, ses_id=None):
        super().__init__()

        self.client = vcc.get_rmq_client(ses_id=ses_id, is_multi_thread=True)

        self._ack.connect(self.client.acknowledge_msg)
        self._close.connect(self.client.abord)
        self._send.connect(self.client.send)
        self._ping.connect(self.client.ping)
        self._pong.connect(self.client.pong)

        self._msg.connect(processing_fnc)

    def run(self):
        print('START RMQclient')
        # Start monitoring
        try:
            self.client.monit(self.process_msg)
        except RMQclientException:
            return

    def stop(self):
        try:
            self._close.emit()
        except RMQclientException:
            pass

    def process_msg(self, headers, body):
        self._msg.emit(headers, body.decode('utf-8'))

    def acknowledge_msg(self):
        self._ack.emit()

    def send(self, sender, code, target, data):
        self._send.emit(sender, code, target, data)

    def ping(self, target, to_queue=False, need_reply=False):
        self._ping.emit(target, to_queue, need_reply)

    def pong(self, sender, target, status):
        self._pong.emit(sender, target, status)
