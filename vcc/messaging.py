import functools
import logging
import uuid

from datetime import datetime, date
from urllib.parse import quote

import pika
import json

from vcc import json_encoder

logger = logging.getLogger('vcc')


# Define VLBIexception
class RMQclientException(Exception):
    def __init__(self, err_msg):
        self.err_msg = err_msg


# Class to connect to VCC message broker.
# Monitor specific queue or publish messages.
class RMQclient:

    def __init__(self, is_multi_thread=False):
        super().__init__()

        # Default TTL for important messages
        self.ttl = 5000
        self.max_attempts = 5
        self.consumer_tag = ''
        self.id = str(uuid.uuid4()).upper()
        logger.debug(f'rmqclient {self.id}')

        # Initialize some variables
        self.exchange = self.queue = None
        self._last_msg = (None, None)
        self.connection, self.publisher, self.consumer = None, None, None
        self.timeout, self.timeout_id = 300, None
        self.process_msg, self.process_timeout = self.do_nothing, None
        self.close_requested, self.last_data_events = False, datetime.now()

        if not is_multi_thread:  # Do not need multithread approach for sending message
            self.acknowledge_msg, self.send = self._acknowledge_msg, self._send
            self.on_timeout, self.reset_timeout = self._on_timeout, self._reset_timeout

    # Implement __enter__
    def __enter__(self):
        return self

    # Implement __exit__ needed by __enter__
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    # Make sure communications are close when instance is destroyed
    def __del__(self):
        if not self.close_requested:
            self.close()

    # Connect to broker
    def connect(self, config):
        if self.connection and not self.connection.is_closed:
            logger.debug('rmq connection already opened')
            return
        logger.debug('connecting to to VCC message broker')
        url, port = config.url, config.msg_port
        self.exchange, self.queue = config.exchange, config.queue

        try:
            user, password = config.credentials
            credentials = pika.credentials.PlainCredentials(user, password)
            parameters = pika.ConnectionParameters(host=url, port=int(port), credentials=credentials,
                                                   virtual_host=quote(config.vhost, safe=""))
            self.connection = pika.BlockingConnection(parameters)
            logger.debug('connected to to VCC message broker')
        except pika.exceptions.AMQPConnectionError as err:
            logger.debug(f'Could not connect to VCC message broker')
            raise RMQclientException(f'Could not connect {str(err)}')
        except Exception as err:
            logger.debug(f'Could not connect to VCC message broker')
            raise RMQclientException(f'Could not connect {str(err)}')

    # Connect to consumer channel
    def open_consumer(self):
        try:
            if not self.consumer or self.consumer.is_closed:
                self.consumer = self.connection.channel()
        except pika.exceptions.AMQPConnectionError as err:
            raise RMQclientException(f'Could not connect to consumer channel {str(err)}')

    # Connect to publisher channel
    def open_publisher(self):
        try:
            if not self.publisher or self.publisher.is_closed:
                self.publisher = self.connection.channel()
        except pika.exceptions.AMQPConnectionError as err:
            raise RMQclientException(f'Could not connect to publisher channel {str(err)}')

    @staticmethod
    def close_it(item):
        try:
            item.close()
        finally:
            return None

    # Close all connection
    def close(self):
        self.close_requested = True
        # Close all connections
        logger.debug(f'close rmq connections {self.id}')
        [self.close_it(item) for item in [self.publisher, self.connection] if item]
        self.publisher = self.consumer = self.connection = None

    # Thread safe function to send message
    def send(self, sender, code, key, data, reply_to='', priority=0, ttl=None, to_queue=False):
        logger.debug(f'send : {code} {key}')
        cb = functools.partial(self._send, sender, code, key, data, reply_to, priority, ttl, to_queue)
        self.connection.add_callback_threadsafe(cb)

    def _send(self, sender, code, key, data, reply_to='', priority=0, ttl=None, to_queue=False):
        self.open_publisher()

        conn = self.connection.is_closed if self.connection else "NULL"
        chn = self.publisher.is_closed if self.publisher else "NULL"
        logger.debug(f'_send : {code} {key} CONN {conn} CHANNEl {chn}')
        # Detect format message
        fmt, msg = ('text', data) if isinstance(data, str) else ('json', json.dumps(data, default=json_encoder))

        headers = {'type': 'vlbi', 'sender': sender, 'code': code, 'format': fmt, 'utc': datetime.utcnow().isoformat()}
        properties = {'delivery_mode': 2, 'priority': priority, 'reply_to': reply_to, 'headers': headers,
                      'expiration': str(ttl) if ttl else None}

        try:
            exchange = '' if to_queue else self.exchange
            self.publisher.basic_publish(exchange, key, msg, pika.BasicProperties(**properties))
            logger.debug(f'sent {exchange} {key}')
        except (pika.exceptions.ChannelWrongStateError, pika.exceptions.StreamLostError) as err:
            raise RMQclientException(f'publisher channel error{str(err)}')

    # Send a ping to specific target
    def ping(self, target, to_queue=False, need_reply=False):
        return self.send(self.queue, 'ping', target, 'request status', priority=5, ttl=self.ttl,
                         to_queue=to_queue, reply_to=self.queue if need_reply else '')

    # Reply to ping
    def pong(self, sender, target, status):
        return self.send(sender, 'pong', target, {'status': status}, priority=5, ttl=self.ttl, to_queue=True)

    # Generic function doing nothing with message
    def do_nothing(self, properties, body):
        logger.debug('DO NOTHING')

    def cancel(self):
        self.abord()
        raise RMQclientException('terminate')

    def abord(self):
        try:
            self.consumer.basic_cancel(self.consumer_tag)
            self.close()
        except:
            pass

    # Connect to queue and wait for message
    def monit(self, process_fnc, timeout_fnc=None, timeout=300):
        self.process_msg, self.process_timeout, self.timeout = process_fnc, timeout_fnc, timeout
        self.open_consumer()

        try:
            if self.process_timeout:
                self.timeout_id = self.connection.call_later(self.timeout, self.on_timeout)
            logger.debug('basic_consume')
            self.consumer.add_on_cancel_callback(self.close)
            self.consumer.basic_qos(prefetch_count=1)
            on_message_callback = functools.partial(self.new_msg)
            self.consumer.basic_consume(queue=self.queue, on_message_callback=on_message_callback, auto_ack=False)
            self.consumer_tag = self.consumer.consumer_tags[0]

            logger.debug('start consumer')
            self.consumer.start_consuming()
        except (pika.exceptions.ConnectionClosedByBroker, pika.exceptions.ConnectionClosed,
                pika.exceptions.AMQPError, pika.exceptions.StreamLostError, Exception) as err:
            raise RMQclientException(f'Monit connection lost {str(err)}')

    def new_msg(self, ch, method, properties, body):
        logger.debug(f'MSG {method.delivery_tag}')
        self._last_msg = (ch, method)
        logger.debug(f'new_msg {properties.headers} {body}')
        if properties.headers.get('type', 'unknown') == 'vlbi':  # Valid VLBI message
            if self.process_timeout:
                self.reset_timeout()
            self.process_msg(properties.headers, body)
        else:
            logger.debug('Acknowledge bad message')
            self.acknowledge_msg()

    def keep_connection_alive(self):
        try:
            if (datetime.now() - self.last_data_events).total_seconds() > 30:
                self.last_data_events = datetime.now()
                self.connection.process_data_events()
        except pika.exceptions.AMQPConnectionError as err:
            raise RMQclientException(f'keep_connection_alive {str(err)}')

    def on_timeout(self):
        cb = functools.partial(self._on_timeout)
        self.connection.add_callback_threadsafe(cb)

    def _on_timeout(self):
        try:
            self.timeout_id = self.connection.call_later(self.timeout, self.on_timeout)
            self.process_timeout()
        except Exception as e:
            logger.debug(f'ON TIMEOUT {str(e)}')

    def reset_timeout(self):
        cb = functools.partial(self._reset_timeout)
        self.connection.add_callback_threadsafe(cb)

    def _reset_timeout(self):
        try:
            self.connection.remove_timeout(self.timeout_id)
            self.timeout_id = self.connection.call_later(self.timeout, self.on_timeout)
        except Exception as e:
            logger.debug(f'RESET TIMEOUT {str(e)}')

    # Internal function to ack message (thread safe)
    def acknowledge_msg(self):
        cb = functools.partial(self._acknowledge_msg)
        self.connection.add_callback_threadsafe(cb)

    # Accept last
    def _acknowledge_msg(self):
        try:
            ch, method = self._last_msg
            logger.debug(f'ACK {method.delivery_tag}')
            ch.basic_ack(method.delivery_tag)
        except Exception as ex:
            logger.debug(f'Could not ACK last message {str(ex)}')

    # Test that queue is alive
    def alive(self):
        # Ping same queue and read message
        self.ping(self.queue, to_queue=True)

        # Check is message is coming back (wait maximum time == self.ttl)
        self.open_consumer()
        start = datetime.now()
        try:
            while (datetime.now() - start).total_seconds() * 1000 < self.ttl:
                method, props, body = self.consumer.basic_get(self.queue)
                if method:
                    now = datetime.utcnow()
                    if props.headers.get('code', '') == 'ping':
                        dt = now - datetime.fromisoformat(props.headers['utc'])
                        self.consumer.basic_ack(method.delivery_tag)  # ACK message
                        self.close()
                        return dt.total_seconds()
                    else:  # Not the right message
                        self.consumer.basic_reject(method.delivery_tag)
        except (pika.exceptions.ConnectionClosedByBroker, pika.exceptions.ConnectionClosed,
                pika.exceptions.AMQPError, Exception) as err:
            raise RMQclientException(f'Test alive failed{str(err)}')
        raise RMQclientException(f'No answer after {int(self.ttl/1000)} seconds')

    def get(self, process_fnc):
        self.process_msg = process_fnc
        process = functools.partial(self.new_msg)
        # Check is message is coming back (wait maximum time == self.ttl)
        self.open_consumer()
        try:
            while True:
                method, properties, body = self.consumer.basic_get(self.queue)
                process(self.consumer, method, properties, body)
            self.close()
        except (pika.exceptions.ConnectionClosedByBroker, pika.exceptions.ConnectionClosed,
                pika.exceptions.AMQPError, Exception) as err:
            raise RMQclientException(f'get inbox messages failed{str(err)}')


