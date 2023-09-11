import os.path
from threading import Thread, Event
from datetime import datetime, timedelta
import re
import logging
import traceback

from psutil import process_iter, AccessDenied, NoSuchProcess

from vcc import VCCError, json_decoder
from vcc.messaging import RMQclientException
from vcc.ns import notify
from vcc.ns.onoff import post_onoff
from vcc.ns.processes import ProcessLog

logger = logging.getLogger('vccns')


# Read records from log file opened by ddout
class DDoutScanner(Thread):
    key_words: set = {'warm', 'missed', 'issue', 'fmout-gps', 'gps-fmout', 'late'}

    is_pcfs = re.compile(r'^(?P<time>^\d{4}\.\d{3}\.\d{2}:\d{2}:\d{2}\.\d{2})(?P<data>.*)$').match
    is_header = re.compile(r'(?P<key>#onoff#    source)(?P<data>.*)$').match
    is_onoff = re.compile(r'(?P<key>#onoff#VAL)(?P<data>.*)$').match
    is_info = re.compile(r';\"(?P<key>ses-info):(?P<data>.*)$').match
    keys = [(re.compile(f'{separator}(?P<key>{key})(?P<data>.*)$').match, msg) for (separator, key, msg)
            in [(':', 'exper_initi', 'schedule loaded {ses_id}'),
                (':', 'sched_end', 'schedule ended'),
                (';', 'halt', 'schedule halted'),
                (';', 'contstatus', None),
                (';', 'cont', 'schedule continue'),
                (':', 'scan_name=[a-zA-Z0-9-]*', '{key}'),
                (':', 'source=[a-zA-Z0-9-+]*', '{key}')
                ]
            ]

    def __init__(self, sta_id, vcc, problem):
        super().__init__()

        self.stopped = Event()
        self.sta_id, self.vcc, self.problem, self.rmq = sta_id, vcc, problem, None
        self.log = self.active = self.ses_id = None
        self.last_time = {}
        self.onoff, self.header = [], []

    # Close the log file
    def close_log(self):
        if self.log:
            self.log.close()
            if self.ses_id:
                self.send_msg({'status': f'{os.path.basename(self.active)} closed', 'session': self.ses_id})
                ProcessLog(self.vcc, self.sta_id, 'full_log', {'session': self.ses_id})

        self.active = self.log = None

    def is_valid_session(self, ses_id):
        rsp = self.vcc.get_api().get(f'/sessions/{ses_id}')
        if rsp:
            data = json_decoder(rsp.json())
            return data.get('code', '').lower() == ses_id.lower() if data else False
        return False

    def connect(self, warning=None):
        try:
            self.rmq = self.vcc.get_rmq_connection()
            if warning:
                logger.warning(warning)
        except VCCError:
            self.problem.set()

    # Open log file if different that active file
    def open_log(self, path):
        if path != self.active:
            name = os.path.basename(path)
            self.close_log()
            self.active, self.log = path, open(path, 'r', encoding="utf8", errors="ignore")
            ses_id = name[:-6] if name.endswith(f'{self.sta_id.lower()}.log') else None
            self.ses_id = ses_id if ses_id and self.is_valid_session(ses_id) else None
            logger.debug(f'OPEN LOG {path} SES_ID {self.ses_id}')
            if self.ses_id:
                self.send_msg({'status': f'{name} opened', 'session': self.ses_id})
        return self.last_time.get(self.active, datetime.utcnow() - timedelta(seconds=2))

    # Get the path of the file opened by ddout
    @staticmethod
    def get_ddout_log():
        for proc in process_iter(['name', 'pid']):
            if proc.info['name'] == 'ddout':
                try:
                    files = [file.path for file in proc.open_files() if file.path.startswith('/usr2/log')]
                    return files[0] if files else None
                except (NoSuchProcess, AccessDenied):
                    return None
        return None

    # Check if ses-info message to be sent to vcc
    def is_info_record(self, info):
        rec = self.is_info(info)
        if not rec:
            return False
        data = rec['data'].split(',')
        ses_id, key_word = self.ses_id, data[0].lower()
        if len(data) > 1 and data[1].lower() in self.key_words:
            ses_id, key_word = data[0], data[1].lower()
        if not ses_id:
            notify(f'Invalid ses-info record', f'Session code is required', icon='warning')
        elif ses_id != self.ses_id and not self.test_session(ses_id):
            notify(f'Invalid ses-info record', f'{ses_id} is not valid session<br>or<br>{self.sta_id} not in {ses_id}',
                   icon='warning')
        elif key_word not in self.key_words:
            notify(f'Invalid ses-info record)', f'Valid key words are:<br>{"<br>".join(self.key_words)}',
                   icon='warning')
        else:
            self.send_msg({'status': f'{rec["key"]}:{rec["data"]}', 'session': ses_id})
        return True

    # Check if ONOFF header
    def is_onoff_header(self, info):
        rec = self.is_header(info)
        if not rec:
            return False
        self.header = ['source'] + rec['data'].split()
        self.send_onoff()  # Send existing onoff records to VCC
        return True

    # Check if ONOFF VAL record
    def is_onoff_record(self, timestamp, info):
        rec = self.is_onoff(info)
        if not rec:
            return False
        record = {name: value for name, value in zip(self.header, rec['data'].split())}
        self.onoff.append(dict(**{'time': timestamp}, **record))
        return True

    # Send ONOFF record to VCC
    def send_onoff(self):
        self.onoff = post_onoff(self.vcc.get_api(), self.onoff)

    # Send station status to VCC Messenger
    def send_status(self, info):
        for (is_key, status) in self.keys:
            rec = is_key(info)
            if rec:
                if status:
                    msg = {'status': status.format(ses_id=self.ses_id, key=rec['key']), 'session': self.ses_id}
                    self.send_msg(msg)
                return

    def send_msg(self, msg):
        try:
            self.rmq.send(self.sta_id, 'sta_info', 'msg', msg)
            logger.info(f'sta_info msg {str(msg)}')
        except Exception as exc:
            logger.warning(f'sta_inf msg {str(msg)} failed')
            logger.warning(f'sta_info msg problem -  0 {str(exc)}')
            for index, line in enumerate(traceback.format_exc().splitlines(), 1):
                logger.warning(f'sta_info msg problem - {index:2d} {line.strip()}')

    # The continuous function
    def run(self):
        logger.info(f'ddout started {self.native_id}')
        self.connect()
        while not self.stopped.wait(0.5):
            try:
                self.rmq.keep_connection_alive()
                path = self.get_ddout_log()
                if not path:
                    self.send_onoff()
                    self.close_log()
                else:
                    last = self.open_log(path)
                    for line in self.log:
                        rec = self.is_pcfs(line)
                        if rec:
                            timestamp, info = datetime.strptime(rec['time'], '%Y.%j.%H:%M:%S.%f'), rec['data']
                            if timestamp >= last:
                                if not self.is_info_record(info) and not self.is_onoff_header(info) \
                                        and not self.is_onoff_record(timestamp, info):
                                    self.send_onoff()
                                    self.send_status(info)
                                self.last_time[self.active] = timestamp
            except (RMQclientException, VCCError) as exc:
                logger.warning(f'ddout communication failed - {str(exc)}')
                self.connect(warning='ddout communication reset')

        self.send_onoff()
        self.close_log()
        logger.info('ddout stopped')

    def stop(self):
        logger.debug(f'ddout stop requested')
        self.stopped.set()

