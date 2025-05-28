import gzip
import logging
import logging.handlers
import os
import sys
import platform
from base64 import urlsafe_b64decode as b64d
from base64 import urlsafe_b64encode as b64e
from datetime import date, datetime
from pathlib import Path
from subprocess import Popen, PIPE
import hashlib

import toml
from cryptography.fernet import Fernet
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

vcc_groups = {'CC': 'Coordinating Center', 'OC': "Operations Center", 'AC': 'Analysis Center',
              'CO': 'Correlator', 'NS': 'Network Station', 'DB': 'Dashboard'}


# Error with VCC problems
class VCCError(Exception):
    def __init__(self, err_msg):
        self.err_msg = err_msg


# Make sure folder is full path
def make_path(folder, filename):
    return Path(Path(folder).expanduser(), filename)


# Change iso format string to datetime. Return string if not datetime
def decode_obj(val):
    try:
        return datetime.fromisoformat(val)
    except (ValueError, TypeError):
        return val


# Change dictionary to attribute of a class
def make_object(data, cls=None, index=0):
    # Use empty Obj class if one is not provided
    cls = cls if cls else type('Obj', (), {})()

    # Set attribute of the class
    for key, value in data.items():
        if isinstance(value, dict):
            setattr(cls, key, make_object(value, index=index+1))
        elif isinstance(value, list):
            setattr(cls, key, [decode_obj(val) for val in value])
        else:
            setattr(cls, key, decode_obj(value))
    return cls


# Update object using dictionary
def update_object(root, dict_name, info):
    if not hasattr(root, dict_name):
        setattr(root, dict_name, make_object(info))
    else:
        main_obj = getattr(root, dict_name)
        for name, elements in info.items():
            if not hasattr(main_obj, name):
                setattr(main_obj, name, make_object(elements) if isinstance(elements, dict) else decode_obj(elements))
            elif isinstance(elements, dict):
                update_object(main_obj, name, elements)


# Encode date and datetime object in special dict object
def json_encoder(obj):
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {name: json_encoder(item) for name, item in obj.items()}
    if isinstance(obj, list):
        return [json_encoder(item) for item in obj]
    return obj


# Decode date and datetime object in string with isoformat
def json_decoder(obj):
    try:
        return datetime.fromisoformat(obj)
    except:
        if isinstance(obj, dict):
            return {name: json_decoder(item) for name, item in obj.items()}
        if isinstance(obj, list):
            return [json_decoder(item) for item in obj]
    return obj


backend = default_backend()


# Derive a secret key from a given password and salt"""
def _derive_key(password: bytes, salt: bytes, iterations: int) -> bytes:
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=iterations, backend=backend)
    return b64e(kdf.derive(password))


def decrypt(token: bytes, password: str) -> bytes:
    decoded = b64d(token)
    salt, iterations, token = decoded[:16], int.from_bytes(decoded[16:20], 'big'), b64e(decoded[20:])
    key = _derive_key(password.encode(), salt, iterations)
    return Fernet(key).decrypt(token)


# Custom filter use to format records
class ContextFilter(logging.Filter):
    def filter(self, record):
        setattr(record, 'utc', datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3])
        return True


# Custom filter to output only DEBUG messages on console
class DebugFilter(logging.Filter):
    def filter(self, record):
        return record.levelno <= logging.DEBUG


# Set default logger
def set_logger(log_path='', prefix='', console=False, size=1000000):
    # Functions needed to provide name of new compress file
    def namer(name):
        folder = Path(name).parent
        return Path(folder, datetime.utcnow().strftime(f'{prefix}%Y-%m-%d.%H%M%S.gz'))

    # Functions needed to created file rotator with gzip compression
    def rotator(source, destination):
        with open(source, "rb") as sf, open(destination, "wb") as df:
            df.write(gzip.compress(sf.read(), 9))
        os.remove(source)

    logger = logging.getLogger('vcc')
    logger.setLevel(logging.DEBUG)
    logger.addFilter(ContextFilter())
    formatter = logging.Formatter('%(utc)s - %(levelname)s - %(message)s')
    # Add File handler
    if log_path and Path(log_path).parent.exists():
        fh = logging.handlers.RotatingFileHandler(log_path, 'a', size, 1)
        fh.setLevel(logging.INFO)
        fh.setFormatter(formatter)
        fh.rotator = rotator
        fh.namer = namer
        logger.addHandler(fh)
    # Add console filter
    if console:
        ch = logging.StreamHandler()
        ch.setLevel(logging.DEBUG)
        ch.setFormatter(formatter)
        logger.addHandler(ch)
    return logger


def get_config_data(config):
    if (path := Path(config)).exists():
        try:
            return toml.load(path.open())
        except toml.TomlDecodeError as exc:
            print(f'Error reading {path} [{str(exc)}]')
            exit(0)
    return {}


def get_ns_code(config):
    if data := get_config_data(config):
        return data.get('Signatures', {}).get('NS', [None, None])[0]
    return None


def vcc_cmd(action, options, user=None, group=None):
    cmd = str(Path(Path(sys.argv[0]).parent, action))
    if platform.system() == "Windows":
        cmd = cmd.replace('\\', '\\\\')
    logger = logging.getLogger('vcc')
    logger.info(f'command [{cmd}] {options}')

    # Use popen so that thread is not blocked by window message
    Popen([f'{cmd} {options}'], user=user, group=group, shell=True,
          stdin=None, stdout=None, stderr=None, close_fds=True)


def vcc_cmd_r(action, options, user=None, group=None):
    cmd = str(Path(Path(sys.argv[0]).parent, action))
    if platform.system() == "Windows":
        cmd = cmd.replace('\\', '\\\\')
    logger = logging.getLogger('vcc')
    logger.info(f'command [{cmd}] {options}')

    # Use popen so that thread is not blocked by window message
    prc = Popen([f'{cmd} {options}'], user=user, group=group, shell=True, stdin=None, stdout=PIPE,
                stderr=PIPE, close_fds=True)
    return prc.communicate()


# Output VCC package version
def show_version():
    from importlib import metadata
    print(metadata.version("vcc"))
    sys.exit(0)

def help(subject):
    import pkg_resources  # part of setuptools
    subjects = toml.load(open(pkg_resources.resource_filename(__name__, f'help/vcc.toml')))
    title, *lines = subjects['vcc']['text']
    message = '<br>'.join(lines)

    vcc_cmd('message-box', f'-t "{title}" -m "{message}" -i "info"')


def message_box(title, msg, icon):
    message = '<br>'.join(msg.splitlines())
    vcc_cmd('message-box', f'-t "{title}" -m "{message}" -i "{icon}"')


def get_md5sum(path, chunk_size=32768):

    md5 = hashlib.md5()
    with open(path, 'rb') as file:
        while True:
            chunk = file.read(chunk_size)
            if not chunk:
                break
            md5.update(chunk)
    return md5.hexdigest()
