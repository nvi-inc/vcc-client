import argparse
import sys
from pathlib import Path

from vcc import help, settings, show_version
from vcc.client import VCC
from vcc.dashboard import Dashboard
from vcc.downtime import downtime
from vcc.inbox import check_inbox
from vcc.master import master
from vcc.session import Session
from vcc.sumops import sumops
from vcc.urgent import VCCMessage
from vcc.users import test_users
from vcc.utils import (fetch_files, master_types, upload_schedule_files)
from vcc.tools import upcoming_sessions


# Output session information
def show_session(ses_id):
    with VCC() as vcc:
        if rsp := vcc.api.get(f'/sessions/{ses_id}'):
            print(Session(rsp.json()))
        else:
            print(f'Could not find information on {ses_id}')


# Add list of standard option to parser
def add_arguments(parser):
    parser.add_argument('-s', '--start', help='start date for first session', required=False)
    parser.add_argument('-e', '--end', help='end date for last session', required=False)
    parser.add_argument('-d', '--days', help='number of days', type=int, default=7, required=False)
    parser.add_argument('-D', '--display', help='display name', required=False)


# Generate a parser for list of sessions
def sessions_args():
    parser = argparse.ArgumentParser(description='Access VCC functionalities')
    parser.add_argument('-c', '--config', help='config file', required=False)
    add_arguments(parser)
    parser.add_argument('code', help='None or station code', nargs='?', default='')
    return parser.parse_args(filter_input())


# Generate a parser for specific session
def session_args():
    parser = argparse.ArgumentParser(description='Access VCC functionalities')
    parser.add_argument('-c', '--config', help='config file', required=False)
    parser.add_argument('code', help='Session code')
    return parser.parse_args(filter_input())


def filter_input():
    name = Path(sys.argv[0]).name
    param = [] if name == 'vcc' else [name]
    param.extend(sys.argv[1:])
    return param


def main():
    parser = argparse.ArgumentParser(description='Access VCC functionalities', exit_on_error=False)
    parser.add_argument('-c', '--config', help='config file', required=False)

    # Create subprocesses
    subparsers = parser.add_subparsers(dest='action')
    # VERSION and TEST subprocesses
    subparsers.add_parser('version', help='Get version of VCC package')
    subparsers.add_parser('test', help='Test if config file has valid signatures')
    # INBOX subprocess
    sub = subparsers.add_parser('inbox', help='Monitor or Read inbox for group')
    sub.add_argument('-r', '--read', help='read messages in inbox', action='store_true')
    sub.add_argument('group', help='group id of inbox', choices=['CC', 'OC', 'AC', 'CC', 'NS'], type=str.upper)
    # SKED subprocess
    sub = subparsers.add_parser('sked', help='Upload schedule files (Operations Center only)')
    sub.add_argument('-q', '--quiet', help='do not notify users', action='store_true')
    sub.add_argument('files', help='schedule files to upload', nargs='+')
    # FETCH subprocess
    sub = subparsers.add_parser('fetch', help='retrieve files')
    sub.add_argument('param', help='Session code or file name')
    # MASTER subprocess
    sub = subparsers.add_parser('master', help='Update master (Coordinating Center only)')
    sub.add_argument('-d', '--delete', help='delete the session', action='store_true', required=False)
    sub.add_argument('param', help='master file or session to modify')
    # DASHBOARD subprocess
    sub = subparsers.add_parser('dashboard', help='Use dashboard to monitor session')
    sub.add_argument('session', help='session code')
    # DOWNTIME subprocess
    sub = subparsers.add_parser('downtime', help='Use dashboard to monitor session')
    sub.add_argument('-r', '--report', help='output data in csv format', action='store_true')
    sub.add_argument('station', help='station code', nargs='?')
    # SUMOPS subprocess
    sub = subparsers.add_parser('sumops', help='Generate SUMOPS report')
    group = sub.add_mutually_exclusive_group()
    group.add_argument('-s', '--sked', help='skd schedule file', dest='schedule', required=False)
    group.add_argument('-v', '--vex', help='vex schedule file', dest='schedule', required=False)
    group.add_argument('-r', '--report', action='store_true', required=False)
    sub.add_argument('session', help='session code', nargs='?')
    sub.add_argument('station', help='station code', nargs='?')

    # HELP subprocess
    sub = subparsers.add_parser('help', help='VCC help')
    sub.add_argument('subject', help='subject', nargs='?', default='')
    # urgent subprocess
    sub = subparsers.add_parser('urgent', help='start urgent interface')

    # Session type subprocess
    for code, mtype in master_types.items():
        sub = subparsers.add_parser(code, help=f'Get list of {mtype} sessions')
        add_arguments(sub)
        sub.add_argument('station', help='None or station code', nargs='?', default='')
    # Main options
    add_arguments(parser)
    parser.add_argument('code', help='None or station code', nargs='?', default='')
    try:
        args = parser.parse_args(filter_input())
        settings.init(args)
        if args.action == 'version':  # Show version
            show_version()
        elif args.action == 'help':  # Help
            help(args.subject)
        elif args.action == 'test':  # Run VCC test for config file
            test_users()
        elif args.action == 'sked':  # Upload schedule file
            upload_schedule_files(args.files, notify=not args.quiet)
        elif args.action == 'master':
            master(args.param, args.delete) 
        elif args.action == 'dashboard':
            Dashboard(args.session).exec()
        elif args.action == 'sumops':
            sumops(args)
        elif args.action == 'fetch':
            fetch_files(args.param)
        elif args.action == 'urgent':
            VCCMessage().exec()
        elif args.action == 'inbox':
            check_inbox(args.group, args.read)
        elif args.action == 'downtime':
            downtime(args.station, args.report)
        elif args.action in master_types.keys():
            upcoming_sessions(args.action, args.station, args)
        else:
            upcoming_sessions('all', args.code, args)
    except argparse.ArgumentError:
        args = sessions_args()
        if len(args.code) not in (0, 2):
            settings.init(session_args())
            show_session(args.code)
        else:
            settings.init(args)
            upcoming_sessions('all', args.code, args)
    sys.exit(0)


if __name__ == '__main__':

    sys.exit(main())
