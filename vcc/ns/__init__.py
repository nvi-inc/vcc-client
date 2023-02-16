import os
import psutil
from subprocess import Popen

import logging

logger = logging.getLogger('vcc')


# Get all displays for oper users.
def get_displays(all_users=False, display=None):

    displays = [display if display else os.environ.get('DISPLAY', None)]
    if all_users:
        oper = [user.pid for user in psutil.users() if user.name == 'oper']
        for prc in psutil.process_iter():
            for parent in prc.parents():
                if parent.pid in oper:
                    try:
                        displays.append(prc.environ().get('DISPLAY', None))
                    finally:
                        break

    return list(filter(None, list(set(displays))))


# Notify oper using vcc message_box. Pop message box to all displays or the user display
def notify(title, message, all_users=False, display=None):
    cmd = f"vcc-message \'{title}\' \'{message}\'"

    # Use popen so that thread is not blocked by window message
    if not display and not all_users:
        Popen([cmd], shell=True, stdin=None, stdout=None, stderr=None, close_fds=True)
    else:
        for display in get_displays(all_users, display):
            logger.debug(f'display is {display}')
            env = {**os.environ, **{'DISPLAY': display}}
            Popen([cmd], env=env, shell=True, stdin=None, stdout=None, stderr=None, close_fds=True)


