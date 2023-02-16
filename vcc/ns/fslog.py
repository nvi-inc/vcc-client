import os
import re
import logging
import bz2
from datetime import datetime

from vcc import settings, update_object, set_logger, VCCError
from vcc.server import VCC

logger = logging.getLogger('vcc')


class BZ2log:
    def __init__(self, path):
        self.path = path

    @property
    def name(self):
        return os.path.splitext(os.path.basename(self.path))[0] + '_full.log.bz2'

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
def upload(sta_id, ses_id, full=False, reduce=False):
    name = f'{ses_id}{sta_id}.log'.lower()
    path = os.path.join(settings.Folders.log, name)
    if os.path.exists(path):
        with VCC('NS') as vcc:
            t0 = datetime.now()
            file = BZ2log(path) if full else SHORTlog(path, reduce)
            rsp = vcc.get_api().post('/data/log', files=[('file', (file.name, file, file.format))])
            logger.info(f'successfully uploaded {file.name} in {(datetime.now()-t0).total_seconds():.3f} seconds' \
                if rsp else f'failed uploading {file.name}! [{rsp.text}]')
    else:
        logger.warning(f'{path} does not exist!')

