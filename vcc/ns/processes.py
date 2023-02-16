import shutil
from threading import Thread
import logging
import re
import os
from datetime import datetime

from vcc import settings, make_path
from vcc.session import Session
from vcc.mail import mail_it
from vcc.ns.drudg import DRUDG
from vcc.ns.fslog import upload
from vcc.ns import notify

logger = logging.getLogger('vcc')


def notify_all(title, message):
    try:
        notify(title, message, all_users=True)
    except Exception:
        logger.warning('could not notify oper')
    try:
        mail_it(title, message)
    except Exception:
        logger.warning('could not sent email')

    return None


class ProcessMaster(Thread):
    # overriding constructor
    def __init__(self, vcc, sta_id, data):
        # calling parent class constructor
        Thread.__init__(self)
        self.vcc, self.sta_id, self.data = vcc, sta_id, data

    def run(self):
        logger.debug('star processing master')

        message = ['List of sessions', '-'*16] if self.data else []
        # Get session information
        api = self.vcc.get_api()
        for ses_id, status in self.data.items():
            rsp = api.get(f'/sessions/{ses_id}')
            if rsp:
                session = Session(rsp.json())
                message.append(f'{session} --- {status}!')

        # Display upcoming sessions
        message.extend(['', f'List of upcoming sessions for {self.sta_id}', '-'*30])
        rsp = api.get(f'/sessions/next/{self.sta_id}', params={'days': 14})
        if rsp:
            index, now = 1, datetime.utcnow()
            for data in rsp.json():
                session = Session(data)
                if session.start > now:
                    message.append(f'{index:2d} {session}')
                    index += 1

        notify_all('Master has changed', '<br>'.join(message))

        logger.debug('end processing master')


class ProcessSchedule(Thread):

    get_name = re.compile('.*filename=\"(?P<name>.*)\".*').match

    def __init__(self, vcc, sta_id, data):
        # calling parent class constructor
        Thread.__init__(self)
        self.vcc, self.sta_id, self.data = vcc, sta_id, dict(data)

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
        ses_id = self.data['session'].lower()
        logger.debug(f'star processing schedule {ses_id}')
        # Download schedule (skd first)
        download_option = settings.Messages.Schedule.download.split()[0]
        if download_option == 'no':
            return notify_all(f'New schedule available for {ses_id}', 'Not downloaded: configuration set to no')
        # Request file from VCC
        rsp = self.vcc.get_api().get(f'/schedules/{ses_id}')
        logger.debug(f'get schedule {rsp.status_code}')
        if not rsp:
            return notify_all(f'Problem downloading schedule for {ses_id}', rsp.text)
        # Save schedule in Schedules folder
        found = self.get_name(rsp.headers['content-disposition'])
        if not found:
            return notify_all(f'Problem downloading schedule for {ses_id}', rsp.headers['content-disposition'])
        filename = found['name']
        path = make_path(settings.Folders.schedule, filename)
        modified = self.prc_snp_modified(path, ses_id)
        self.rename(download_option, path)
        with open(path, 'wb') as f:
            f.write(rsp.content)
        logger.info(f'{filename} downloaded')
        # Execute drudg
        drudg_it = settings.Messages.Schedule.drudg
        if drudg_it == 'no':
            return notify_all(f'{filename} has been downloaded but not processed',
                              'DRUDG is not set for automatic mode')
        if modified and drudg_it == 'not_modified':
            return notify_all(f'{filename} has been downloaded but not processed',
                              '\n'.join([f'{file} was manually modified' for file in modified]))
        # Drug it
        sta_id = self.sta_id.lower()
        proc = DRUDG(ses_id, sta_id)
        err = proc.drudg(filename)
        if err:
            return notify_all(f'Problem DRUDG {ses_id}', err)

        modified = os.stat(path).st_mtime
        ok = lambda f: "ok" if os.path.exists(f) and os.stat(f).st_mtime == modified else "not created"
        msg = [f'{os.path.basename(file)} {ok(file)}'
               for file in [make_path(settings.Folders.snap, f'{ses_id}{sta_id}.snp'),
                            make_path(settings.Folders.proc, f'{ses_id}{sta_id}.prc')]]
        lst = make_path(settings.Folders.list, f'{ses_id}{sta_id}.lst')
        msg.append(f'{os.path.basename(lst)} {"ok" if os.path.exists(lst) else "not created"}')

        notify_all(f'New schedule for {ses_id}{" - problem drudging it" if err else ""}', '\n'.join(msg))
        logger.debug(f'end processing schedule {ses_id}')


class ProcessLog(Thread):
    # overriding constructor
    def __init__(self, vcc, sta_id, code, data):
        # calling parent class constructor
        Thread.__init__(self)
        self.vcc, self.sta_id, self.full, self.data = vcc, sta_id, code == 'full_log', data

    def run(self):
        logger.debug('star processing log')
        ans = upload(self.sta_id, self.data['session'], full=True)
        logger.debug(ans)



