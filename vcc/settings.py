from pathlib import Path
import sys

from vcc import make_object, get_config_data


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
    for path in [Path(args.config if args.config else 'vcc.ctl'), Path('/usr2/control/vcc.ctl'), Path(Path.home(), 'vcc.ctl')]:
        if path.exists():
            args.config = str(path)
            break

    if data := get_config_data(args.config):
        # Add information in config file to this module
        make_object(data, this_module)
        return args
    print('no valid configuration file')


def check_privilege(groups):
    this_module = sys.modules[__name__]
    for grp in [groups] if isinstance(groups, str) else groups:
        if hasattr(this_module.Signatures, grp):
            return True
    return False


def get_user_code(grp):
    this_module = sys.modules[__name__]
    return info[0] if (info := getattr(this_module.Signatures, grp, None)) else None
