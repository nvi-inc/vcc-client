import re
import os
import sys
import signal
import logging
import time
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
from vcc.ns.drudg import drudg_it
from vcc.ns.onoff import onoff
from vcc.ns.fslog import upload

logger = logging.getLogger('vcc')


# Class used to monitor VCC inbox and DDOUT continuously
class NSwatcher(Thread):

    extract_name = re.compile('.*filename=\"(?P<name>.*)\".*').match

    def __init__(self, sta_id):
        super().__init__()

        signal.signal(signal.SIGINT, self.terminate)
        signal.signal(signal.SIGHUP, self.terminate)
        signal.signal(signal.SIGTERM, self.terminate)

        self.sta_id, self.stopped, self.threads = sta_id, Event(), {'inbox': None, 'ddout': None}

    def stop_rmq_thread(self, name):
        logger.debug(f'call stop for {name}')
        try:
            self.threads[name].stop()
        except (NameError, AttributeError, RMQclientException) as exc:
            logger.debug(f'thread {name} error {str(exc)}')
        logger.debug(f'thread {name} stopped')

    def run(self):
        logger.info('start vccns')

        vcc = VCC('NS')
        while not self.stopped.wait(1.0):
            ddout, inbox = self.threads.values()
            try:
                if not ddout or not ddout.is_alive():
                    logger.warning(f'ddout needs restart {ddout.is_alive() if ddout else "None"}')
                    Event().wait(5 if ddout else 0)
                    self.threads['ddout'] = ddout = DDoutScanner(self.sta_id, vcc)
                    ddout.start()
                if not inbox or not inbox.is_alive():
                    logger.warning(f'inbox needs restart {inbox.is_alive() if inbox else "None"}')
                    Event().wait(5 if inbox else 0)
                    self.threads['inbox'] = inbox = InboxTracker(self.sta_id, vcc)
                    inbox.start()
            except (VCCError, RMQclientException, Exception) as exc:
                logger.warning(str(exc))
                if self.stopped.is_set():
                    break
                Event().wait(1)  # Wait 1 second to reset communication
                #if not vcc.is_available:
                #    vcc = VCC('NS')

        # Terminated. Close all connections
        self.stop_rmq_thread('ddout')
        self.stop_rmq_thread('inbox')
        if vcc:
            vcc.close()
        logger.info('end vccns')

    def terminate(self, sig, alarm):
        logger.info('terminating vccns')
        self.stopped.set()


def get_vccns_proc():
    my_pid = os.getpid()
    for prc in process_iter(attrs=['pid', 'name', 'cmdline']):
        if prc.info['pid'] != my_pid and any(['vcc-ns' in cmd for cmd in prc.info['cmdline'] or []]):
            return prc
    return None


# Provide status of monitoring app
def status():
    prc = get_vccns_proc()
    if prc:
        # Look at connections for this pid
        dt = datetime.now() - datetime.fromtimestamp(Process(prc.info['pid']).create_time())
        hours = int(dt.seconds/3600)
        print('vcc-ns has been running for ', end='')
        if dt.days:
            print(f'{dt.days} day{"s" if dt.days != 1 else ""} '
                  f'{hours} hour{"s" if hours != 1 else ""} and {int((dt.seconds-hours*3600)/60)} minutes')
        elif hours:
            print(f'{hours} hour{"s" if hours != 1 else ""} and {int((dt.seconds-hours*3600)/60)} minutes')
        else:
            minutes = int(dt.seconds/60)
            print(f'{minutes} minute{"s" if minutes != 1 else ""} and {int(dt.seconds-minutes*60)} seconds')
    else:
        print('vcc-ns is not running')


# Stop VCCNS monitoring application
def stop(verbose=True):
    prc = get_vccns_proc()
    if prc:
        try:
            Process(prc.info['pid']).send_signal(signal.SIGTERM)
            while True:
                time.sleep(1)
                prc = get_vccns_proc()
                if not prc:
                    if verbose:
                        print(f'Successfully killed \"vcc-ns\" process')
                    return
                Process(prc.info['pid']).send_signal(signal.SIGKILL)
        except Exception as err:
            if verbose:
                print(f'Failed trying to kill \"vcc-ns\" process. [{str(err)}]')
            return False
    elif verbose:
        print('vcc-ns is not running')
    return True


