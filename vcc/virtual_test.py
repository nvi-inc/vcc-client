import os
import sys

from pathlib import Path


def main():
    print('VIRTUAL', os.environ.get('VIRTUAL_ENV'))
    print(sys.argv)
    folder = Path(sys.argv[0]).parent
    print('folder', folder)
    print('interpreter', sys.executable)


if __name__ == '__main__':

    import sys
    sys.exit(main())
