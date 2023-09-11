import os
from pathlib import Path
import re
import logging
import bz2
from datetime import datetime

from vcc import settings
from vcc.server import VCC, VCCError

logger = logging.getLogger('vccns')


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
def upload(vcc, sta_id, ses_id, full=False, reduce=False):
    path = Path(settings.Folders.log, f'{ses_id}{sta_id}.log'.lower())
    if path.exists():
        try:
            t0 = datetime.now()
            file = BZ2log(path) if full else SHORTlog(path, reduce)
            rsp = vcc.get_api().post('/data/log', files=[('file', (file.name, file, file.format))])
            logger.info(f'successfully uploaded {file.name} in {(datetime.now()-t0).total_seconds():.3f} seconds'
                        if rsp else f'failed uploading {file.name}! [{rsp.text}]')
        except VCCError:
            logger.warning(f'problem uploading {path.name}')
    else:
        logger.warning(f'{path.stem} not uploaded. It does not exist!')

