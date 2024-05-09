import sys
from threading import Thread, Event


class ProgressDots(Thread):
    def __init__(self, title, delay=1):
        super().__init__()
        self.stopped = Event()
        self.title, self.delay = title, min(max(delay, 1), 10)

    def run(self):
        sys.stdout.write(self.title)
        sys.stdout.flush()
        while not self.stopped.wait(self.delay):
            sys.stdout.write('.')
            sys.stdout.flush()

    def stop(self, msg=' done!'):
        self.stopped.set()
        print(msg, file=sys.stdout)

