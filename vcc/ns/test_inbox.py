import sys
import psutil
import json

from datetime import datetime
from threading import Event

from collections import namedtuple
from vcc import vcc_cmd, vcc_cmd_r
from vcc.ns import get_displays
from vcc.socket import Client
from vcc import json_encoder

Addr = namedtuple('addr', 'ip port')


def get_port(display):
    for index, prc in enumerate(psutil.process_iter()):
        try:
            if prc.name() == 'inbox-wnd':
                param = prc.cmdline()
                print('prc display', param[param.index('-D') + 1].split(':')[-1])
                if param[param.index('-D') + 1] == display:
                    for conn in prc.net_connections():
                        print('conn', conn)
                        if conn.status == 'LISTEN':
                            print('get_port', Addr(*conn.laddr).port)
                            return Addr(*conn.laddr).port
        except (IndexError, Exception):
            pass
    print('get_port', None)
    return None


def start_inbox(display):
    ctl = '/usr2/control/vcc.ctl'
    options = f"-c '{ctl}' -D '{display}'"
    vcc_cmd('inbox-wnd', options, user='oper', group='rtx')
    for _ in range(5):
        if port := get_port(display):
            return port
        print('waiting for process', _)
        Event().wait(1)
    return None


def send(display, text):

    if (port := get_port(display)) or (port := start_inbox(display)):
        client = Client('127.0.0.1', port)
        headers = {'utc': datetime.utcnow(), 'code': 'urgent'}
        data = {'message': text, 'fr': 'OC-NASA'}
        client.send(json.dumps((headers, data), default=json_encoder).encode("utf-8"))
        return True
    return False


def test():
    for index, prc in enumerate(psutil.process_iter()):
        try:
            if (param := prc.cmdline())[1].endswith('inbox-wnd'):
                name = param[param.index('-D') + 1]
                for conn in prc.net_connections():
                    print('PRC', index, prc.pid, name, conn)
        except IndexError:
            pass
        except Exception as exc:
            pass


def main():

    import argparse
    import os

    parser = argparse.ArgumentParser(description='Display message')
    parser.add_argument('-s', '--start', action='store_true', required=False)
    parser.add_argument('-d', '--display', required=False)

    args = parser.parse_args()

    display = args.display if args.display else os.environ.get('DISPLAY')

    send(display, "This is a test")
    print('terminate')
    sys.exit()


if __name__ == '__main__':

    sys.exit(main())
