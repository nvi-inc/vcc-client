import functools
import json
import logging
import logging.handlers
import uuid
import jwt
import time
import functools

from base64 import b64decode
from urllib.parse import quote, urljoin
from cryptography.hazmat.primitives import serialization

from datetime import datetime

import requests
import toml
from Crypto.Cipher import AES
from sshtunnel import (BaseSSHTunnelForwarderError,
                       HandlerSSHTunnelForwarderError, SSHTunnelForwarder)

from vcc import (VCCError, json_encoder, make_object, settings, vcc_groups)

logger = logging.getLogger('vcc')


def http_retry(max_attempts=3, delay=0.1):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(self, *args, **kwargs):
            attempts = 0
            while attempts < max_attempts:
                try:
                    return func(self, *args, **kwargs)
                except requests.exceptions.ConnectionError as exc:
                    attempts += 1
                    self.http_session = requests.session()  # reset Session
                    time.sleep(delay)
            raise VCCError('connection error')

        return wrapper
    return decorator


def load_private_key():
    with open(settings.RSAkey.path, 'rb') as f:
        return serialization.load_ssh_private_key(f.read(), password=None)


def validate_group(group_id):
    if not group_id:
        for group_id in vcc_groups:
            if hasattr(settings.Signatures, group_id):
                break
        else:
            raise VCCError('No valid groups in configuration file')
    if not (info := getattr(settings.Signatures, group_id)):
        raise VCCError(f'{group_id} is not a valid group')
    return group_id, info[0], info[1]


# Class to connect to VCC Web Service
class VCC:
    def __init__(self, group_id=None):
        self.group_id, self.code, self.uid = validate_group(group_id)
        # Initialize communication parameters
        self.base_url = self.url = self.protocol = None
        self.name, self.tunnel, self.port = '', None, 0
        self.http_session = None

        self.secret_key = str(uuid.uuid4())
        self.private_key = load_private_key()
        self.jwt_data = None

    # Enter function when 'with' is used
    def __enter__(self):
        self.connect()
        return self

    # Exit function when 'with' is used
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def make_signature(self, exp=120, data=None):
        required = {'code': self.code, 'group': self.group_id, 'secret': self.secret_key, 'exp': time.time() + exp}
        data = dict(**data, **required) if data else required
        return {'token': jwt.encode(data, self.private_key, algorithm='RS256', headers={'uid': self.uid}),
                'utc': datetime.utcnow().isoformat()}

    def validate_signature(self, rsp):
        if not rsp or not (token := rsp.headers.get('token')):
            self.jwt_data = None
        elif not (headers := jwt.get_unverified_header(token)) or headers.get('uid') != self.uid:
            raise VCCError('Invalid token')
        else:
            try:
                self.jwt_data = jwt.decode(token, self.secret_key, algorithms=headers['alg'])
            except (jwt.exceptions.ExpiredSignatureError, jwt.exceptions.InvalidSignatureError) as exc:
                raise VCCError(f'Invalid token {str(exc)}')
        return rsp

    def start_tunnel(self, name, config, test=False):
        if name == self.name and self.tunnel:
            self.tunnel.check_tunnels()
            if not self.tunnel.tunnel_is_up:
                self.tunnel.restart()
            return self.name, self.tunnel
        tunnel = SSHTunnelForwarder(config.url, ssh_username=config.tunnel, ssh_pkey=config.key,
                                    remote_bind_address=('localhost', config.port))
        tunnel.daemon_forward_servers = True
        tunnel.start()
        self.url, self.port = 'localhost', tunnel.local_bind_port
        if test:
            tunnel.check_tunnels()

        return name, tunnel

    def tunnel_is_up(self):
        if not self.tunnel:
            return False
        self.tunnel.check_tunnels()
        return all(list(self.tunnel.tunnel_is_up.values()))

    # Get first available VWS client
    def connect(self):
        logger.debug('connecting')
        # Get list of VLBI Communications Center (VCC)
        for name, config in get_server():
            self.url, self.protocol, self.port = config.url, config.protocol, config.port
            if getattr(config, 'tunnel', None):
                logger.debug('tunnel start')
                try:
                    self.name, self.tunnel = self.start_tunnel(name, config)
                except (BaseSSHTunnelForwarderError, HandlerSSHTunnelForwarderError):
                    logger.debug('tunnel problem')
                    continue
            # Init http session
            self.http_session = requests.Session()
            self.base_url = f'{self.protocol}://{self.url}:{self.port}'
            # Test VCC API can be reached
            if self.is_available:
                return

        self.close()
        raise VCCError('cannot connect to any VCC')

    def close(self):
        try:
            if self.tunnel:
                self.tunnel.stop()
            if self.http_session:
                self.http_session.close()
        finally:
            self.tunnel = self.http_session = None

    @property
    # Check if site is available by requesting a welcome message
    def is_available(self):
        try:
            if not self.http_session:
                self.connect()
            rsp = self.get('/', timeout=5)  # Not more than 5 seconds to look for vcc
            return 'Welcome to VLBI Communications Center' in rsp.text if rsp else False
        except Exception as exc:
            pass
        return False

    # GET data from web service
    @http_retry()
    def get(self, path, params=None, headers=None, timeout=None):
        headers = dict(**(headers or {}), **self.make_signature())
        rsp = self.http_session.get(url=urljoin(self.base_url, path), params=params, headers=headers, timeout=timeout)
        return rsp if path == '/' else self.validate_signature(rsp)

    # POST data to web service
    @http_retry()
    def post(self, path, data=None, files=None, headers=None, params=None):
        headers = dict(**(headers or {}), **self.make_signature())
        rsp = self.http_session.post(url=urljoin(self.base_url, path), json=json_encoder(data), files=files,
                                     params=params, headers=headers)
        return self.validate_signature(rsp)

    # PUT data to web service
    @http_retry()
    def put(self, path, data=None, files=None, headers=None):
        headers = dict(**(headers or {}), **self.make_signature())
        rsp = self.http_session.put(url=urljoin(self.base_url, path), json=json_encoder(data), files=files,
                                    headers=headers)
        return self.validate_signature(rsp)

    # DELETE data from web service
    @http_retry()
    def delete(self, path, headers=None):
        headers = dict(**(headers or {}), **self.make_signature())
        rsp = self.http_session.delete(url=urljoin(self.base_url, path), headers=headers)
        return self.validate_signature(rsp)

    def copy(self):
        second = VCC(self.group_id)
        second.tunnel, second.protocol, second.url, second.port = self.tunnel, self.protocol, self.url, self.port
        second.http_session = requests.Session()
        second.base_url = f'{second.protocol}://{second.url}:{second.port}'
        return second


def get_server():
    def _decode(item):
        try:
            key, val = item.split(':')
            try:
                return key, int(val)
            except ValueError:
                return key, val
        except ValueError:
            raise VCCError('cannot find any VCC in config file')

    for name, info in settings.Servers.__dict__.items():
        config = dict([_decode(item) for item in info.split(',')]+[('key', settings.RSAkey.path)])
        yield name.lower(), make_object(config)
