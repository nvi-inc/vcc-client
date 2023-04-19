import os
import time
import gzip
import logging
import logging.handlers
from pathlib import Path
import signal

from datetime import date, datetime
from base64 import urlsafe_b64encode as b64e, urlsafe_b64decode as b64d
from psutil import Process, process_iter

from cryptography.fernet import Fernet
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

groups = {'CC', 'NS', 'OC', 'AC', 'CO', 'DB'}


# Error with VCC problems
class VCCError(Exception):
    def __init__(self, err_msg):
        self.err_msg = err_msg


# Make sure folder is full path
def make_path(folder, filename):
    return os.path.join(os.path.expanduser(folder), filename)


# Change a iso format string to datetime. Return string if not datetime
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


def _derive_key(password: bytes, salt: bytes, iterations: int) -> bytes:
    """Derive a secret key from a given password and salt"""
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
        folder = os.path.dirname(name)
        return os.path.join(folder, datetime.utcnow().strftime(f'{prefix}%Y-%m-%d.%H%M%S.gz'))

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



def get_process(name):
    my_pid = os.getpid()
    for prc in process_iter(attrs=['pid', 'name', 'cmdline']):
        if prc.info['cmdline'] and name in prc.info['cmdline'] and prc.info['pid'] != my_pid:
            return prc
    return None


# Stop VCCN monitoring application
def stop_process(name, verbose=True):
    prc = get_process(name)
    if prc:
        try:
            Process(prc.info['pid']).send_signal(signal.SIGTERM)
            while True:
                time.sleep(1)
                prc = get_process(name)
                if prc:
                    Process(prc.info['pid']).send_signal(signal.SIGKILL)
            if verbose:
                print(f'Successfully killed \"vccns\" process {prc.info["pid"]}')
        except Exception as err:
            if verbose:
                print(f'Failed trying to kill \"vccns\" process {prc.info["pid"]}. [{str(err)}]')
            return False
    elif verbose:
        print(f'{name} is not running')
    return True




