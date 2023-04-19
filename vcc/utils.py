import os
from datetime import datetime

from vcc import settings, VCCError, json_decoder
from vcc.server import VCC


def print_session(data):
    start = data['start']
    db_name = f'{start.strftime("%y%m%d")}-{data["code"].lower()}'
    included = f'{"".join(list(map(str.capitalize, data["included"])))}'
    removed = f' -{"".join(list(map(str.capitalize, data["removed"])))}' if data['removed'] else ''
    print(f'{data["code"].upper():12s} {data["type"].upper():12s}', end=' ')
    print(f'{start.strftime("%Y-%m-%d %H:%M")} {included + removed:40s}', end=' ')
    print(f'{data["operations"].upper():4s} {data["correlator"].upper():4s}', end=' ')
    print(f'{data["analysis"].upper():4s} {db_name}')


def upload_schedule_files(path_list):
    try:
        with VCC('OC') as vcc:
            api = vcc.get_api()
            print(path_list)
            files = [('files', (os.path.basename(path), open(path, 'rb'), 'text/plain')) for path in path_list]
            rsp = api.post('/schedules', files=files)
            if not rsp:
                raise VCCError(f'{rsp.status_code}: {rsp.text}')
            [print(file, result) for file, result in rsp.json().items()]
    except VCCError as exc:
        print(f'Problem uploading {[os.path.basename(path) for path in path_list]} [{str(exc)}]')


def show_session(code):
    try:
        with VCC() as vcc:
            rsp = vcc.get_api().get(f'/sessions/{code}')
            if not rsp:
                raise VCCError(rsp.text)
        print_session(json_decoder(rsp.json()))
        return
    except VCCError as exc:
        print(f'Failed to get information for {code}! [{str(exc)}]')


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





