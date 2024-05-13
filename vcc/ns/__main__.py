from vcc import settings
from vcc.utils import master_types
from vcc.tools import upcoming_sessions
from vcc.ns.download import download
from vcc.ns.drudg import drudg_it
from vcc.ns.onoff import onoff
from vcc.fslog import upload_log


def add_arguments(parser):
    parser.add_argument('-s', '--start', help='start date for first session', required=False)
    parser.add_argument('-e', '--end', help='end date for last session', required=False)
    parser.add_argument('-d', '--days', help='number of days', type=int, default=7, required=False)
    parser.add_argument('-D', '--display', help='display name', required=False)


def sub_parser(parsers, name, help=''):
    sub = parsers.add_parser(name, help=help)
    sub.add_argument('-c', '--config', help='config file', required=False)
    return sub


def main():
    import argparse

    parser = argparse.ArgumentParser(description='Access VCC Network Station functionalities', exit_on_error=False)
    parser.add_argument('-c', '--config', help='config file', required=False)

    # Create subprocesses
    subparsers = parser.add_subparsers(dest='action')
    # DRUDG subprocess
    sub = sub_parser(subparsers, 'drudg', help='Run DRUDG')
    sub.add_argument('-v', '--vex', help='use vex file', action='store_true', required=False)
    sub.add_argument('session', help='session code')
    # LOG subprocess
    sub = sub_parser(subparsers, 'log', help='Upload log file)')
    sub.add_argument('-q', '--quiet', help='quiet mode', action='store_true', required=False)
    sub.add_argument('session', help='session of log')
    # ONOFF subprocess
    sub = sub_parser(subparsers, 'onoff', help='Upload ONOFF values from logfile)')
    sub.add_argument('path', help='path to log')
    # SKD subprocess
    sub = sub_parser(subparsers, 'skd', help='Download skd session file')
    sub.add_argument('session', help='session code')
    # vex subprocess
    sub = sub_parser(subparsers, 'vex', help='Download vex session file')
    sub.add_argument('session', help='session code')
    # PRC subprocess
    sub = sub_parser(subparsers, 'prc', help='Download prc session file')
    sub.add_argument('session', help='session code')
    # Session type subprocess
    for code, mtype in master_types.items():
        sub = sub_parser(subparsers, code, help=f'Get list of {mtype} sessions')
        add_arguments(sub)
    # Main options
    add_arguments(parser)

    try:
        args = settings.init(parser.parse_args())
        if not (sta_id := settings.get_user_code('NS')):
            print('Only Network Station can run this application')
        elif args.action == 'drudg':
            drudg_it(args.session, args.vex)
        elif args.action == 'log':
            upload_log(args.session, args.quiet)
        elif args.action == 'onoff':
            onoff(args.path)
        elif args.action in ['skd', 'vex', 'prc']:
            download(args.action, args.session, sta_id)
        else:
            upcoming_sessions(args.action, sta_id, args)
    except argparse.ArgumentError as exc:
        print('Unexpected argument error\n', str(exc))


if __name__ == '__main__':
    import sys

    sys.exit(main())
