import shutil
from threading import Thread
import traceback
import logging
import re
import os
from pathlib import Path

from vcc import settings, make_path, vcc_cmd
from vcc.utils import get_next_sessions
from vcc.ns.drudg import DRUDG
from vcc.ns import notify, show_sessions

logger = logging.getLogger('vcc')


class ProcessMaster(Thread):
    # overriding constructor
    def __init__(self, vcc, sta_id, data):
        # calling parent class constructor
        Thread.__init__(self)
        self.vcc, self.sta_id = vcc, sta_id
        self.data = data if data else {}

    def run(self):
        logger.debug('star processing master')

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

    def __init__(self, vcc, sta_id, data=None):
        # calling parent class constructor
        Thread.__init__(self)
        self.vcc, self.sta_id = vcc, sta_id
        self.ses_id = data.get('session', None) if data else None

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
            return notify(f'New schedule available for {self.ses_id}', 'Not downloaded: configuration set to NO',
                          icon='warning')
        # Request file from VCC
        if not (rsp := self.vcc.api.get(f'/schedules/{self.ses_id}')):
            return notify(f'Problem downloading schedule for {self.ses_id}', rsp.text, icon='urgent')
        # Save schedule in Schedules folder
        if not (found := self.get_name(rsp.headers['content-disposition'])):
            return notify(f'Problem downloading schedule for {self.ses_id}', rsp.headers['content-disposition'],
                          icon='urgent')
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
            return notify(f'{filename} has been downloaded but not processed',
                          'DRUDG is not set for automatic mode', icon='warning')
        if modified and drudg_it == 'not_modified':
            return notify(f'{filename} has been downloaded but not processed',
                          '<br>'.join([f'{file} was manually modified' for file in modified]), icon='warning')
        # Drug it
        try:
            sta_id = self.sta_id.lower()
            proc = DRUDG(self.ses_id, sta_id)
            err = proc.drudg(filename)
            if err:
                return notify(f'Problem DRUDG {self.ses_id}', err, icon='urgent')
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

        icon = 'urgent' if err else 'info'
        notify(f'New schedule for {self.ses_id}{" - problem drudging it" if err else ""}',
               '<br>'.join(msg), icon=icon)
        logger.debug(f'end processing schedule {self.ses_id}')


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
    def __init__(self, vcc, sta_id, data=None):
        # calling parent class constructor
        Thread.__init__(self)
        self.vcc, self.sta_id = vcc, sta_id
        self.data = data if data else {}

    def run(self):
        if msg := self.data.get("message", ""):
            logger.info(msg)


class ProcessUrgent(Thread):
    # overriding constructor
    def __init__(self, vcc, sta_id, data=None):
        # calling parent class constructor
        Thread.__init__(self)
        self.vcc, self.sta_id = vcc, sta_id
        self.data = data if data else {}

    def run(self):
        title = f'Urgent message from {self.data.get("fr", "?")}'
        msg = self.data.get("message", "EMPTY").splitlines()
        notify(title, '<br>'.join(msg), icon='urgent')
        logger.info(title)
        for index, line in enumerate(msg, 1):
            logger.info(f'{index:2d} {line}')


