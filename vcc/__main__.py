#! /usr/bin/env python3

from vcc import settings
from vcc.utils import show_session, show_next
from vcc.picker import SessionPicker
from vcc.schedule import upload_schedule_files

masters = {None: None, 'all': 'all', 'std': 'standard', 'int': 'intensive'}


def main():
    import argparse

    parser = argparse.ArgumentParser(description='Access VCC functionalities')
    parser.add_argument('-c', '--config', help='config file', required=False)
    group = parser.add_mutually_exclusive_group(required=False)
    group.add_argument('-v', '--viewer', help='view upcoming sessions', choices=masters.keys(), required=False)
    group.add_argument('-s', '--sked', help='update VCC with sked files', nargs='+', required=False)
    parser.add_argument('param', help='station or session code', nargs='?')

    args, _ = parser.parse_known_args()

    args = settings.init(parser.parse_args())

    if args.viewer:
        SessionPicker(masters[args.viewer]).exec()
    elif args.sked:
        upload_schedule_files(args.sked) if settings.check_privilege('OC') else \
            print('Only an Operations Center can upload schedules')
    elif args.param:
        show_next(args.param) if len(args.param) == 2 else show_session(args.param)


if __name__ == '__main__':

    import sys
    sys.exit(main())
