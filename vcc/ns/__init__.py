import re
import json
import psutil
import logging

from psutil import process_iter, AccessDenied, NoSuchProcess

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
        vcc_cmd('message-box', options, user='oper', group='rtx')


# Notify oper using vcc message_box. Pop message box to all displays or the user display
def show_sessions(title, sessions, option='', display=None):
    # Use vcc_cmd to start a new thread for all 'oper' displays
    message = json.dumps(sessions)
    for display in get_displays(display):
        options = f"{option} -c '{settings.args.config}' -t '{title}' -m '{message}' -D '{display}'"
        vcc_cmd('sessions-wnd', options, user='oper', group='rtx')


def get_ddout_log():
    """
    Get log opened by Field System
    """
    for proc in process_iter(['name', 'pid']):
        if proc.info['name'] == 'ddout':
            try:
                files = [file.path for file in proc.open_files() if file.path.startswith('/usr2/log')]
                return files[0] if files else None
            except (NoSuchProcess, AccessDenied):
                return None
    return None
