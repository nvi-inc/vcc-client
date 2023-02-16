import os
import re
import logging
from datetime import datetime

from vcc import VCCError
from vcc.server import VCC

logger = logging.getLogger('vcc')


# Send ONOFF records to VCC
def post_onoff(api, records):
    if records:
        try:
            rsp = api.post('/data/onoff', data=records)
            if rsp:
                logger.info(f'uploaded {len(records)} onoff records for {records[0]["source"]}')
            else:
                logger.warning(f'failed uploading onoff {rsp.text}')
        except VCCError as exc:
            logger.warning(f'failed uploading onoff {str(exc)}')
    return []


def onoff(path):
    is_header = re.compile('^(?P<time>^\d{4}\.\d{3}\.\d{2}:\d{2}:\d{2}\.\d{2})(?P<key>#onoff#    source)'
                           '(?P<data>.*)$').match
    is_onoff = re.compile('^(?P<time>^\d{4}\.\d{3}\.\d{2}:\d{2}:\d{2}\.\d{2})(?P<key>#onoff#VAL)'
                          '(?P<data>.*)$').match

    logger.info(f'extracting onoff records from {os.path.basename(path)}')

    header, records = [], []
    with open(path, 'r', encoding="utf8", errors="ignore") as f, VCC('NS') as vcc:
        api = vcc.get_api()
        for line in f:
            found = is_onoff(line)
            if found:
                timestamp = datetime.strptime(found['time'], '%Y.%j.%H:%M:%S.%f')
                record = {name: value for name, value in zip(header, found['data'].split())}
                records.append(dict(**{'time': timestamp}, **record))
            else:
                found = is_header(line)
                if found:
                    header = ['source'] + found['data'].split()
                    records = post_onoff(api, records)  # Send existing onoff records to VCC

        post_onoff(api, records)
