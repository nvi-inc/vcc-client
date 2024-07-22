from vcc import settings, signature, VCCError, vcc_groups
from vcc.client import VCC, RMQclientException


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
    for group_id, name in vcc_groups.items():
        if code := getattr(settings.Signatures, group_id, (None, None, None))[0]:
            print(f'{name} {code}', end=' ')
            try:
                with VCC(group_id) as vcc:
                    if not (rsp := vcc.api.get('/users/valid')):  # , headers=signature.make(group_id))
                        raise VCCError(f'has invalid response {rsp.text}')
                    print('is valid!', end=' ')
                    test_inbox(vcc, group_id, 'db_test' if group_id == 'DB' else None)
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
