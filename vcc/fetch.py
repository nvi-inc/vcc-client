from datetime import datetime, timedelta

from vcc import settings, signature, VCCError, groups
from vcc.messaging import RMQclientException
from vcc.server import VCC, get_server


# Test that inbox is available
def test_inbox(vcc, group_id, session=None):
    print(f'Test on {group_id} INBOX ', end='')
    try:
        rmq_client = vcc.get_rmq_client(session)
        print(f'is successful! Response time is {inbox.alive():.3f} seconds')

    except (VCCError, RMQclientException) as exc:
        print(f'fails! [{str(exc)}]')


# Test if users in configuration file are valid
def test_users():
    for group_id in groups:
        if hasattr(settings.Signatures, group_id):
            print(f'Test on {group_id} user ', end='')

            try:
                with VCC(group_id) as vcc:
                    api = vcc.get_api()
                    rsp = api.get('/users/valid', headers=signature.make(group_id))
                    if not rsp or not signature.validate(rsp):
                        raise VCCError(f'invalid response {rsp.text}')
                    print('is successful!')
                    ses_id = None
                    # Testing DB needs a session code. Get the first upcoming session
                    if group_id == 'DB':
                        today = datetime.utcnow().date()
                        begin, end = today - timedelta(days=2), today + timedelta(days=7)
                        rsp = api.get('/sessions', params={'begin': begin, 'end': end, 'master': 'all'})
                        if not rsp:
                            raise VCCError(rsp.text)
                        ses_id = rsp.json()[0]
                    test_inbox(vcc, group_id, ses_id)
            except VCCError as exc:
                print(f'fails! [{str(exc)}]')


# Test if users in configuration file are valid
def fetch_once():
    try:
        with VCC('NS') as vcc:
            client = vcc.get_rmq_client()

    except VCCError as exc:
        print(f'failed! [{str(exc)}]')


def main():
    import argparse

    parser = argparse.ArgumentParser(description='Test VCC users')
    parser.add_argument('-c', '--config', help='config file', required=True)
    parser.add_argument('-once', help='execute fetch once', action='store_true', required=False)

    args = settings.init(parser.parse_args())

    if settings.check_privilege('NS'):
        if args.once:
           fetch_once()
    else:
        print(f'Only Network Station can use fetch command')


if __name__ == '__main__':

    import sys
    sys.exit(main())
