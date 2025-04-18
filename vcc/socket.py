import socket
from threading import Event


BUFFER_SIZE = 4096
EOT = b"\r\n"


class Server:

    def __init__(self, host, port):
        self.host, self.port = host, port
        self.buffer, self.records, self.stopped = b"", [], Event()

        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.socket.bind((self.host, self.port))
        self.socket.listen(1)

    def _get_data(self, conn):
        try:
            while EOT not in self.buffer:
                if not (received := conn.recv(BUFFER_SIZE)):
                    return False
                self.buffer += received
            while EOT in self.buffer:
                record, _, self.buffer = self.buffer.partition(EOT)
                self.records.append(record)
            return True
        except ConnectionResetError as err:
            return False

    def monit(self):
        try:
            while not self.stopped.is_set():
                conn, addr = self.socket.accept()
                with conn:
                    if self._get_data(conn) and self.records:
                        for record in self.records:
                            self.process(record)
                        self.records = []
        except (KeyboardInterrupt, OSError):
            print('socket ends')

    def stop(self):
        self.stopped.set()
        self.socket.shutdown(socket.SHUT_RDWR)
        self.socket.close()

    def process(self, data):
        self.logger(f"Data not process {str(data)}")


class Client:
    def __init__(self, host: str, port: int) -> None:
        self.buffer = b""
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.connect((host, port))

    def send(self, data: bytes or str):
        if isinstance(data, str):
            data = data.encode("utf-8")
        self.socket.sendall(data + EOT)

