import os
from pathlib import Path
import re
import bz2
from datetime import datetime

from vcc import settings, message_box
from vcc.client import VCC, VCCError
from vcc.progress import ProgressDots


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
        progress = ProgressDots(f'Uploading {file.name} .', delay=5)
        try:
            if not vcc.api.get(f'/sessions/{ses_id}'):
                if not quiet:
                    print(f'{ses_id} not an IVS session')
                return
            params = {'send_msg': True}
            if not quiet:
                progress.start()
            if rsp := vcc.api.post('/log', files=[('file', (file.name, file, file.format))], params=params):
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
    if not quiet:
        waiting = ProgressDots('Contacting VCC .', delay=0.5)
        waiting.start()
    with VCC('NS') as vcc:
        upload(vcc, sta_id, ses_id)
        if not quiet:
            waiting.stop()


def download_log(vcc, filename):
    if not (found := re.match(r'(?P<ses_id>[a-z0-9]*)(?P<sta_id>[a-z0-9]{2})(?P<fmt>_full\.log\.bz2|\.log)', filename)):
        return False

    ses_id, sta_id, fmt = found['ses_id'], found['sta_id'], found['fmt']
    waiting = ProgressDots(f'Downloading {filename}.', delay=0.5)
    waiting.start()
    success = 'failed!'
    if not (rsp := vcc.api.get(f'/log/{ses_id}/{sta_id}')):
        message_box(f'Get file {filename}', f"{filename} failed!\n{rsp.json().get('error', rsp.text)}", 'warning')
    elif not (found := re.match(r'.*filename=\"(?P<name>.*)\".*', rsp.headers['content-disposition'])):
        message_box(f"Download problem", f"Problem downloading {filename}\n{rsp.headers['content-disposition']}",
                    'warning')
    else:
        dir_path = getattr(folders, 'log', '.') if (folders := getattr(settings, 'Folders')) else '.'
        decompress = fmt == '.log' and rsp.headers['content-type'] == 'application/stream'
        with open(Path(dir_path, filename), 'wb') as f:
            f.write(bz2.decompress(rsp.content) if decompress else rsp.content)
        success = 'done!'
    waiting.stop(msg=success)
    return True


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
