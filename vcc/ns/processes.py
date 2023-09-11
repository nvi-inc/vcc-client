import json
import shutil
from threading import Thread
import traceback
import logging
import re
import os
from datetime import datetime
from subprocess import Popen

from vcc import settings, make_path
from vcc.session import Session
from vcc.mail import mail_it
from vcc.ns.drudg import DRUDG
from vcc.ns.fslog import upload
from vcc.ns import notify

logger = logging.getLogger('vcc')


def notify_all(title, sessions, option='', icon='info'):
    try:
        json.dumps(sessions)
        notify(title, json.dumps(sessions), option=option, all_users=True, icon=icon)
    except:
        logger.warning('could not notify oper')
    #try:
    #    message = '\n'.join([f'{Session(ses)} --- {ses["status"]}' for ses in sessions])
    #    mail_it(title, message)
    #except:
    #    logger.warning('could not sent email')

    return None


class ProcessMaster(Thread):
    # overriding constructor
    def __init__(self, vcc, sta_id, data):
        # calling parent class constructor
        Thread.__init__(self)
        self.vcc, self.sta_id = vcc, sta_id
        self.data = data if data else {}

    def run(self):
        logger.debug('star processing master')

        sessions = []
        # Get session information
        api = self.vcc.get_api()
        for ses_id, status in self.data.items():
            rsp = api.get(f'/sessions/{ses_id}')
            if rsp:
                sessions.append(dict(**rsp.json(), **{'status': status}))
        notify_all(f'List of modified sessions for {self.sta_id}', sessions, option='-m')

        # Display upcoming sessions
        Popen(["vcc-ns next"], shell=True, stdin=None, stdout=None, stderr=None, close_fds=True)


class ProcessSchedule(Thread):

    get_name = re.compile('.*filename=\"(?P<name>.*)\".*').match

    def __init__(self, vcc, sta_id, data=None):
        # calling parent class constructor
        Thread.__init__(self)
        self.vcc, self.sta_id = vcc, sta_id
        self.ses_id = data.get('session', None) if data else None

    @staticmethod
    def rename(download_option, path):
        if download_option == 'rename' and os.path.exists(path):
            for i in range(1, 10):
                new_path = f'{path}.{i}'
                if not os.path.exists(new_path):
                    shutil.move(path, new_path)
                    return

    def prc_snp_modified(self, sched, ses_id):
        if not os.path.exists(sched):
            return []
        sched_time = os.stat(sched).st_mtime
        logger.debug(f'sched {sched_time}')
        name = f'{ses_id}{self.sta_id.lower()}'
        files = [make_path(settings.Folders.snap, f'{name}.snp'), make_path(settings.Folders.proc, f'{name}.prc')]
        [logger.debug(f'{file} {os.stat(file).st_mtime}') for file in files if os.path.exists(file)]
        return [os.path.basename(file) for file in files
                if os.path.exists(file) and os.stat(file).st_mtime > sched_time]

    def run(self):
        logger.debug(f'star processing schedule {self.ses_id}')
        # Download schedule (skd first)
        download_option = settings.Messages.Schedule.download.split()[0]
        if download_option == 'no':
            return notify_all(f'New schedule available for {self.ses_id}', 'Not downloaded: configuration set to no',
                              icon='warning')
        # Request file from VCC
        rsp = self.vcc.get_api().get(f'/schedules/{self.ses_id}')
        logger.debug(f'get schedule {rsp.status_code}')
        if not rsp:
            return notify_all(f'Problem downloading schedule for {self.ses_id}', rsp.text, icon='urgent')
        # Save schedule in Schedules folder
        found = self.get_name(rsp.headers['content-disposition'])
        if not found:
            return notify_all(f'Problem downloading schedule for {self.ses_id}', rsp.headers['content-disposition'],
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
            return notify_all(f'{filename} has been downloaded but not processed',
                              'DRUDG is not set for automatic mode', icon='warning')
        if modified and drudg_it == 'not_modified':
            return notify_all(f'{filename} has been downloaded but not processed',
                              '<br>'.join([f'{file} was manually modified' for file in modified]), icon='warning')
        # Drug it
        try:
            sta_id = self.sta_id.lower()
            proc = DRUDG(self.ses_id, sta_id)
            err = proc.drudg(filename)
            if err:
                return notify_all(f'Problem DRUDG {self.ses_id}', err, icon='urgent')
        except Exception as exc:
            logger.info(str(exc))
            logger.info(traceback.format_exc())
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
        notify_all(f'New schedule for {self.ses_id}{" - problem drudging it" if err else ""}'
                   , '<br>'.join(msg), icon=icon)
        logger.debug(f'end processing schedule {self.ses_id}')


class ProcessLog(Thread):
    # overriding constructor
    def __init__(self, vcc, sta_id, data=None):
        # calling parent class constructor
        Thread.__init__(self)
        self.vcc, self.sta_id, self.ses_id = vcc, sta_id
        self.data = data if data else {}

    def run(self):
        ses_id = self.data.get('session', None)
        if ses_id:
            upload(self.vcc, self.sta_id, ses_id, full=True)


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
        notify(title, '<br>'.join(msg), option='', all_users=True, icon='urgent')
        logger.info(title)
        for index, line in enumerate(msg, 1):
            logger.info(f'{index:2d} {line}')


