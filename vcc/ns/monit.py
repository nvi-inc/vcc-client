import json
import re
import traceback
import logging
import time

from collections import namedtuple
from threading import Thread, Event

from vcc.client import VCC, VCCError
from vcc.ns.processes import ProcessMsg, ProcessSchedule, ProcessLog

Addr = namedtuple('addr', 'ip port')

logger = logging.getLogger('vcc')

process = dict(schedule=ProcessSchedule, log=ProcessLog)


class InboxMonitor(Thread):

    extract_name = re.compile('.*filename=\"(?P<name>.*)\".*').match

    def __init__(self, sta_id, vcc, interval=5):
        super().__init__()

        self.sta_id, self.vcc, self.interval = sta_id, vcc, interval
        self.stopped = Event()

    def check_inbox(self):
        t = time.time()
        try:
            if rsp := self.vcc.get(f'/messages'):
                for headers, data in rsp.json():
                    self.process_message(headers, data)
        except VCCError:
            pass
        return time.time() - t

    def run(self):
        logger.info(f'monit started {self.native_id}')
        dt = self.check_inbox()
        while not self.stopped.wait(self.interval if dt > self.interval else self.interval - dt):
            dt = self.check_inbox()

    def stop(self):
        logger.inbox(f'inbox stop requested')
        self.stopped.set()

    def process_message(self, headers, data):
        code = headers['code']
        logger.debug(f'process_message{headers} {data}')
        if code == 'ping':
            self.pong(headers['sender'], status='Ok')
        else:  # Decode message
            try:
                data = json.loads(data) if headers.get('format', 'text') == 'json' else {}
                text = ', '.join([f'{key}={val}' for key, val in data.items()]) if isinstance(data, dict) else str(data)
                logger.info(f'processing message: {code} {text}')
                if prc := process.get(code, ProcessMsg):
                    prc(self.vcc, self.sta_id, headers, data).start()
            except Exception as exc:
                logger.warning(f'message invalid -  0 {str(exc)}')
                for index, line in enumerate(traceback.format_exc().splitlines(), 1):
                    logger.warning(f'message invalid - {index:2d} {line.strip()}')

    def pong(self, sender, status='Ok'):
        try:
            self.vcc.post(f'/messages/pong', data={'key': sender, 'status': status})
        except VCCError as err:
            logger.warning(f"pong {str(err)}")
