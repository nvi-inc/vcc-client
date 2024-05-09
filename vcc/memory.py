from functools import wraps
from multiprocessing import Lock

_lock = Lock()


def lock(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        _lock.acquire()
        try:
            return func(*args, **kwargs)
        finally:
            _lock.release()

    return wrapper


