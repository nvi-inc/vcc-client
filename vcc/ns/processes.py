import shutil
from threading import Thread, Event
import traceback
import logging
import re
import os
import json
import psutil
import tempfile

from collections import namedtuple
from pathlib import Path

from vcc import settings, make_path, vcc_cmd
from vcc.utils import get_next_sessions
from vcc.ns.drudg import DRUDG
from vcc.ns import get_displays, show_sessions, notify
from vcc.socket import Client
from vcc import json_encoder, json_decoder


Addr = namedtuple('addr', 'ip port')

logger = logging.getLogger('vcc')


def send_msg(header, data):
    for display in get_displays():
        try:
            if (port := get_port(display)) or (port := start_inbox(display)):
                client = Client('127.0.0.1', port)
                client.send(json.dumps((header, data), default=json_encoder).encode("utf-8"))
        except Exception as exc:
            logger.warning(f'send msg {str(exc)}')
    # Save msg in hidden directory
    path = Path(os.environ.get('VCC_HIDDEN', '/tmp'), 'vcc-msg-ns.json')
    path.touch(exist_ok=True)
    with open(path, 'r+') as f:
        records = json_decoder(json.loads(record)) if (record := f.read()) else []
        records.append((header, data))
        f.seek(0)
        f.write(json.dumps(records, default=json_encoder))


def get_port(display):
    for index, prc in enumerate(psutil.process_iter()):
        try:
            if prc.name() == 'inbox-ns':
                param = prc.cmdline()
                if param[param.index('-D') + 1] == display:
                    for conn in prc.net_connections():
                        if conn.status == 'LISTEN':
                            return Addr(*conn.laddr).port
        except (IndexError, Exception):
            pass
    print('get_port', None)
    return None


def start_inbox(display):
    logger.info(f"Start inbox-ns with DISPLAY {display}")
    vcc_cmd('inbox-ns', f"-D '{display}'", user='oper', group='rtx')
    for _ in range(5):
        if port := get_port(display):
            return port
        Event().wait(1)
    return None


class ProcessMaster(Thread):
    # overriding constructor
    def __init__(self, vcc, sta_id, headers, data):
        # calling parent class constructor
        Thread.__init__(self)
        self.vcc, self.sta_id = vcc, sta_id
        self.headers, self.data = headers, data

    def run(self):
        send_msg(self.headers, self.data)

    def _run(self):
        show_sessions(f'List of modified sessions for {self.sta_id}', list(self.data.items()))
        # Get session information
        session_list, begin, end = get_next_sessions(self.vcc, self.sta_id)
        sessions = [(ses_id, self.data.get(ses_id, '')) for ses_id in session_list] if session_list else []
        # Display information
        when = f" ({begin.date()} to {end.date()})" if sessions else ''
        title = f'List of sessions for {self.sta_id.capitalize()}{when}'
        show_sessions(title, sessions, option='-M ')


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
        logger.info(f'drudg_it {drudg_it}')
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


class ProcessUrgent(Thread):
    # overriding constructor
    def __init__(self, vcc, sta_id, headers, data):
        # calling parent class constructor
        Thread.__init__(self)
        self.vcc, self.sta_id = vcc, sta_id
        self.headers, self.data = headers, data

    def run(self):
        send_msg(self.headers, self.data)

    def _run(self):
        title = f'Urgent message from {self.data.get("fr", "?")}'
        msg = self.data.get("message", "EMPTY").splitlines()
        notify(title, '<br>'.join(msg), icon='urgent')
        logger.info(title)
        for index, line in enumerate(msg, 1):
            logger.info(f'{index:2d} {line}')

