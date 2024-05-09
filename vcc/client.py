import functools
import json
import logging
import logging.handlers
import uuid
from base64 import b64decode
from datetime import date, datetime
from urllib.parse import quote, urljoin

import pika
import requests
import toml
from Crypto.Cipher import AES
from sshtunnel import (BaseSSHTunnelForwarderError,
                       HandlerSSHTunnelForwarderError, SSHTunnelForwarder)

from vcc import (VCCError, json_encoder, make_object, settings, signature,
                 vcc_groups)

logger = logging.getLogger('vcc')


# Define RMQclientException
class RMQclientException(Exception):
    def __init__(self, err_msg):
        self.err_msg = err_msg


class API:
    def __init__(self, group_id, config):
        self.base_url = f'{config["protocol"]}://{config["url"]}:{config["api_port"]}'
        self.session = requests.Session()
        self.session.headers.update(signature.make(group_id))
        self.jwt_data = None


    def close(self):
        try:
            if self.session:
                self.session.close()
        finally:
            self.session = None

    # GET data from web service
    def get(self, path, params=None, headers=None, timeout=None):
        try:
            extra = {'utc': datetime.utcnow().isoformat()}
            headers = dict(**headers, **extra) if headers else extra
            rsp = self.session.get(url=urljoin(self.base_url, path), params=params, headers=headers, timeout=timeout)
            self.jwt_data = signature.validate(rsp) if rsp and path != '/' else None
            return rsp
        except requests.exceptions.ConnectionError as exc:
            logging.debug(str(exc))
            raise VCCError(f'connect error')

    # POST data to web service
    def post(self, path, data=None, files=None, headers=None, params=None):
        try:
            extra = {'utc': datetime.utcnow().isoformat()}
            headers = dict(**headers, **extra) if headers else extra
            rsp = self.session.post(url=urljoin(self.base_url, path), json=json_encoder(data), files=files,
                                    params=params, headers=headers)
            self.jwt_data = signature.validate(rsp) if rsp else None
            return rsp
        except requests.exceptions.ConnectionError:
            raise VCCError('connect error')

    # PUT data to web service
    def put(self, path, data=None, files=None, headers=None):
        try:
            extra = {'utc': datetime.utcnow().isoformat()}
            headers = dict(**headers, **extra) if headers else extra
            rsp = self.session.put(url=urljoin(self.base_url, path), json=json_encoder(data), files=files,
                                   headers=headers)
            self.jwt_data = signature.validate(rsp) if rsp else None
            return rsp
        except requests.exceptions.ConnectionError:
            raise VCCError('connect error')

    # DELETE data from web service
    def delete(self, path, headers=None):
        try:
            extra = {'utc': datetime.utcnow().isoformat()}
            headers = dict(**headers, **extra) if headers else extra
            rsp = self.session.delete(url=urljoin(self.base_url, path), headers=headers)
            self.jwt_data = signature.validate(rsp) if rsp else None

            return rsp
        except requests.exceptions.ConnectionError:
            raise VCCError('connect error')