# Start VCCNS monitoring app
def start():
    print('vccns is already running!') if get_vccns_proc() else NSwatcher(settings.Signatures.NS[0]).start()


# Restart vccs watcher
def restart():
    if stop(verbose=False):
        start()


# List upcoming sessions for this station
def upcoming(days, print_it=False):
    sta_id = settings.Signatures.NS[0]
    with VCC('NS') as vcc:
        rsp = vcc.get_api().get(f'/sessions/next/{sta_id}', params={'days': days})
        logger.debug(f'next {sta_id} {rsp.status_code}')
        now = datetime.utcnow()
        title, lines = f'List of upcoming sessions for {sta_id}', []
        if rsp:
            index = 1
            for data in rsp.json():
                session = Session(data)
                if session.start > now:
                    lines.append(f'{index:2d} {session}')
                    index += 1
            message = '\n'.join(lines)
            print(f'\n{title}\n{"=" * len(title)}\n{message}\n') if print_it else notify(title, message)
        else:
            (print if print_it else notify)('VCC problem', rsp.text)


def main():

    import argparse

    parser = argparse.ArgumentParser(description='Network Station', prog='vcc-ns', add_help=False)
    parser.add_argument('-c', '--config', help='config file', required=False)
    parser.add_argument('-D', '--debug', help='debug mode is on', action='store_true')
    parser.add_argument('action',
                        choices=['start', 'stop', 'status', 'restart', 'fetch', 'next', 'drudg', 'onoff', 'log'],
                        type=str.lower)
    action = parser.parse_known_args()[0].action
    if action in ['stop', 'status']:
        getattr(sys.modules[__name__], action)()
        return

    # Create new arguments for specified action
    options = {'drudg': [{'args': ['-v', '--vex'], 'kwargs': {'action': 'store_true', 'help': 'use vex file'}},
                         {'args': ['session'], 'kwargs': {'help': 'session code', 'type': str.lower}}],
               'onoff': [{'args': ['log'], 'kwargs': {'help': 'log file'}}],
               'next': [{'args': ['-p', '--print'], 'kwargs': {'action': 'store_true'}},
                        {'args': ['-d', '--days'], 'kwargs': {'help': 'days ahead', 'type': int, 'default': 14}}],
               'log': [{'args': ['log'], 'kwargs': {'help': 'log file'}}],
               }
    exclusive = {'log': [{'args': ['-f', '--full'], 'kwargs': {'action': 'store_true'}},
                         {'args': ['-r', '--reduce'], 'kwargs': {'action': 'store_true'}}]
                 }

    parser = argparse.ArgumentParser(description='Network Station', prog=f'vcc-ns {action}')
    parser.add_argument('action', choices=[action], help=argparse.SUPPRESS, type=str.lower)
    parser.add_argument('-c', '--config', help='config file', required=False)
    parser.add_argument('-D', '--debug', help='debug mode is on', action='store_true')
    [parser.add_argument(*option['args'], **option['kwargs']) for option in options.get(action, [])]
    if exclusive.get(action, None):
        optional = parser.add_mutually_exclusive_group(required=False)
        [optional.add_argument(*option['args'], **option['kwargs']) for option in exclusive.get(action, None)]

    args = settings.init(parser.parse_args())

    if not settings.check_privilege('NS'):
        print('Only Network Station can run this action')
        sys.exit(0)
    set_logger(console=args.debug)

    if args.action in ['start', 'restart']:
        set_logger('/usr2/log/vcc.log', prefix='vcc-', console=args.debug)
        getattr(sys.modules[__name__], args.action)()
    elif args.action == 'drudg':
        drudg_it(args.drudg, args.vex)
    elif args.action == 'onoff':
        onoff(args.log)
    elif args.action == 'log':
        upload(args.log, args.full, args.reduce)
    elif args.action == 'next':
        upcoming(args.days, args.print)


if __name__ == '__main__':
    import sys

    sys.exit(main())
