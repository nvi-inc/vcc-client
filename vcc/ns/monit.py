import json
import re
import traceback
import logging
from threading import Thread, Event

from vcc.client import RMQclientException
from vcc.ns.processes import ProcessMaster, ProcessSchedule, ProcessLog, ProcessMsg, ProcessUrgent

logger = logging.getLogger('vcc')


class InboxMonitor(Thread):

    extract_name = re.compile('.*filename=\"(?P<name>.*)\".*').match

    def __init__(self, sta_id, vcc, comm_flag):
        super().__init__()

        self.sta_id, self.vcc, self.comm_flag = sta_id, vcc, comm_flag
        try:
            self.rmq_client = self.vcc.get_rmq_client()
        except:
            self.rmq_client = None
            self.comm_flag.set()
        self.stopped = Event()

    def run(self):
        logger.info('inbox started')
        try:
            while True:
                try:
                    self.rmq_client.monit(self.process_message)
                except RMQclientException as exc:
                    logger.debug(f'inbox communication reset - {self.stopped.is_set()}')
                    if self.stopped.is_set():
                        break
                    Event().wait(10)
                    try:
                        self.rmq_client = self.vcc.get_rmq_client()
                        logger.info('inbox communication reset')
                    except:
                        self.comm_flag.set()
                        break
                except Exception as exc:
                    logger.debug(f'inbox problem {str(exc)}')
                    Event().wait(10)
        except Exception as exc:
            logger.debug(f'big problem {str(exc)}')

        logger.info('inbox stopped')

    def stop(self):
        logger.debug(f'inbox stop requested')
        self.stopped.set()
        Event().wait(1)
        self.rmq_client.close()

    def process_message(self, headers, data):
        # Ping sent by dashboard
        code = headers['code']
        logger.debug(f'{headers} {data}')
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
                    ProcessLog(self.vcc, self.sta_id, data).start()
                elif code == 'msg':
                    ProcessMsg(self.vcc, self.sta_id, data).start()
                elif code == 'urgent':
                    ProcessUrgent(self.vcc, self.sta_id, data).start()
            except Exception as exc:
                logger.warning(f'message invalid -  0 {str(exc)}')
                for index, line in enumerate(traceback.format_exc().splitlines(), 1):
                    logger.warning(f'message invalid - {index:2d} {line.strip()}')

        # Always acknowledge message
        self.rmq_client.acknowledge_msg()

    def get_messages(self):
        try:
            self.rmq_client.get(self.process_message)
        except RMQclientException as exc:
            logger.debug(f'Problem retrieving messages {str(exc)}')