# Class to connect to VCC Web Service
class VCC:
    def __init__(self, group_id=None):
        self.group_id = group_id if group_id else self.get_any_group_id()
        # Initialize communication parameters
        self.base_url = self.url = self.protocol = None
        self.api_port, self.msg_port = 0, 0
        self.name, self.tunnel = '', None
        self.api = None

    # Enter function when 'with' is used
    def __enter__(self):
        self.connect()
        return self

    # Exit function when 'with' is used
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    @staticmethod
    def get_any_group_id():
        for group_id in vcc_groups:
            if hasattr(settings.Signatures, group_id):
                return group_id
        else:
            raise VCCError('No valid groups in configuration file')

    def start_tunnel(self, name, config, test=False):
        if name == self.name and self.tunnel:
            self.tunnel.check_tunnels()
            if not self.tunnel.tunnel_is_up:
                self.tunnel.restart()
            return self.name, self.tunnel
        addresses = [('localhost', port) for port in [config.api_port, config.msg_port]]
        tunnel = SSHTunnelForwarder(config.url, ssh_username=config.tunnel, ssh_pkey=config.key,
                                    remote_bind_addresses=addresses)
        tunnel.daemon_forward_servers = True
        tunnel.start()
        self.url = 'localhost'
        self.api_port, self.msg_port = tunnel.local_bind_ports
        if test:
            logger.warning('start checking tunnel')
            tunnel.check_tunnels()
            logger.warning(f'end checking tunnel {tunnel.tunnel_is_up}')

        return name, tunnel

    def tunnel_is_up(self):
        if not self.tunnel:
            return False
        self.tunnel.check_tunnels()
        return all(list(self.tunnel.tunnel_is_up.values()))

    # Get first available VWS client
    def connect(self):
        # Get list of VLBI Communications Center (VCC)
        for name, config in get_server():
            self.url, self.protocol = config.url, config.protocol
            self.api_port, self.msg_port = config.api_port, config.msg_port
            if getattr(config, 'tunnel', None):
                try:
                    self.name, self.tunnel = self.start_tunnel(name, config)
                except (BaseSSHTunnelForwarderError, HandlerSSHTunnelForwarderError):
                    continue

            self.api = API(self.group_id, self.config)
            # Test VCC API can be reached
            if self.is_available:
                return

        self.close()
        raise VCCError('cannot connect to any VCC')

    @property
    def config(self):
        return {'url': self.url, 'protocol': self.protocol, 'api_port': self.api_port, 'msg_port': self.msg_port}

    @property
    # Check if site is available by requesting a welcome message
    def is_available(self):
        if not self.api:
            return False
        try:
            rsp = self.api.get('/', timeout=5)  # Not more than 5 seconds to look for web service
            return 'Welcome to VLBI Communications Center' in rsp.text if rsp else False
        except Exception as exc:
            logger.debug(f'vcc not available - {str(exc)}')
            return False

    # Stop/Close all connections
    def close(self):
        try:
            if self.tunnel:
                self.tunnel.stop()
                logger.debug('tunnel closed')
        finally:
            self.tunnel = None

    def get_api(self):
        return API(self.group_id, self.config)

    # Get RMQclient
    def get_rmq_client(self, ses_id=None, is_multi_thread=False):
        logger.debug('get_rmq_client')
        # Get credentials for RMQclient
        try:
            rsp = self.api.get('/users/inbox', headers={'session': ses_id})
            if rsp:  # Combined client config with information in signature
                try:
                    client = RMQclient(is_multi_thread=is_multi_thread)
                    client.connect(make_object(dict(**self.config, **self.api.jwt_data)))
                    logger.debug(f'get_rmq_client {client.connection.is_closed if client.connection else "NULL"}')
                    return client
                except RMQclientException as exc:
                    raise VCCError(f'Problem at VCC messenger {str(exc)}')
            raise VCCError(f'Problem at VCC api [{rsp.status_code}] [{rsp.text}]')
        except VCCError as exc:
            raise VCCError(str(exc))

    # Get RMQclient
    def get_rmq_connection(self, is_multi_thread=False):
        logger.debug('get_rmq_connection')
        # Get credentials for RMQclient
        try:
            rsp = self.api.get('/users/connection')
            if rsp:  # Combined client config with information in signature
                try:
                    client = RMQclient(is_multi_thread=is_multi_thread)
                    client.connect(make_object(dict(**self.config, **self.api.jwt_data)))
                    logger.debug(f'get_rmq_connection {client.connection.is_closed if client.connection else "NULL"}')
                    return client
                except RMQclientException as exc:
                    raise VCCError(f'Problem at VCC messenger {str(exc)}')
            raise VCCError(f'Problem at VCC api [{rsp.status_code}] [{rsp.text}]')
        except VCCError as exc:
            raise VCCError(str(exc))


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
            while all(rsp := self.consumer.basic_get(self.queue)):
                method, properties, body = rsp
                process(self.consumer, method, properties, body)
            self.close()
        except (pika.exceptions.ConnectionClosedByBroker, pika.exceptions.ConnectionClosed,
                pika.exceptions.AMQPError, Exception) as err:
            raise RMQclientException(f'get inbox messages failed{str(err)}')


def get_server():
    for name, encrypted in settings.Servers.__dict__.items():
        parts = [b64decode(bytes.fromhex(x)) for x in encrypted.split('-')]
        cipher = AES.new(parts[0], AES.MODE_EAX, parts[2])
        config = toml.loads(cipher.decrypt_and_verify(parts[3], parts[1]).decode('utf-8'))
        config['key'] = settings.RSAkey.path
        if hasattr(settings, 'URL'):
            config['url'] = getattr(settings.URL, name, getattr(settings.URL, name.lower(), config['url']))
        yield name.lower(), make_object(config)
