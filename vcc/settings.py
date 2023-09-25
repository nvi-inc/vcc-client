import sys
from pathlib import Path

import toml

from vcc import make_object, groups


# Flag configuration problems
class BadConfigurationFile(Exception):
    def __init__(self, err_msg):
        self.err_msg = err_msg


# Get application input options and parameters
def init(args):
    # Initialize global variables
    this_module = sys.modules[__name__]

    # Store all arguments under args variable
    setattr(this_module, 'args', args)
    for path in [Path(args.config if args.config else 'vcc.ctl'), Path('/usr2/control/vcc.ctl'),
                 Path(Path.home(), 'vcc.ctl')]:
        print('INIT', str(path))
        if path.exists():
            try:
                data = toml.load(path.open())
                # Set some default folders
            except toml.TomlDecodeError as exc:
                print(f'Error reading {path} [{str(exc)}]')
                exit(0)
            # Add information in config file to this module
            make_object(data, this_module)
            return args
    print('no valid configuration file')


def check_privilege(group_id):
    this_module = sys.modules[__name__]
    return hasattr(this_module.Signatures, group_id)
