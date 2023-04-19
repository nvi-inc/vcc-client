from datetime import datetime, timedelta
import json
from subprocess import Popen

from vcc import settings
from vcc.server import VCC
from vcc.utils import show_session, show_next, upload_schedule_files

masters = ['all', 'std', 'int']


def show_version():
    import pkg_resources  # part of setuptools
    print('vcc version', pkg_resources.require("vcc")[0].version)


def upcoming(sta_id=None, master='all', days=7):
    with VCC() as vcc:
        api = vcc.get_api()
        now = datetime.utcnow()
        if sta_id:
            title = f'List of upcoming sessions for {sta_id}'
            sessions = api.get(f'/sessions/next/{sta_id}', params={'days': days}).json()
        else:
            ses_type = dict(int='intensives ', std='24H ').get(master, '')
            title = f'List of upcoming {ses_type}sessions'
            today = datetime.utcnow().date()
            begin, end = today - timedelta(days=2), today + timedelta(days=days)
            rsp = api.get('/sessions', params={'begin': begin, 'end': end, 'master': master})
            sessions = [api.get(f'/sessions/{ses_id}').json() for ses_id in rsp.json()]

        sessions = [data for data in sessions if datetime.fromisoformat(data['start']) > now]
        message = json.dumps(sessions)
        cmd = f"vcc-message -s -db \'{title}\' \'{message}\'"
        Popen([cmd], shell=True, stdin=None, stdout=None, stderr=None, close_fds=True)


def main():
    import argparse

    parser = argparse.ArgumentParser(description='Access VCC functionalities')
    parser.add_argument('-c', '--config', help='config file', required=False)
    group = parser.add_mutually_exclusive_group(required=False)
    group.add_argument('-v', '--viewer', help='view upcoming sessions', choices=masters, required=False)
    group.add_argument('-V', '--version', help='display version', action='store_true', required=False)
    group.add_argument('-s', '--sked', help='update VCC with sked files', nargs='+', required=False)
    parser.add_argument('param', help='station or session code', nargs='?')

    args, _ = parser.parse_known_args()

    args = settings.init(parser.parse_args())

    if args.version:
        show_version()
    if args.viewer:
        upcoming(master=args.viewer)  # SessionPicker(args.viewer).exec()
    elif args.sked:
        upload_schedule_files(args.sked) if settings.check_privilege('OC') else \
            print('Only an Operations Center can upload schedules')
    elif args.param:
        show_next(args.param) if len(args.param) == 2 else show_session(args.param)
    else:
        upcoming(master='all')


if __name__ == '__main__':

    import sys
    sys.exit(main())
