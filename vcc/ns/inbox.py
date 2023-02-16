import json
import re
import traceback
import logging
from threading import Thread

from vcc.messaging import RMQclientException
from vcc.ns.processes import ProcessMaster, ProcessSchedule, ProcessLog

logger = logging.getLogger('vcc')


class InboxTracker(Thread):

    extract_name = re.compile('.*filename=\"(?P<name>.*)\".*').match

    def __init__(self, sta_id, vcc):
        super().__init__()

        self.sta_id, self.vcc = sta_id, vcc
        self.rmq_client = self.vcc.get_rmq_client()

    def run(self):
        logger.info('Start monitoring VCC')
        try:
            self.rmq_client.monit(self.process_message)
        except RMQclientException as exc:
            logger.debug(f'End listener monit {str(exc)}')

    def stop(self):
        logger.info(f'Stop monitoring {self.sta_id} inbox')
        self.rmq_client.close()

    def process_message(self, headers, data):
        # Ping sent by dashboard
        code = headers['code']
        print(headers, data)
        if code == 'ping':
            self.rmq_client.pong(self.sta_id, headers.get('reply_to'), 'Ok')
        else:
            # Decode message
            try:
                data = json.loads(data) if headers.get('format', 'text') == 'json' else {}
                text = ', '.join([f'{key}={val}' for key, val in data.items()]) if isinstance(data, dict) else str(data)
                logger.info(f'processing message: {code} {text}')
                if code == 'master':
                    ProcessMaster(self.vcc, self.sta_id, data).start()
                elif code == 'schedule':
                    ProcessSchedule(self.vcc, self.sta_id, data).start()
                elif code == 'log':
                    ProcessLog(self.vcc, self.sta_id, code, data).start()
            except Exception as exc:
                logger.warning(f'invalid message {str(exc)}')
                [logger.warning(line.strip()) for line in traceback.format_exc().splitlines()]

        # Always acknowledge message
        self.rmq_client.acknowledge_msg()

    def get_messages(self):
        try:
            self.rmq_client.get(self.process_message)
        except RMQclientException as exc:
            logger.debug(f'Problem retrieving messages {str(exc)}')


