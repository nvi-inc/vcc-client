import re
import logging
from pathlib import Path

from vcc import VCCError, settings
from vcc.client import VCC
from vcc.fslog import fs2time


logger = logging.getLogger('vcc')


# Send ONOFF records to VCC
def post_onoff(vcc, records):
    if records:
        try:
            if vcc and (rsp := vcc.post('/data/onoff', data=records)):
                logger.info(f'uploaded {len(records)} onoff records for {records[0]["source"]}')
            else:
                raise VCCError(rsp.text)
        except VCCError as exc:
            logger.warning(f'failed uploading onoff {str(exc)}')
    return []


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
                records = post_onoff(vcc, records)  # Send existing onoff records to VCC

        post_onoff(vcc, records)
