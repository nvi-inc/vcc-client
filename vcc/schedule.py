import os

from vcc import VCCError
from vcc.server import VCC


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


