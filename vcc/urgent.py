import sys

from vcc import settings
from vcc.server import VCC, VCCError


def send_message(user_group, message, targets):
    targets = targets if targets else [('all', 'urgent')]
    data = {'message': message, 'targets': targets}

    try:
        with VCC(user_group) as vcc:
            rsp = vcc.get_api().post('/messages/urgent', data=data)
            print(rsp.json().capitalize() if rsp else rsp.text)
    except VCCError as exc:
        print(f'Failed uploading urgent message [{str(exc)}]')


def main():
    import argparse

    parser = argparse.ArgumentParser(description='Urgent message')
    parser.add_argument('-c', '--config', help='config file', required=False)
    parser.add_argument('group', choices=['CC', 'AC', 'CO', 'OC', 'NS'], type=str.upper)
    parser.add_argument('-OC', '--OC', help='operations center', type=str.upper, required=False)
    parser.add_argument('-CO', '--CO', help='correlator', type=str.upper, required=False)
    parser.add_argument('-AC', '--AC', help='analysis center', type=str.upper, required=False)
    parser.add_argument('-CC', '--CC', help='coordinating center', type=str.upper, required=False)
    parser.add_argument('-NS', '--NS', help='network station', type=str.capitalize, required=False)
    parser.add_argument('-s', '--session', help='session', type=str.lower, required=False)
    parser.add_argument('message', nargs='*')

    args = settings.init(parser.parse_args())

    if not hasattr(settings.Signatures, args.group):
        print(f'{args.group} is not in your list of Signatures')
    else:
        message = ' '.join(args.message)
        if args.session:
            send_message(args.group, message, [('session', args.session)])
        else:
            send_message(args.group, message, [(grp, getattr(args, grp))
                                               for grp in ('OC', 'CO', 'AC', 'CC', 'NS') if getattr(args, grp)])


if __name__ == '__main__':

    sys.exit(main())
