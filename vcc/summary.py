from datetime import datetime, timedelta

from vcc import settings, json_decoder
from vcc.client import VCC
from vcc.session import Session

masters = ['all', 'std', 'int']


def summary(sta_id, begin, end):
    with VCC() as vcc:
        end = end if end else datetime.utcnow().date()
        rsp = vcc.get('/sessions', params={'begin': begin, 'end': end, 'master': 'all'})
        sessions = [Session(vcc.get(f'/sessions/{ses_id}').json()) for ses_id in rsp.json()]

        sta_id = sta_id.capitalize()
        for session in sessions:
            if sta_id in session.included:
                print(f'{session.code.lower()}', end=' ')
                rsp = vcc.get(f'/schedules/{session.code.lower()}', params={'select': 'summary'})
                if rsp:
                    scans = {info['station']: info['nbr_scans'] for info in json_decoder(rsp.json())['scheduled']}
                    print(scans.get(sta_id, 'N/A'))
                else:
                    print('N/A')


def main():
    import argparse

    def valid_date(s):
        try:
            return datetime.strptime(s, "%Y-%m-%d").date()
        except ValueError:
            msg = "not a valid date: {0!r}".format(s)
            raise argparse.ArgumentTypeError(f'not a valid date format: {s}')

    parser = argparse.ArgumentParser(description='VCC station summary')
    parser.add_argument('-c', '--config', help='config file', required=False)
    parser.add_argument('sta_id', help='station or session code', nargs='?')
    parser.add_argument('begin', help='first day of summary (yyyy-mm-dd)', type=valid_date)
    parser.add_argument('end', help='last day of summary (yyyy-mm-dd)', nargs='?', type=valid_date)

    args = settings.init(parser.parse_args())

    summary(args.sta_id, args.begin, args.end)


if __name__ == '__main__':

    import sys
    sys.exit(main())
