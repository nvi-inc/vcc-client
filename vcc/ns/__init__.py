import json
import logging
import os
import psutil
import re

from pathlib import Path
from subprocess import Popen, PIPE

from vcc import settings, vcc_cmd


logger = logging.getLogger('vcc')
get_file_name = re.compile('.*filename=\"(?P<name>.*)\".*').match


# Get all displays for oper users.
def get_displays(display=None):

    if display:
        return [display]
    displays = []
    for prc in psutil.process_iter():
        try:
            displays.append(prc.environ().get('DISPLAY', None))
        except:
            pass

    return list(filter(None, list(set(displays))))


# Notify oper using vcc message_box. Pop message box to all displays or the user display
def notify(title, message, icon='info', display=None):
    # Use vcc_cmd to start a new thread for all 'oper' displays
    for display in get_displays(display):
        options = f"-t '{title}' -m '{message}' -i '{icon}' -D '{display}'"
        try:
            vcc_cmd('message-box', options, user='oper', group='rtx')
        except Exception as exc:
            logger.warning(f"notify {str(exc)}")


# Notify oper using vcc message_box. Pop message box to all displays or the user display
def show_sessions(title, sessions, option='', display=None):
    # Use vcc_cmd to start a new thread for all 'oper' displays
    message = json.dumps(sessions)
    for display in get_displays(display):
        options = f"{option} -c '{settings.args.config}' -t '{title}' -m '{message}' -D '{display}'"
        vcc_cmd('sessions-wnd', options, user='oper', group='rtx')


PATH = ':'.join(["/usr2/st/bin", "/usr2/fs/bin", os.environ.get('PATH')])


def get_ddout_log():
    try:
        output, _ = Popen(['lognm'], env={'PATH': PATH}, stdout=PIPE).communicate()
        if name := output.decode('utf-8').strip():
            return Path('/usr2/log', f"{name}.log")
        logger.warning(f"get_ddout_log failed {output}")
        return None
    except Exception as exc:
        logger.warning(f"get_ddout_log failed {str(exc)}")
        return None

