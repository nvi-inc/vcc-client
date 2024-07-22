import re
import sys
import signal
import logging
import shutil
from pathlib import Path
from datetime import datetime

from threading import Thread, Event

from vcc import VCCError, settings
from vcc.client import VCC, RMQclientException
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


class NSwatcher(Thread):
    """
    Class used to monitor VCC inbox and DDOUT continuously
    ddout and inbox are using separated threads
    """
    extract_name = re.compile('.*filename=\"(?P<name>.*)\".*').match
    which = {'ddout': DDoutScanner, 'inbox': InboxMonitor}

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
        self.threads = {name: None for name in self.which.keys()}

    def stop_thread(self, name):
        try:
            logger.debug(f'{name} {type(self.threads[name])}')
            if self.threads[name]:
                logger.debug(f'{name} is {"alive" if self.threads[name].is_alive() else "dead"}')
                self.threads[name].stop()
        except (NameError, AttributeError, RMQclientException) as exc:
            logger.warning(f'problem stopping {name} - {str(exc)}')

    def run(self):
        logger.info(f'vccmon started {self.native_id}')

        vcc, problem, show_msg = VCC('NS'), Event(), Event()
        problem.set()
        show_msg.set()
        logger.info(sys.argv[0])
        while not self.stopped.wait(1.0):
            try:
                if problem.is_set():
                    if not vcc.is_available:
                        vcc.connect()
                        if vcc.is_available:
                            logger.info('connected to vcc server')
                    problem.clear()
                    logger.debug(f'start {" ".join(list(self.threads.keys()))}')
                    for name in self.threads.keys():
                        self.stop_thread(name)
                        self.threads[name] = self.which[name](self.sta_id, vcc, problem)
                        self.threads[name].start()
                    show_msg.clear()
                elif not self.stopped.is_set():
                    for name in self.threads.keys():
                        if not self.threads[name].is_alive():
                            logger.debug(f'test alive: {name} is dead')
                            self.threads[name] = self.which[name](self.sta_id, vcc, problem)
                            self.threads[name].start()
                continue
            except VCCError as exc:
                err_msg = f'communication problem - {str(exc)}'
            except Exception as exc:
                err_msg = f'unknown problem - {str(exc)}'
            if show_msg.is_set():
                logger.warning(err_msg)
            show_msg.set()
            Event().wait(10)

        logger.debug(f'stop threads {list(reversed(self.threads.keys()))}')

        # Terminated. Close all connections
        for name in reversed(self.threads.keys()):
            self.stop_thread(name)
        logger.debug('wait for threads')
        vcc.close()
        for name in reversed(self.threads.keys()):
            self.threads[name].join()
        logger.info('vccmon stopped')
        sys.exit(0)

    def terminate(self, sig, alarm):
        logger.debug(f'service stop requested {sig}')
        self.stopped.set()


def inbox_in_use():
    with VCC('NS') as vcc:
        try:
            vcc.get_rmq_client().alive()
            return False
        except (VCCError, RMQclientException):
            return True


def main():

    import argparse

    parser = argparse.ArgumentParser(description='Network Station', prog='vccmon', add_help=False)
    parser.add_argument('-c', '--config', help='config file', required=False)
    parser.add_argument('-D', '--debug', help='debug mode is on', action='store_true')

    args = settings.init(parser.parse_args())

    if not (sta_id := settings.get_user_code('NS')):
        print('Only Network Station can run this action')
        sys.exit(1)
    if inbox_in_use():
        print(f'The inbox for {sta_id} is already monitored!')
        sys.exit(1)
    level = logging.DEBUG if args.debug else logging.INFO
    try:
        NSwatcher(sta_id, logging_level=level).start()
    except Exception as exc:
        logger.debug(f'end {str(exc)}')
        sys.exit(1)
    sys.exit(0)


if __name__ == '__main__':

    sys.exit(main())
