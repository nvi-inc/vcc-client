import re
import os
import sys
import signal
import logging
import time
import json
import shutil
from pathlib import Path
from datetime import datetime
from psutil import Process, process_iter

from threading import Thread, Event

from vcc import VCCError, settings, set_logger
from vcc.server import VCC
from vcc.session import Session
from vcc.messaging import RMQclientException
from vcc.ns import notify
from vcc.ns.inbox import InboxTracker
from vcc.ns.ddout import DDoutScanner

logger = logging.getLogger('vccns')


class ContextFilter(logging.Filter):
    def filter(self, record):
        setattr(record, 'utc', datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3])
        return True


class VCChandler(logging.handlers.WatchedFileHandler):
    def __init__(self, filename):
        self.path = filename if isinstance(filename, Path) else Path(filename)
        self.make_log()
        super().__init__(filename)

    def make_log(self):
        if not self.path.exists():
            open(self.path, 'w').close()
        os.chmod(self.path, 0o664)
        shutil.chown(self.path, 'oper', 'rtx')

    def reopenIfNeeded(self):
        if not self.path.exists():
            self.flush()
            self.close()
            self.make_log()


# Class used to monitor VCC inbox and DDOUT continuously
class NSwatcher(Thread):

    extract_name = re.compile('.*filename=\"(?P<name>.*)\".*').match
    which = {'ddout': DDoutScanner, 'inbox': InboxTracker}

    def __init__(self, sta_id, logging_level=logging.INFO):

        super().__init__()

        signal.signal(signal.SIGTERM, self.terminate)

        handler = VCChandler(Path(settings.Folders.log, 'vcc', 'vcc-ns.log'))
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
            logger.debug(f'problem stopping {name} - {str(exc)}')

    def run(self):
        logger.info(f'vcc-ns started {self.native_id}')

        vcc, problem, show_msg = VCC('NS'), Event(), Event()
        problem.set()
        show_msg.set()
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
        logger.info('vcc-ns stopped')
        sys.exit(0)

    def terminate(self, sig, alarm):
        logger.debug(f'service stop requested {sig}')
        self.stopped.set()


def main():

    import argparse

    parser = argparse.ArgumentParser(description='Network Station', prog='vcc-ns', add_help=False)
    parser.add_argument('-c', '--config', help='config file', required=False)
    parser.add_argument('-D', '--debug', help='debug mode is on', action='store_true')

    args = settings.init(parser.parse_args())

    if not settings.check_privilege('NS'):
        print('Only Network Station can run this action')
        sys.exit(0)
    level = logging.DEBUG if args.debug else logging.INFO
    try:
        NSwatcher(settings.Signatures.NS[0], logging_level=level).start()
    except Exception as exc:
        print('problem', str(exc))
        logger.debug(f'end {str(exc)}')
        sys.exit(1)
    sys.exit(0)


if __name__ == '__main__':
    import sys

    sys.exit(main())
