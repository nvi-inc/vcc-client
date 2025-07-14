import shutil
import time
from threading import Thread, Event
import traceback
import logging
import re
import os
import json
import psutil
import tempfile
import sys

from collections import namedtuple
from datetime import datetime, timedelta
from pathlib import Path

from vcc import settings, make_path, vcc_cmd
from vcc.utils import get_next_sessions
from vcc.ns.drudg import DRUDG
from vcc.ns import get_displays, show_sessions, notify
from vcc import json_encoder, json_decoder


Addr = namedtuple('addr', 'ip port')

logger = logging.getLogger('vcc')


def send_msg(header, data):

    # Save msg in messages directory
    path = Path(Path(sys.prefix).parent, 'messages', "ns.json")
    path.touch(exist_ok=True)
    # Read old records
    with open(path, 'r') as f:
        records = json_decoder(json.loads(record)) if (record := f.read()) else []
        records.append((json_decoder(header), data))
    # Remove records older than 5 days
    too_old = datetime.utcnow() - timedelta(days=5)
    records = [rec for rec in records if rec[0]['utc'] > too_old]
    # Save to temporary and rename (to avoid overwriting file being read)
    tmp = tempfile.NamedTemporaryFile(delete=False).name
    with open(tmp, 'w') as f:
        f.write(json.dumps(records, default=json_encoder))
    shutil.move(tmp, str(path), copy_function=shutil.copyfile)
    path.chmod(0o664)

    # Start inbox if needed
    inboxes = get_inboxes()
    for display in get_displays():
        if not inboxes.get(display, None):
            start_inbox(display)


def get_inboxes():
    inboxes = {}
    for index, prc in enumerate(psutil.process_iter()):
        try:
            if prc.name() == 'vcc':
                ok = {'inbox', 'NS'}.issubset(prc.cmdline())
                if {'inbox', 'NS'}.issubset(prc.cmdline()) and (display := prc.environ().get('DISPLAY', None)):
                    inboxes[display] = prc.pid
        except (IndexError, Exception):
            pass
    return inboxes


def start_inbox(display):
    env = {'DISPLAY': display}
    return vcc_cmd('/usr2/vcc/bin/inbox', '', user='oper', group='rtx', env=env)


class ProcessSchedule(Thread):

    get_name = re.compile('.*filename=\"(?P<name>.*)\".*').match

    def __init__(self, vcc, sta_id, headers, data):
        # calling parent class constructor
        Thread.__init__(self)
        self.vcc, self.sta_id = vcc, sta_id
        self.ses_id = data.get('session', None) if data else None
        self.headers, self.data = headers, data

    @staticmethod
    def rename(download_option, path):
        if download_option == 'rename' and path.exists():
            for i in range(1, 10):
                new_path = Path(f'{str(path)}.{i}')
                if not new_path.exists():
                    shutil.move(path, new_path)
                    return

    def prc_snp_modified(self, sched, ses_id):
        if not os.path.exists(sched):
            return []
        sched_time = os.stat(sched).st_mtime
        name = f'{ses_id}{self.sta_id.lower()}'
        files = [make_path(settings.Folders.snap, f'{name}.snp'), make_path(settings.Folders.proc, f'{name}.prc')]
        return [os.path.basename(file) for file in files
                if os.path.exists(file) and os.stat(file).st_mtime > sched_time]

    def run(self):
        # Download schedule (skd first)
        download_option = settings.Messages.Schedule.download.split()[0]
        if download_option == 'no':
            self.data['processed'] = 'Schedule not downloaded: configuration set to NO'
            return send_msg(self.headers, self.data)
        # Request file from VCC
        if not (rsp := self.vcc.get(f'/schedules/{self.ses_id}')):
            self.data['processed'] = f'Problem downloading schedule for\n\n {rsp.text}'
            return send_msg(self.headers, self.data)
        # Save schedule in Schedules folder
        if not (found := self.get_name(rsp.headers['content-disposition'])):
            self.data['processed'] = f"Problem downloading schedule\n\n {rsp.headers['content-disposition']}"
            return send_msg(self.headers, self.data)

        filename = found['name']
        path = make_path(settings.Folders.schedule, filename)
        modified = self.prc_snp_modified(path, self.ses_id)
        self.rename(download_option, path)
        with open(path, 'wb') as f:
            f.write(rsp.content)
        logger.info(f'{filename} downloaded')
        # Execute drudg
        drudg_it = settings.Messages.Schedule.drudg
        if drudg_it == 'no':
            self.data['processed'] = (f'{filename} has been downloaded but not processed<br><br>'
                                      f'DRUDG is not set for automatic mode')
            return send_msg(self.headers, self.data)
        if modified and drudg_it == 'not_modified':
            extra = '<br>'.join([f'{file} was manually modified' for file in modified])
            self.data['processed'] = f'{filename} has been downloaded but not processed<br><br>{extra}'
            return send_msg(self.headers, self.data)
        # Drug it
        try:
            sta_id = self.sta_id.lower()
            proc = DRUDG(self.ses_id, sta_id)
            err = proc.drudg(filename)
            if err:
                self.data['processed'] = (f'{filename} has been downloaded but not processed<br><br>'
                                          f'Problem DRUDGing: {err}')
                return send_msg(self.headers, self.data)
        except Exception as exc:
            logger.warning(str(exc))
            for index, line in enumerate(traceback.format_exc().splitlines(), 1):
                logger.warning(f'{index:3d} {line}')
            return

        modified = os.stat(path).st_mtime

        def ok_msg(_f):
            return "ok" if os.path.exists(_f) and os.stat(_f).st_mtime == modified else "not created"

        msg = [f'{os.path.basename(file)} {ok_msg(file)}'
               for file in [make_path(settings.Folders.snap, f'{self.ses_id}{sta_id}.snp'),
                            make_path(settings.Folders.proc, f'{self.ses_id}{sta_id}.prc')]]
        lst = make_path(settings.Folders.list, f'{self.ses_id}{sta_id}.lst')
        msg.append(f'{os.path.basename(lst)} {"ok" if os.path.exists(lst) else "not created"}')
        extra = '<br>'.join(msg)
        self.data['icon'] = 'warning' if err else 'info'
        self.data['processed'] = f"New schedule processed {' - problem drudging it' if err else ''}<br><br>{extra}"
        return send_msg(self.headers, self.data)


class ProcessLog(Thread):
    # overriding constructor
    def __init__(self, vcc, sta_id, data=None):
        # calling parent class constructor
        Thread.__init__(self)
        self.vcc, self.sta_id = vcc, sta_id
        self.data = data if data else {}

    def run(self):
        if ses_id := self.data.get('session', None):
            vcc_cmd('fslog', f'-C {self.sta_id} {ses_id}')


class ProcessMsg(Thread):

    # overriding constructor
    def __init__(self, vcc, sta_id, headers, data):
        # calling parent class constructor
        Thread.__init__(self)
        self.vcc, self.sta_id = vcc, sta_id
        self.headers, self.data = headers, data

    def run(self):
        send_msg(self.headers, self.data)
