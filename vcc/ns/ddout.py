from threading import Thread, Event
from datetime import datetime, timedelta
import re
import logging
from pathlib import Path

from vcc import VCCError, json_decoder, vcc_cmd
from vcc.ns import get_ddout_log
from vcc.ns.onoff import post_onoff
from vcc.fslog import fs2time


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

    def __init__(self, sta_id, vcc):
        super().__init__()

        self.stopped = Event()
        self.sta_id, self.vcc = sta_id, vcc
        self.log = self.active = self.ses_id = None
        self.log_time = {}
        self.onoff, self.header = [], []
        self.onoff_not_sent = []

    # Close the log file
    def close_log(self):
        if self.log:
            self.log.close()
            if self.ses_id:
                self.send_msg({'status': f'{Path(self.active).name} closed', 'session': self.ses_id})
                logger.info(f'sending {self.ses_id} full log to VCC')
                vcc_cmd('vccns', f'log -q {self.ses_id}')

        self.active = self.log = None

    def is_valid_session(self, ses_id):
        try:
            if rsp := self.vcc.get(f'/sessions/{ses_id}'):
                data = json_decoder(rsp.json())
                return data.get('code', '').lower() == ses_id.lower() if data else False
        except VCCError:
            pass
        return False

    # Open log file if different that active file
    def open_log(self, path):
        if not self.active or path.name != self.active.name:
            self.close_log()
            self.active, self.log = path, open(path, 'r', encoding="utf8", errors="ignore")
            try:
                self.log.seek(0, 2)
                self.log.seek(max(self.log.tell() - 10000, 0), 0)
            except Exception as exc:
                logger.debug(str(exc))
            self.ses_id = None
            if (name := path.stem).endswith(self.sta_id.lower()) and self.is_valid_session(ses_id := name[:-2]):
                self.ses_id = ses_id
                self.send_msg({'status': f'{path.name} opened', 'session': self.ses_id})
            logger.debug(f'OPEN LOG {path.name} SES_ID {self.ses_id}')
        return self.log_time.get(self.active.stem, (datetime.utcnow() - timedelta(seconds=2)).timestamp())

    # Check if ONOFF header
    def is_onoff_header(self, info):
        if not (rec := self.is_header(info)):
            return False
        self.header = ['source'] + rec['data'].split()
        self.send_onoff()  # Send existing onoff records to VCC
        return True

    # Check if ONOFF VAL record
    def is_onoff_record(self, timestamp, info):
        if not (rec := self.is_onoff(info)):
            return False
        record = {name: value for name, value in zip(self.header, rec['data'].split())}
        self.onoff.append(dict(**{'time': timestamp}, **record))
        return True

    # Send ONOFF record to VCC
    def send_onoff(self):
        try:
            if self.onoff_not_sent:
                self.onoff_not_sent = post_onoff(self.vcc, self.onoff_not_sent)
            self.onoff = post_onoff(self.vcc, self.onoff)
        except VCCError:
            self.onoff_not_sent = self.onoff
            self.onoff = []

    # Send station status to VCC Messenger
    def send_status(self, info):
        logger.info(f"status {info}")
        for (is_key, status) in self.keys:
            if rec := is_key(info):
                if status:
                    self.send_msg(status.format(ses_id=self.ses_id, key=rec['key']))
                return

    def send_msg(self, status):
        logger.info(f"sending status {status}")
        try:
            self.vcc.post(f'/messages/status', data={'session': self.ses_id, 'station': self.sta_id, 'status': status})
        except VCCError as exc:
            logger.warning(f"send_msg failed [{str(exc)}]")

    # The continuous function
    def run(self):
        logger.info(f'ddout started {self.native_id}')

        while not self.stopped.wait(0.1):
            try:
                if path := get_ddout_log():
                    last = self.open_log(path)
                    for line in self.log:
                        if rec := self.is_pcfs(line):
                            if (timestamp := fs2time(rec['time'])) >= last:
                                info = rec['data']
                                if not self.is_onoff_header(info) and not self.is_onoff_record(timestamp, info):
                                    self.send_onoff()
                                    self.send_status(info)
                                self.log_time[self.active.stem] = timestamp
                else:
                    self.send_onoff()
                    self.close_log()
            except VCCError as exc:
                logger.warning(f'ddout communication failed - {str(exc)}')

        self.send_onoff()
        self.close_log()
        logger.info('ddout stopped')

    def stop(self):
        logger.debug(f'ddout stop requested')
        self.stopped.set()
