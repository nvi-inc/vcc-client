import re
import sys
import signal
import logging
import shutil
from pathlib import Path
from datetime import datetime

from threading import Thread, Event

from vcc import settings
from vcc.client import VCC
from vcc.ns.monit import InboxMonitor
from vcc.ns.ddout import DDoutScanner

logger = logging.getLogger('vcc')

"""
VCC NS client monitoring LOG file and NS inbox.
DDoutScanner monitors the current log and send specific information to VCC
InboxTracker monitors NS inbox on VCC and dispatches message to appropriate function
"""


class ContextFilter(logging.Filter):
    """
    Class to format UTC time in log
    """
    def filter(self, record):
        record.utc = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
        return True


class VCChandler(logging.handlers.WatchedFileHandler):
    """
    Class checking if log has been moved or deleted. Re-open it if needed
    """
    def __init__(self, filename):
        self.path = Path(filename)
        self.make_log()
        super().__init__(filename)

    def make_log(self):
        Path(self.path.parent).mkdir(exist_ok=True)
        if not self.path.exists():
            open(self.path, 'w').close()
        self.path.chmod(0o664)
        shutil.chown(self.path, 'oper', 'rtx')

    def reopenIfNeeded(self):
        if not self.path.exists():
            self.flush()
            self.close()
            self.make_log()


class VCCmon(Thread):
    """
    Class used to monitor VCC inbox and DDOUT continuously
    ddout and inbox are using separated threads
    """
    def __init__(self, sta_id, logging_level=logging.INFO):

        super().__init__()

        signal.signal(signal.SIGTERM, self.terminate)

        # define logger parameters
        handler = VCChandler(Path(settings.Folders.log, 'vcc', 'vccmon.log'))
        handler.setFormatter(logging.Formatter('%(utc)s [%(levelname)s] %(message)s'))
        logger.addFilter(ContextFilter())
        logger.setLevel(logging_level)
        logger.addHandler(handler)

        self.sta_id, self.stopped = sta_id, Event()

    def run(self):
        logger.info(f'vccmon started {self.native_id}')
        not_connected = False

        with VCC('NS') as vcc:
            threads = [DDoutScanner(self.sta_id, vcc), InboxMonitor(self.sta_id, vcc)]
            for prc in threads:
                prc.start()
            while not self.stopped.wait(5):
                if not vcc.is_available:
                    if not_connected:
                        logger.info('not connected to vcc')
                        not_connected = True
                elif not_connected:
                    logger.info('re-connected tp vcc')
                    not_connected = False

            # Terminated. Close all connections
            for prc in reversed(threads):
                prc.stop()
            for prc in reversed(threads):
                prc.join()
        logger.info('vccmon stopped')
        sys.exit(0)

    def terminate(self, sig, alarm):
        logger.debug(f'vccmon stop requested')
        self.stopped.set()


def main():

    import argparse

    parser = argparse.ArgumentParser(description='Network Station', prog='vccmon', add_help=False)
    parser.add_argument('-c', '--config', help='config file', required=False)
    parser.add_argument('-D', '--debug', help='debug mode is on', action='store_true')

    args = settings.init(parser.parse_args())

    if not (sta_id := settings.get_user_code('NS')):
        print('Only Network Station can run this action')
        sys.exit(1)
    level = logging.DEBUG if args.debug else logging.INFO
    try:
        VCCmon(sta_id, logging_level=level).start()
    except Exception as exc:
        logger.debug(f'end {str(exc)}')
        sys.exit(1)
    sys.exit(0)


if __name__ == '__main__':

    sys.exit(main())
