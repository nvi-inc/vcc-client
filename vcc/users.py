from vcc import settings, VCCError, vcc_groups
from vcc.client import VCC


# Test if users in configuration file are valid
def test_users():
    for group_id, name in vcc_groups.items():
        if code := getattr(settings.Signatures, group_id, (None, None, None))[0]:
            print(f'{name} {code}', end=' ')
            try:
                with VCC(group_id) as vcc:
                    if not (rsp := vcc.get('/users/valid')):  # , headers=signature.make(group_id))
                        raise VCCError(f'has invalid response {rsp.text}')
                    print(f"is valid! Inbox has {rsp.json().get('messages_ready', 0)} messages", end=' ')
            except VCCError as exc:
                print(f'test fails! [{str(exc)}]')
            print()


def main():
    import argparse

    parser = argparse.ArgumentParser(description='Test VCC users')
    parser.add_argument('-c', '--config', help='config file', required=False)

    settings.init(parser.parse_args())

    test_users()


if __name__ == '__main__':

    import sys
    sys.exit(main())
