import os
import re
import bz2

from functools import cache, lru_cache
from datetime import datetime
from pathlib import Path

import time
import logging



from vcc import settings, message_box
from vcc.client import VCC, VCCError
from vcc.utils import ProgressDots
from vcc.session import Session


logger = logging.getLogger('vcc')


# Send ONOFF records to VCC
def post_onoff(vcc, records):
    if records and vcc:
        error = None
        for _ in range(3):
            try:
                if rsp := vcc.post('/data/onoff', data=records):
                    logger.info(f'uploaded {len(records)} onoff records for {records[0]["source"]}')
                    return
                error = rsp.text
            except VCCError as exc:
                error = str(exc)
            time.sleep(0.1)
        raise VCCError(error)


def onoff(filepath):
    is_header = re.compile(r'^(?P<time>^\d{4}\.\d{3}\.\d{2}:\d{2}:\d{2}\.\d{2})(?P<key>#onoff#    source)'
                           r'(?P<data>.*)$').match
    is_onoff = re.compile(r'^(?P<time>^\d{4}\.\d{3}\.\d{2}:\d{2}:\d{2}\.\d{2})(?P<key>#onoff#VAL)'
                          r'(?P<data>.*)$').match
    if not (path := Path(filepath)).exists() and not (path := Path(settings.Folders.log, filepath)):
        logger.info(f'{filepath} doest not exist!')
        return

    logger.info(f'extracting onoff records from {path.name}')

    header, records = [], []
    with open(path, 'r', encoding="utf8", errors="ignore") as f, VCC('NS') as vcc:
        for line in f:
            if found := is_onoff(line):
                timestamp = fs2time(found['time'])
                record = {name: value for name, value in zip(header, found['data'].split())}
                records.append(dict(**{'time': timestamp}, **record))
            elif found := is_header(line):
                header = ['source'] + found['data'].split()
                try:
                    post_onoff(vcc, records)  # Send existing onoff records to VCC
                except VCCError as exc:
                    logger.warning(f"fail uploading onoff {str(exc)}")
                records = []

        try:
            post_onoff(vcc, records)
        except VCCError as exc:
            logger.warning(f"fail uploading onoff {str(exc)}")



def time2fs(timestamp: float) -> str:
    return datetime.utcfromtimestamp(timestamp).strftime('%Y.%j.%H:%M:%S.%f')[:20]


@cache
def day1(year: int) -> float:
    return datetime(year, 1, 1).timestamp()


@lru_cache(maxsize=100)
def ydh2sec(text):
    year, day, hour = [int(s) for s in text.split('.')]
    return day1(year) + (day - 1) * 86400 + hour * 3600


def fs2time(text):
    ydh, _, ms = text.partition(':')
    minutes, seconds = [float(s) for s in ms.split(':')]
    return ydh2sec(ydh) + minutes * 60 + seconds


class BZ2log:
    def __init__(self, path):
        self.path = path

    @property
    def name(self):
        return self.path.stem + '_full.log.bz2'

    @property
    def format(self):
        return 'application/stream'

    def read(self):
        return bz2.compress(open(self.path, 'rb').read())


class SHORTlog:
    def __init__(self, path, reduce=False):
        self.path = path
        self.read = self.reduce_it if reduce else self.no_changes

    @property
    def name(self):
        return os.path.basename(self.path)

    @property
    def format(self):
        return 'text/plain'

    def reduce_it(self):
        is_multi_cast = re.compile('^[:.0-9]*#(rdtc|dbtcn)').match
        with open(self.path, 'r', encoding="utf8", errors="ignore") as f:
            return ''.join([line for line in f if not is_multi_cast(line)]).encode('utf-8')

    def no_changes(self):
        return open(self.path, 'rb').read()


# Upload log file
def upload(vcc, sta_id, ses_id, full=True, reduce=True, quiet=False):

    print(f'sending log for {ses_id} {sta_id}')

    if (path := Path(settings.Folders.log, f'{ses_id}{sta_id}.log'.lower())).exists():
        file = BZ2log(path) if full else SHORTlog(path, reduce)
        progress = ProgressDots(f'Uploading {file.name} ', delay=5)
        try:
            if not vcc.get(f'/sessions/{ses_id}'):
                if not quiet:
                    print(f'{ses_id} not an IVS session')
                return
            params = {'send_msg': True}
            if not quiet:
                progress.start()
            if rsp := vcc.post('/logs', files=[('file', (file.name, file, file.format))], params=params):
                status = rsp.json()
                msg = f" done in {status['time']:.3f} seconds!"
            else:
                msg = f' failed! [{rsp.text}]'
        except VCCError as exc:
            msg = f' problem! [{str(exc)}'
        if not quiet:
            progress.stop(msg)
    elif not quiet:
        print(f'{path.name} does not exist!')


def upload_log(ses_id, quiet=False):
    if not settings.check_privilege('NS'):
        message_box('NO privilege for this action', 'Only Network Station can upload log', 'warning')
        return

    sta_id = settings.Signatures.NS[0].lower()
    waiting = None
    if not quiet:
        waiting = ProgressDots('Contacting VCC .', delay=0.5)
        waiting.start()
    for _ in range(3):
        try:
            with VCC('NS') as vcc:
                upload(vcc, sta_id, ses_id)
                if waiting:
                    waiting.stop()
            break
        except VCCError:
            pass





def main():

    import argparse

    parser = argparse.ArgumentParser(description='Upload log file', prog='fslog', add_help=False)
    parser.add_argument('-c', '--config', help='config file', required=False)
    parser.add_argument('-q', '--quiet', help='quiet mode', action='store_true', required=False)
    parser.add_argument('session', help='Session code')

    args = settings.init(parser.parse_args())

    if not (sta_id := settings.get_user_code('NS')):
        print('Only Network Station can run this action')
        sys.exit(1)

    if not args.quiet:
        waiting = ProgressDots('Contacting VCC .', delay=0.5)
        waiting.start()
    with VCC('NS') as vcc:
        if not args.quiet:
            waiting.stop()
        upload(vcc, sta_id, args.session, quiet=args.quiet)


if __name__ == '__main__':
    import sys

    sys.exit(main())
