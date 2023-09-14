import requests
import traceback
import logging
import logging.handlers

import toml
import pkg_resources
from io import StringIO

from Crypto.Cipher import PKCS1_OAEP, AES
from base64 import b64decode, b64encode
from paramiko import RSAKey


from sshtunnel import SSHTunnelForwarder, BaseSSHTunnelForwarderError, HandlerSSHTunnelForwarderError
from urllib.parse import urljoin

from vcc import make_object, settings, signature, json_encoder, groups, VCCError
from vcc.messaging import RMQclient, RMQclientException

logger = logging.getLogger('vcc')


class API:
    def __init__(self, group_id, config):
        self.base_url = f'{config["protocol"]}://{config["url"]}:{config["api_port"]}'
        print(config)
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
            rsp = self.session.get(url=urljoin(self.base_url, path), params=params, headers=headers, timeout=timeout)
            self.jwt_data = signature.validate(rsp) if rsp and path != '/' else None
            return rsp
        except requests.exceptions.ConnectionError:
            raise VCCError('connect error')

    # POST data to web service
    def post(self, path, data=None, files=None, headers=None, params=None):
        try:
            rsp = self.session.post(url=urljoin(self.base_url, path), json=json_encoder(data), files=files,
                                    params=params, headers=headers)
            self.jwt_data = signature.validate(rsp) if rsp else None
            return rsp
        except requests.exceptions.ConnectionError:
            raise VCCError('connect error')

    # PUT data to web service
    def put(self, path, data=None, files=None, headers=None):
        try:
            rsp = self.session.put(url=urljoin(self.base_url, path), json=json_encoder(data), files=files,
                                   headers=headers)
            self.jwt_data = signature.validate(rsp) if rsp else None
            return rsp
        except requests.exceptions.ConnectionError:
            raise VCCError('connect error')

    # DELETE data from web service
    def delete(self, path, headers=None):
        try:
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

    # Enter function when 'with' is used
    def __enter__(self):
        return self

    # Exit function when 'with' is used
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    @staticmethod
    def get_any_group_id():
        for group_id in groups:
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
        try:
            rsp = self.get_api().get('/', timeout=5)  # Not more than 5 seconds to look for web service
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
            api = self.get_api()
            rsp = api.get('/users/inbox', headers={'session': ses_id})
            if rsp:  # Combined client config with information in signature
                try:
                    client = RMQclient(is_multi_thread=is_multi_thread)
                    client.connect(make_object(dict(**self.config, **api.jwt_data)))
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
            api = self.get_api()
            rsp = api.get('/users/connection')
            if rsp:  # Combined client config with information in signature
                try:
                    client = RMQclient(is_multi_thread=is_multi_thread)
                    client.connect(make_object(dict(**self.config, **api.jwt_data)))
                    logger.debug(f'get_rmq_connection {client.connection.is_closed if client.connection else "NULL"}')
                    return client
                except RMQclientException as exc:
                    raise VCCError(f'Problem at VCC messenger {str(exc)}')
            raise VCCError(f'Problem at VCC api [{rsp.status_code}] [{rsp.text}]')
        except VCCError as exc:
            raise VCCError(str(exc))


def get_server():
    for name, encrypted in settings.Servers.__dict__.items():
        parts = [b64decode(bytes.fromhex(x)) for x in encrypted.split('-')]
        cipher = AES.new(parts[0], AES.MODE_EAX, parts[2])
        config = toml.loads(cipher.decrypt_and_verify(parts[3], parts[1]).decode('utf-8'))
        config['key'] = settings.RSAkey.path
        if hasattr(settings, 'URL'):
            config['url'] = getattr(settings.URL, name, getattr(settings.URL, name.lower(), config['url']))
        yield name.lower(), make_object(config)
