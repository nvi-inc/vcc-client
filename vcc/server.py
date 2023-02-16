import requests
import logging
import logging.handlers

import toml
import pkg_resources
from io import StringIO

from Crypto.Cipher import PKCS1_OAEP, AES
from paramiko import RSAKey


from sshtunnel import SSHTunnelForwarder, BaseSSHTunnelForwarderError, HandlerSSHTunnelForwarderError
from urllib.parse import urljoin

from vcc import make_object, settings, signature, json_encoder, VCCError
from vcc.messaging import RMQclient, RMQclientException

logger = logging.getLogger('vcc')


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
            rsp = self.session.get(url=urljoin(self.base_url, path), params=params, headers=headers, timeout=timeout)
            self.jwt_data = signature.validate(rsp) if rsp and path != '/' else None
            return rsp
        except requests.exceptions.ConnectionError:
            raise VCCError('connect error')

    # POST data to web service
    def post(self, path, data=None, files=None, headers=None):
        try:
            rsp = self.session.post(url=urljoin(self.base_url, path), json=json_encoder(data), files=files,
                                    headers=headers)
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
    def __init__(self, group_id):
        self.group_id = group_id
        # Initialize communication parameters
        self.base_url = self.url = self.protocol = None
        self.api_port, self.msg_port = 0, 0
        self.name = ''
        # Initialized tunnels
        self.tunnel = None
        self.connect()  # Connect to VCC server

    # Enter function when 'with' is used
    def __enter__(self):
        return self

    # Exit function when 'with' is used
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

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

    # Get first available VWS client
    def connect(self):
        # Get list of VLBI Communications Center (VCC)
        for name, config in get_server(self.group_id):
            self.url, self.protocol = config.url, config.protocol
            self.api_port, self.msg_port = config.api_port, config.msg_port
            if getattr(config, 'tunnel', None):
                try:
                    self.name, self.tunnel = self.start_tunnel(name, config)
                except (BaseSSHTunnelForwarderError, HandlerSSHTunnelForwarderError) as exc:
                    continue

            # Test VCC API can be reached
            if self.is_available:
                return

        self.close()
        raise VCCError('cannot connect to any VCC')

    # Make sure tunnel is close when instance is destroyed
    def __del__(self):
        self.close()

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
            logger.debug(f'vcc available {str(exc)}')
            return False

    # Stop/Close all connections
    def close(self):
        try:
            if self.tunnel:
                self.tunnel.stop()
        finally:
            self.tunnel = None

    def get_api(self):
        return API(self.group_id, self.config)

    # Get RMQclient
    def get_rmq_client(self, ses_id=None, is_multi_thread=False):
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


def get_server(group_id):
    info = signature.check(group_id)
    f = pkg_resources.resource_stream(__name__, 'data/sv.bin')
    parts = [f.read(x) for x in [16, 16, -1]]
    cip = AES.new(info, AES.MODE_EAX, parts[1])
    for name, config in toml.loads(cip.decrypt_and_verify(parts[2], parts[0]).decode('utf-8')).items():
        name = name.lower()
        config['key'] = settings.RSAkey.path
        config['url'] = getattr(settings.URL, name, config['url']) if hasattr(settings, 'URL') else config['url']
        yield name, make_object(config)
