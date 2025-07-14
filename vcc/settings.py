from pathlib import Path
import sys

from vcc import make_object, get_config_data


# Flag configuration problems
class BadConfigurationFile(Exception):
    def __init__(self, err_msg):
        self.err_msg = err_msg


# Get application input options and parameters
def init(*argv, **kwargs):
    # Initialize global variables
    this_module = sys.modules[__name__]

    # Input is path of control file
    if path := kwargs.get('path', None):
        args = make_object({'config': path})
    elif argv:
        args = argv[0]
    else:
        print('invalid settings parameters')
        sys.exit(1)

    # Store all arguments under args variable
    setattr(this_module, 'args', args)
    default = Path(args.config) if args.config else Path(Path.cwd(), 'vcc.ctl')
    for file in [default, Path('/usr2/control/vcc.ctl'), Path(Path.home(), 'vcc.ctl')]:
        if file.exists():
            args.config = str(file)
            break
    if data := get_config_data(args.config):
        # Add information in config file to this module
        make_object(data, this_module)
        return args
    print('no valid configuration file')
    sys.exit(1)


def check_privilege(groups):
    this_module = sys.modules[__name__]
    for grp in [groups] if isinstance(groups, str) else groups:
        if hasattr(this_module.Signatures, grp):
            return True
    return False


def get_user_code(grp):
    this_module = sys.modules[__name__]
    return info[0] if (info := getattr(this_module.Signatures, grp, None)) else None
