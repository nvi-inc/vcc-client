from vcc import settings, message_box
from vcc.client import VCC, VCCError
from vcc.session import Session


def test_read(vcc):
    if rsp := vcc.api.get(f'/messages/'):
        print(rsp.json())
    else:
        print(f'Problem reading inbox {rsp.text}')


def test_send(vcc):
    msg = {'station': 'Kk', 'status': 'r41160kk.log closed', 'session': 'r41160'}
    msg['code'], msg['key'] = 'sta_info', 'msg'
    print(msg)
    if rsp := vcc.api.post('/messages/', data=msg):
        print('message', rsp.json())
    else:
        print('error', rsp.text)


def main():

    import argparse

    parser = argparse.ArgumentParser(description='Upload log file', prog='fslog', add_help=False)
    parser.add_argument('-c', '--config', help='config file', required=False)
    parser.add_argument('-s', '--send', help='send message', action='store_true', required=False)
    parser.add_argument('code')

    args = settings.init(parser.parse_args())

    with VCC(args.code) as vcc:
        test_send(vcc) if args.send else test_read(vcc)


if __name__ == '__main__':
    import sys

    sys.exit(main())
