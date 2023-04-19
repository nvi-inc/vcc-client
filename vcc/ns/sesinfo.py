import json
import sys
import argparse
from datetime import datetime
import os
import traceback

from vcc.utils import settings, json_decoder
from vcc import VCCError
from vcc.server import VCC
from vcc.ns.schedend import SessionReport


class SessionInformation:

    session: str
    sta_id: str
    action: str = None
    vcc: VCC = None

    def __init__(self):
        parser = self.make_parser()
        parser.add_argument('action', choices=['missed', 'issue', 'warm', 'fmout-gps', 'gps-fmout', 'late'],
                            type=str.lower, nargs='?')

        settings.init(parser.parse_known_args()[0])
        self.action = settings.args.action

        if hasattr(settings.Signatures, 'NS'):
            self.sta_id = settings.Signatures.NS[0].capitalize()
        if self.action and not self.sta_id:
            print('Only station can execute this command')
            exit(sys.exit(0))

        self.vcc = VCC('NS')

    def test_session(self):
        self.session = settings.args.session
        try:
            rsp = self.vcc.get_api().get(f'/sessions/{self.session}')
            if not rsp:
                raise VCCError(json.loads(rsp.text).get('error', rsp.text))
            data = json_decoder(rsp.json())
            if self.sta_id not in data['included'] + data['removed']:
                raise VCCError(f'{self.sta_id} not in {self.session}')
            return True
        except VCCError as exc:
            print(str(exc))
            return False

    def send_msg(self, msg):
        rmq = self.vcc.get_rmq_connection()
        rmq.send(self.sta_id, 'sta_info', 'msg', msg)
        rmq.close()

    def process(self):

        if not self.action:
            if settings.args.summary:
                print(f'Summary for {self.session}{" " + self.sta_id if self.sta_id else ""}')
            else:
                SessionReport(self.session).exec()
        else:
            if self.action in {'fmout-gps', 'gps-fmout'}:
                values = self.process_fmout_gps()
            elif self.action in {'missed', 'issue'}:
                values = self.process_problem()
            else:
                values = getattr(self, f'process_{self.action}')()

            self.send_msg({'status': f'{self.action}:{",".join(values)}', 'session': self.session})

    def process_problem(self):
        parser = self.make_parser()
        parser.add_argument('first')
        parser.add_argument('last')
        parser.add_argument('comments', nargs='*')

        args = parser.parse_args()
        return [args.first, args.last, ' '.join(args.comments)]

    def process_warm(self):
        parser = self.make_parser()
        parser.add_argument('comments', nargs='*')

        args = parser.parse_args()
        return [" ".join(args.comments)]

    def process_late(self):
        parser = self.make_parser()
        parser.add_argument('time')
        parser.add_argument('comments', nargs='*')

        args = parser.parse_args()
        return [args.time, ' '.join(args.comments)]

    def process_fmout_gps(self):
        parser = self.make_parser()
        parser.add_argument('time', choices=['start', 'end'], type=str.lower)
        parser.add_argument('value', type=float)
        parser.add_argument('unit', choices=['sec', 'msec', 'usec'], type=str.lower, nargs='?', default='usec')

        # Do that for value with scientific exponent
        try:
            value, sys.argv[4] = float(sys.argv[4]), 0.0
        except ValueError:
            pass
        args = parser.parse_args()
        return [args.time, f'{value:.6E}', args.unit]

    def make_parser(self):
        parser = argparse.ArgumentParser(description='ses-info')
        parser.add_argument('-c', '--config', help='config file', required=False)
        parser.add_argument('-s', '--summary' , help='print summary', action='store_true')
        parser.add_argument('session', help='session code')
        if self.action:
            parser.add_argument('action', choices=[self.action], help=argparse.SUPPRESS, type=str.lower)
        return parser


def main():
    info = SessionInformation()
    if info.test_session():
        info.process()


if __name__ == '__main__':

    sys.exit(main())

