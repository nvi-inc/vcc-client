import os
import re
import hashlib
from pathlib import Path
from datetime import datetime, timedelta

from tkinter import messagebox

from vcc import settings, VCCError, json_decoder, vcc_cmd
from vcc.client import VCC
from vcc.fslog import download_log


# Compute md5 hash for a file
def get_md5sum(path, chunk_size=32768):

    md5 = hashlib.md5()
    with open(path, 'rb') as file:
        while chunk := file.read(chunk_size):
            md5.update(chunk)
    return md5.hexdigest()


def time_it(some_function):
    from time import time

    def wrapper(*args, **kwargs):
        t1 = time()
        result = some_function(*args, **kwargs)
        print(f'{some_function.__name__}: {time()-t1}')
        return result
    return wrapper


def print_session(data):
    start = datetime.fromisoformat(data['start'])
    db_name = f'{start.strftime("%Y%m%d")}-{data["code"].lower()}'
    included = f'{"".join(list(map(str.capitalize, data["included"])))}'
    removed = f' -{"".join(list(map(str.capitalize, data["removed"])))}' if data['removed'] else ''
    print(f'{data["code"].upper():12s} {data["type"].upper():12s}', end=' ')
    print(f'{start.strftime("%Y-%m-%d %H:%M")} {included + removed:40s}', end=' ')
    print(f'{data["operations"].upper():4s} {data["correlator"].upper():4s}', end=' ')
    print(f'{data["analysis"].upper():4s} {db_name}')


sked_types = {'.skd', '.vex'}
get_filename = re.compile('.*filename=\"(?P<name>.*)\".*').match
is_log = re.compile(r'(?P<ses_id>[a-z0-9]*)(?P<sta_id>[a-z0-9]{2})(?P<fmt>_full\.log\.bz2|\.log)').match


def fetch_files(name):
    def save_file(response, subdir, msg):
        if not (found := get_filename(response.headers['content-disposition'])):
            messagebox.showerror(f"Download problem", f"Problem downloading {msg}\n"
                                                      f"{response.headers['content-disposition']}")
            return None
        dir_path = getattr(folders, subdir, '.') if (folders := getattr(settings, 'Folders')) else '.'
        with open(p := Path(dir_path, found['name']), 'wb') as f:
            f.write(rsp.content)
        return p

    path = Path(name)

    with VCC() as vcc:
        # Request schedule files (skd, vex and text)
        if not (suffix := path.suffix[1:]):
            ses_id, folder = name.lower(), 'schedule'
            if not vcc.api.get(f'/sessions/{ses_id}'):
                messagebox.showerror(ses_id.upper(), f'{ses_id} is not an IVS session')
                return
            if not (rsp := vcc.api.get(f'/schedules/{ses_id}')):
                messagebox.showerror('Get schedule', f'No schedule for files for {ses_id}')
                return
            if not (file := save_file(rsp, f'schedule for {ses_id}', folder)):
                return
            print(f'{file.name} downloaded')
            # If sk was downloaded, look for vex file
            if file.suffix == '.skd' and (rsp := vcc.api.get(f'/schedules/{ses_id}', params={'select': 'vex'})):
                if file := save_file(rsp, folder, f'{ses_id}.vex'):
                    print(f'{file.name} downloaded')
            # Download text file
            if rsp := vcc.api.get(f'/schedules/{ses_id}', params={'select': 'txt'}):
                if file := save_file(rsp, folder, f'{ses_id}.txt'):
                    print(f'{file.name} downloaded')
            # Download prc file is user is stations
            if sta_id := getattr(settings.Signatures, 'NS', [''])[0].lower():
                if rsp := vcc.api.get(f'/schedules/{ses_id}', params={'select': f'{sta_id}|prc'}):
                    if file := save_file(rsp, 'proc', f'{ses_id}{sta_id}.prc'):
                        print(f'{file.name} downloaded')

        elif suffix in ('skd', 'vex', 'txt', 'prc'):
            stem = Path(name.lower()).stem
            folder = 'proc' if suffix == 'prc' else 'schedule'
            ses_id, select = (stem[:-2], f"{stem[-2:]}|{suffix}") if suffix == 'prc' else (stem, suffix)
            # Download session file
            if not (rsp := vcc.api.get(f'/schedules/{ses_id}', params={'select': select})):
                messagebox.showerror(f'Get file {name}', f"{name} failed!\n{rsp.json().get('error', rsp.text)}")
            elif file := save_file(rsp, folder, name):
                print(f'{file.name} downloaded')
        elif suffix in ('log', 'bz2') and download_log(vcc, name):
            pass
        else:
            messagebox.showerror('invalid file type', f'VCC does not store {suffix} files')


def upload_schedule_files(path_list, notify=True):
    if not settings.check_privilege('OC'):
        vcc_cmd('message-box',
                "-t 'NO privilege for this action' -m 'Only Operations Center can upload schedule files' -i 'warning'")
        return
    try:
        with VCC('OC') as vcc:
            api = vcc.get_api()
            files = [('files', (os.path.basename(path), open(path, 'rb'), 'text/plain')) for path in path_list]
            rsp = api.post('/schedules', files=files, params={'notify': notify})
            if not rsp:
                raise VCCError(f'{rsp.status_code}: {rsp.text}')
            message = '<br>'.join([f"{os.path.basename(file)} {result}" for file, result in rsp.json().items()])
            vcc_cmd('message-box', f"-t 'Schedule files' -m '{message}' -i 'info'")
    except VCCError as exc:
        err = '<br>'.join(str(exc).splitlines())
        message = '<br>'.join([os.path.basename(path) for path in path_list])
        vcc_cmd('message-box', f"-t 'Problem uploading schedule files' -m '{message}<br>{err}' -i 'warning'")


def show_session(code):
    try:
        with VCC() as vcc:
            # Check if this is a session code
            if rsp := vcc.get_api().get(f'/sessions/{code}'):
                print_session(json_decoder(rsp.json()))
            else:
                print(f'Failed to get information for {code}!')
        return
    except VCCError as exc:
        print(f'Failed to get information for {code}! {str(exc)}')


def show_next(sta_id):
    try:
        with VCC() as vcc:
            rsp = vcc.get_api().get(f'/sessions/next/{sta_id}')
            if not rsp:
                raise VCCError(rsp.text)
        now = datetime.utcnow()
        for data in json_decoder(rsp.json()):
            if data['start'] > now:
                print_session(data)
    except VCCError as exc:
        print(f'Failed to get information for {sta_id}! [{str(exc)}]')


master_types = dict(int='intensives ', std='24H ', all='')






