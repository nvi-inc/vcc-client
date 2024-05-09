def main():

    import argparse

    parser = argparse.ArgumentParser(description='Network Station', prog='vcc-ns', add_help=False)
    parser.add_argument('action',
                        choices=['monit', 'fetch', 'next', 'drudg', 'onoff', 'log'],
                        type=str.lower)
    parser.add_argument('-c', '--config', help='config file', required=False)
    parser.add_argument('-D', '--debug', help='debug mode is on', action='store_true')
    action = parser.parse_known_args()[0].action

    # Create new arguments for specified action
    options = {'drudg': [{'args': ['-v', '--vex'], 'kwargs': {'action': 'store_true', 'help': 'use vex file'}},
                         {'args': ['session'], 'kwargs': {'help': 'session code', 'type': str.lower}}],
               'onoff': [{'args': ['log'], 'kwargs': {'help': 'log file'}}],
               'next': [{'args': ['-p', '--print'], 'kwargs': {'action': 'store_true'}},
                        {'args': ['-d', '--days'], 'kwargs': {'help': 'days ahead', 'type': int, 'default': 14}}],
               'log': [{'args': ['log'], 'kwargs': {'help': 'log file'}}],
               'fetch': [{'args': ['fetch'], 'kwargs': {'help': 'fetch schedule'}},
                         {'args': ['-f', '--force'], 'kwargs': {'action': 'store_true'}}],
               }
    exclusive = {'log': [{'args': ['-f', '--full'], 'kwargs': {'action': 'store_true'}},
                         {'args': ['-r', '--reduce'], 'kwargs': {'action': 'store_true'}}],
                 'fetch': [{'args': ['-o', '--overwrite'], 'kwargs': {'action': 'store_true'}},
                           {'args': ['-r', '--rename'], 'kwargs': {'action': 'store_true'}}]
                 }

    parser = argparse.ArgumentParser(description='Network Station', prog=f'vcc-ns {action}')
    parser.add_argument('action', choices=[action], help=argparse.SUPPRESS, type=str.lower)
    parser.add_argument('-c', '--config', help='config file', required=False)
    parser.add_argument('-D', '--debug', help='debug mode is on', action='store_true')
    for option in options.get(action, []):
        parser.add_argument(*option['args'], **option['kwargs'])
    if exclusive.get(action, None):
        optional = parser.add_mutually_exclusive_group(required=False)
        for option in exclusive.get(action, None):
            optional.add_argument(*option['args'], **option['kwargs'])

    parser.print_usage()


main()
