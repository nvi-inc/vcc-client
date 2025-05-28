from pathlib import Path

from vcc import settings
from vcc.progress import ProgressDots
from vcc.client import VCC
from vcc.ns import get_file_name


def download(file_type, session, station):

    waiting = ProgressDots('Contacting VCC .', delay=0.5)
    waiting.start()
    with VCC('NS') as vcc:
        msg = get_prc(vcc, session, station) if file_type == 'prc' else get_sched(vcc, session, file_type)
        waiting.stop()
        print(msg)


def get_sched(vcc, session, file_type):
    problem = f'Problem downloading {file_type} file for {session}'
    if not (rsp := vcc.get(f'/schedules/{session}', params={'select': file_type})):
        try:
            return rsp.json().get('error', problem)
        except:
            return problem
    if not (found := get_file_name(rsp.headers['content-disposition'])):
        return f"{problem} [{rsp.headers['content-disposition']}]"
    # Save file
    path = Path(settings.Folders.schedule, filename := found['name'])
    with open(path, 'wb') as f:
        f.write(rsp.content)
    return f"{filename} downloaded"


def get_prc(vcc, session, station):
    return 'Not implemented'
