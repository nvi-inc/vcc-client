from datetime import datetime, timedelta

from vcc import settings, signature, VCCError, groups
from vcc.messaging import RMQclientException
from vcc.server import VCC


# Test that inbox is available
def test_inbox(vcc, group_id, session=None):
    print(f'Inbox', end=' ')
    if group_id == 'DB' and not session:
        print('not tested!')
        return
    try:
        msg = vcc.get_rmq_client(session)
        print(f'is available! Response time is {msg.alive():.3f} seconds')

    except (VCCError, RMQclientException) as exc:
        print(f'NOT available! [{str(exc)}]')


# Test if users in configuration file are valid
def test_users():
    text = {'CC': 'Coordinating Center {}', 'OC': "Operations Center {}", 'AC': 'Analysis Center {}',
            'CO': 'Correlator {}', 'NS': 'Network Station {}', 'DB': 'Dashboard'}
    for group_id in groups:
        code = getattr(settings.Signatures, group_id, (None, None, None))[0]
        if code:
            print(text[group_id].format(code), end=' ')
            try:
                with VCC(group_id) as vcc:
                    api = vcc.get_api()
                    rsp = api.get('/users/valid', headers=signature.make(group_id))
                    if not rsp or not signature.validate(rsp):
                        raise VCCError(f' has invalid response {rsp.text}')
                    print('is valid!', end=' ')
                    ses_id = None
                    # Testing DB needs a session code. Get the first upcoming session
                    if group_id == 'DB':
                        today = datetime.utcnow().date()
                        begin, end = today - timedelta(days=2), today + timedelta(days=7)
                        rsp = api.get('/sessions', params={'begin': begin, 'end': end, 'master': 'all'})
                        if not rsp:
                            raise VCCError(rsp.text)
                        if rsp.json():
                            ses_id = rsp.json()[0]
                    test_inbox(vcc, group_id, ses_id)
            except VCCError as exc:
                print(f'test fails! [{str(exc)}]')


def main():
    import argparse

    parser = argparse.ArgumentParser(description='Test VCC users')
    parser.add_argument('-c', '--config', help='config file', required=False)

    settings.init(parser.parse_args())

    test_users()


if __name__ == '__main__':

    import sys
    sys.exit(main())
