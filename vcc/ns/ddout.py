import os.path
from threading import Thread, Event
from datetime import datetime, timedelta
import re
import logging
import traceback

from vcc import VCCError, json_decoder, vcc_cmd
from vcc.client import RMQclientException
from vcc.ns import get_ddout_log
from vcc.ns.onoff import post_onoff

logger = logging.getLogger('vcc')


# Read records from log file opened by ddout
class DDoutScanner(Thread):
    key_words: set = {'warm', 'missed', 'issue', 'fmout-gps', 'gps-fmout', 'late'}

    is_pcfs = re.compile(r'^(?P<time>^\d{4}\.\d{3}\.\d{2}:\d{2}:\d{2}\.\d{2})(?P<data>.*)$').match
    is_header = re.compile(r'(?P<key>#onoff# {4}source)(?P<data>.*)$').match
    is_onoff = re.compile(r'(?P<key>#onoff#VAL)(?P<data>.*)$').match
    is_acquired = re.compile(r'.(?P<key>#trakl#)(?P<data>.*)$').match
    keys = [(re.compile(f'{separator}(?P<key>{key})(?P<data>.*)$').match, msg) for (separator, key, msg)
            in [(':', 'exper_initi', 'schedule loaded {ses_id}'),
                (':', 'sched_end', 'schedule ended'),
                (';', 'halt', 'schedule halted'),
                (';', 'contstatus', None),
                (';', 'cont', 'schedule continue'),
                (':', 'scan_name=[a-zA-Z0-9-]*', '{key}'),
                (':', 'source=[a-zA-Z0-9-+]*', '{key}'),
                ('', '#trakl# Source acquired', 'Source acquired')
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
                logger.info(f'sending {self.ses_id} full log to VCC')
                vcc_cmd('vccns', f'log -q {self.ses_id}')

        self.active = self.log = None

    def is_valid_session(self, ses_id):
        rsp = self.vcc.api.get(f'/sessions/{ses_id}')
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
            try:
                self.log.seek(0, 2)
                self.log.seek(max(self.log.tell() - 10000, 0), 0)
            except Exception as exc:
                logger.debug(str(exc))
            ses_id = name[:-6] if name.endswith(f'{self.sta_id.lower()}.log') else None
            self.ses_id = ses_id if ses_id and self.is_valid_session(ses_id) else None
            if self.ses_id:
                self.send_msg({'status': f'{name} opened', 'session': self.ses_id})
            logger.debug(f'OPEN LOG {path} SES_ID {self.ses_id}')
        return self.last_time.get(self.active, datetime.utcnow() - timedelta(seconds=2))

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
        self.onoff = post_onoff(self.vcc.api, self.onoff)

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
                if not (path := get_ddout_log()):
                    self.send_onoff()
                    self.close_log()
                else:
                    last = self.open_log(path)
                    for line in self.log:
                        logger.info(line[:40])
                        if rec := self.is_pcfs(line):
                            timestamp, info = datetime.strptime(rec['time'], '%Y.%j.%H:%M:%S.%f'), rec['data']
                            if timestamp >= last:
                                logger.warning(str(info))
                                if not self.is_onoff_header(info) and not self.is_onoff_record(timestamp, info):
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

