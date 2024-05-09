from collections import OrderedDict, defaultdict
import string
from operator import itemgetter
import os
import re


from datetime import datetime, timedelta

_UTC_FORMATS = {'sked': '%Y%j%H%M%S', 'skd': '%y%j%H%M%S', 'vex': '%Yy%jd%Hh%Mm%Ss'}


def utc(*args, **kwargs):
    def decode(fmt_name, text):
        if fmt_name == 'vex' and '24h' in text:
            return datetime.strptime(text[:9], '%Yy%jd') + timedelta(days=1)
        elif fmt_name == 'skd' and text[-6:] == '240000':
            return datetime.strptime(text[:5], '%y%j') + timedelta(days=1)
        return datetime.strptime(text, _UTC_FORMATS[fmt_name])

    for key, value in kwargs.items():
        if key in _UTC_FORMATS:
            return decode(key, value)
    # Value and format are provided as argument 0 and 1
    return datetime.strptime(args[0], args[1])


class SKD:
    def __init__(self, path):
        self.path, self.file = path, None
        self.line, self.line_nbr = '', 0

        self.scheduling_software, self.session_code = 'SKED', ''
        self.stations = {'names': {}, 'codes': {}, 'keys': {}, 'removed': []}
        self.sources, self.scans = {}, {}
        self.observations, self.baselines = OrderedDict(), OrderedDict()
        self.obs_list = []
        self.scheduled_obs = 0
        self.missed = []
        self.valid = os.path.exists(path)
        self.correlator = self.start = self.end = None
        self.errors, self.warnings = [], []

    def __enter__(self):

        self.file = open(self.path, encoding='utf-8', errors="surrogateescape")
        self.line_nbr = 0
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.file:
            self.file.close()
            self.file = None

    def has_next(self):
        if self.file:
            self.line = self.readline()
            if not self.line:
                return False
            self.line_nbr += 1
            return True
        return False

    def readline(self):
        return self.file.readline()

    def read_until(self, key_word='', start_word=''):
        while self.has_next():
            if self.line:
                if key_word and start_word:
                    return self.line.startswith(start_word) and key_word in self.line
                if key_word:
                    return key_word in self.line
                if start_word:
                    return self.line.startswith(start_word)
        return False

    def __eq__(self, other):
        if self.session_code != other.session_code or \
                self.scheduled_obs != other.scheduled_obs or \
                len(self.observations) != len(other.observations):
            return False

        def is_same(first, second):

            if isinstance(first, dict):
                if len(first) != len(second):
                    return False
                for (k1, v1), (k2, v2) in zip(first.items(), second.items()):
                    if k1 != k2 or not is_same(v1, v2):
                        return False
            if isinstance(first, list):
                if len(first) != len(second):
                    return False
                for one, two in zip(first, second):
                    if not is_same(one, two):
                        return False
            elif first != second:
                return False
            return True

        # Check if same observations
        for (skd, skd_obs), (vex, vex_obs) in zip(self.observations.items(), other.observations.items()):
            if skd != vex:
                return False
            for (skd_key, skd_data), (vex_key, vex_data) in zip(skd_obs.items(), vex_obs.items()):
                if skd_key != vex_key or not is_same(skd_data, vex_data):
                    return False
        return True

    @property
    def is_vex(self):
        return self.__class__.__name__ == 'VEX'

    def section_not_used(self, line):
        pass

    def section_param(self, line):
        if line.startswith('SCHEDULING_SOFTWARE'):
            self.scheduling_software = line.split()[-1]
        elif line.startswith('SCHEDULER'):
            info = line.split()
            self.correlator = info[3]
            if self.scheduling_software == 'VieSched++':
                self.start, self.end = utc(skd=info[5]), utc(skd=info[7])
            else:
                self.start, self.end = utc(sked=info[5]), utc(sked=info[7])

    def section_stations(self, line):
        if line.startswith('A'):
            info = line.split()
            key, name, code = [info[i] for i in [1, 2, 14]]
            sta = SKD.init_sta(code, name, key)
            self.stations['codes'][code] = self.stations['names'][name] = self.stations['keys'][key] = sta

    def section_sources(self, line):
        code, name = (line.split()[0:2])
        src = SKD.init_src(code, name)
        self.sources[src['name']] = src

    def section_sked(self, line):
        info = line.split()
        start = utc(skd=info[4])
        name = start.strftime('%j-%H%M')
        scan = SKD.init_scan(name, info[0], start)
        # Extract stations
        scan['ids'] = {}
        n = int(len(info[9]) / 2)
        if int(n * 2) != len(info[9]):
            self.warnings.add(f'Problem with scan {info[0]} {info[4]}')
            return
        scan['ids'] = {k: int(info[i]) for i, k in enumerate(info[9][::2], 11+n)}
        self.scans[name].append(scan) if name in self.scans else self.scans.update({name: [scan]})

    # Read skd file ans extract information
    def read(self, VieSched_sort=False):

        sections = {'$PARAM': self.section_param, '$STATIONS': self.section_stations,
                    '$SOURCES': self.section_sources, '$SKED': self.section_sked}
        section = self.section_not_used

        # First line must be $EXPER
        if not self.read_until(start_word='$EXPER'):
            self.errors.append('Did not find $EXPER')
            self.valid = False
            return
        # Decode session code
        self.session_code = self.line.split()[1].lower()
        # Decode all sections
        while self.has_next():
            if not (line := self.line) or line.startswith('*'):  # Empty line or comment
                continue
            if line.startswith('$'):  # This is a new section
                section = sections.get(line.strip(), self.section_not_used)
            else:
                section(line)

        # Order scans by time and source name
        sort_source = not (VieSched_sort and self.scheduling_software == 'VieSched++')
        scans, self.scans = dict(sorted(self.scans.items())), OrderedDict()
        for name, scan in scans.items():
            if len(scan) == 1:
                end = self.add_scan(scan[0])
            else:
                scan = sorted(scan, key=lambda i: (i['start'], i['source'])) if sort_source else \
                    sorted(scan, key=lambda i: i['start'])
                for index, rec in zip(string.ascii_lowercase, scan):
                    rec['name'] = f'{rec["name"]}{index}'
                    end = self.add_scan(rec)
        if not hasattr(self, 'end'):
            self.end = end

        self.set_first_sources()
        self.count_observations()

    def add_scan(self, scan):
        if not hasattr(self, 'start'):
            self.start = scan['start']

        # Add scan to scans
        name = scan['name']
        if name in self.scans:
            self.warnings.append(f'duplicate scan {name}')
        self.scans[name] = scan;

        scan_duration = 0
        for key, duration in scan['ids'].items():
            if key in self.stations['keys']:
                scan_duration = max(duration, scan_duration)
                code = self.stations['keys'][key]['code']
                scan['station_codes'][code] = {'duration': duration}
                self.stations['codes'][code]['scans'][name] = scan
        scan.pop('ids')
        scan['station_codes'] = OrderedDict(sorted(scan['station_codes'].items()))

        # Update sources dict
        source = scan['source']
        if source not in self.observations:
            self.observations[source] = {}
        src = self.observations[source]
        for fr in scan['station_codes']:
            if fr not in src:
                src[fr] = {}
            for to in scan['station_codes']:
                if fr < to:
                    if to not in src[fr]:
                        src[fr][to] = []
                    obs = SKD.init_obs(scan, fr, to)
                    src[fr][to].append(obs)
                    self.obs_list.append(obs)

        return scan['start'] + timedelta(seconds=scan_duration)

    def set_first_sources(self):
        # Set first sources
        for code, sta in self.stations['codes'].items():
            if len(sta['scans']) > 0:
                sta['first_source'] = list(sta['scans'].values())[0]['source']

    def count_observations(self):
        # Count observations for stations
        scheduled = 0
        for code, sta in self.stations['codes'].items():
            nbr_obs = 0
            for scan in sta['scans'].values():
                nbr_obs += len(scan['station_codes']) - 1
            sta['scheduled_obs'] = nbr_obs
            scheduled += nbr_obs
        self.scheduled_obs = int(scheduled / 2)

        # Count observations for sources
        for name, src in self.sources.items():
            if name in self.observations:
                obs = self.observations[name]
                nbr_obs = 0
                for fr, info in obs.items():
                    for to, scans in info.items():
                        nbr_obs += len(scans)
                src['scheduled_obs'] += nbr_obs

        # Count observations for baselines
        names = sorted(self.stations['names'].keys())
        for index, fr in enumerate(names):
            sta = self.stations['names'][fr]
            for to in names[index+1:]:
                nbr_obs = 0
                code = self.stations['names'][to]['code']
                for scan in sta['scans'].values():
                    if code in scan['station_codes']:
                        nbr_obs += 1
                self.baselines[f'{fr}-{to}'] = nbr_obs

    def remove_stations(self, stations):
        for name in stations:
            sta_code = ''
            if name in self.stations['names']:
                sta_code = self.stations['names'][name]['code']
            elif name.startswith('TIGO') and 'TIGO' in self.stations['names']:
                sta_code = self.stations['names']['TIGO']['code']

            if sta_code:
                for scan_name in list(self.scans.keys()):
                    sta_lst = self.scans[scan_name]['station_codes']
                    if sta_code in sta_lst:
                        sta_lst.pop(sta_code)
                        if len(sta_lst) == 1:
                            sta = list(sta_lst.keys())[0]
                            self.stations['codes'][sta]['scans'].pop(scan_name)
                            self.scans.pop(scan_name)
                        self.stations['codes'][sta_code]['scans'].pop(scan_name)

        self.count_observations()
        return self.scheduled_obs

    def make_observations(self):
        observations = {}
        for name, scan in self.scans.items():
            stations = list(scan['station_codes'].keys())
            for i in range(0, len(stations) - 1):
                for j in range(i + 1, len(stations)):
                    obs = SKD.init_obs(scan, stations[i], stations[j])
                    observations['{}-{}-{}'.format(name, stations[i], stations[j])] = obs
                    observations['{}-{}-{}'.format(name, stations[j], stations[i])] = obs

        self.observations = observations

    def get_nbr_scans(self, id):
        return len(self.stations['codes'][id.capitalize()]['scans'])

    def get_nbr_observations(self, id):
        return self.stations['codes'][id.capitalize()]['scheduled_obs']

    def summary(self, rejected=None):
        if rejected := [sta.capitalize() for sta in re.findall('..', rejected) if sta in self.stations["codes"]] \
                if rejected else []:
            self.remove_stations(rejected)
        print(f'Summary for {self.session_code}{" without " if rejected else ""}{" ".join(rejected)}')
        info = self.stations['codes']
        for sta in sorted(info.values(), key=itemgetter('code')):
            nbr = len(sta['scans'])
            print('{p[code]} has {nbr:4d} scans and {p[scheduled_obs]:6d} observations.'.format(nbr=nbr, p=sta))
        print(f'Total scans {len(self.scans):d} and observations {self.scheduled_obs:d}')

    def list_scans(self, sta):
        sta = sta.capitalize()
        for scan in self.data['station_codes'][sta]['scans']:
            print(scan)

    def list_observations(self, sta):
        sta = sta.capitalize()

        index = 0
        for obs in self.data['obs_list']:
            if sta == obs['fr'] or sta == obs['to']:
                fr, to, scan = obs['fr'], obs['to'], obs['scan']
                duration = min(scan['station_codes'][fr]['duration'], scan['station_codes'][to]['duration'])
                index += 1
                print(f'{index:5d} {scan["name"]:10} {scan["source"]:10} {scan["start"]} {fr} {to} {duration:4d}'
                      f' {obs["X"]} {obs["S"]}')

    @staticmethod
    def init_sked():
        session = {'name': '', 'correlator': '', 'start': '', 'stop': '', 'scheduled_obs': 0, 'used_obs': 0,
                   'correlated': ''}
        return {'session': session, 'sources': {}, 'station_codes': {}, 'station_names': {}, 'station_keys': {},
                'scans': OrderedDict(), 'used': 0, 'observations': {}, 'obs_list': []}

    @staticmethod
    def init_band(channels):
        return {'sum': 0.0, 'n': 0, 'snr': {}, 'SEFD': {'measured': 0, 'predicted': 0, 'STATS': []}}

    @staticmethod
    def init_sta(code='', name='', key=''):
        return {'name': name, 'code': code, 'key': key, 'first_source': '', 'scans': OrderedDict(),
                'scheduled': 0, 'scheduled_obs': 0, 'correlated': 0, 'used': 0, 'dropped': '', 'Dropped': '',
                'X': SKD.init_band(8), 'S': SKD.init_band(6), 'antenna': {}}

    @staticmethod
    def init_src(code='', name=''):
        name = code if name == '$' else name
        return {'name': name, 'code': code, 'scheduled_obs': 0, 'scans': OrderedDict(), 'obs': {}}

    @staticmethod
    def init_scan(name, source, start):
        return {'name': name, 'source': source, 'start': start, 'station_codes': {}}

    @staticmethod
    def init_obs(scan, fr, to):
        return {'scan': scan, 'fr': fr, 'to': to}


class VEX(SKD):

    def __init__(self, path):
        super().__init__(path)

    @staticmethod
    def decode(param, row=0, col=0):
        return param[row][col]

    def read(self, VieSched_sort=False):

        blocks = defaultdict(dict)
        block, literal = '', False

        if not self.has_next() or not self.line.strip().startswith('VEX_rev'):
            print(f'{self.path} not a VEX file! Check first line.')
            return

        while self.has_next():
            for part in self.line.strip().split(';'):
                if not (part := part.strip()) or part.startswith('*'):
                    continue
                if part.startswith('end_literal'):
                    literal = False
                elif literal:
                    continue
                elif part.startswith('start_literal'):
                    literal = True
                elif part.startswith('$'):
                    block = part[1:]
                elif part.startswith('enddef') or part.startswith('endscan'):
                    blocks[block][record['code']] = record
                elif part.startswith('def ') or part.startswith('scan '):
                    record = {'code': part.split()[1], 'ref': defaultdict(list)}
                elif part.startswith('ref '):
                    key = (info := part[3:].split('='))[0].strip()[1:]
                    if block == 'GLOBAL':
                        blocks[block][key] = info[1].strip()
                    else:
                        record['ref'][key].append(info[1].strip())
                elif '=' in part:
                    if (key := (info := part.split('='))[0].strip()) not in record:
                        record[key] = []
                    record[key].append(info[1].strip().split(':'))

        # Keep EXPER information
        for code, record in blocks['EXPER'].items():
            if 'exper_name' in record:
                self.session_code = self.decode(record['exper_name']).lower()
            if 'target_correlator' in record:
                self.correlator = self.decode(record['target_correlator']).lower()
        # Keep station information
        stations, sites = blocks['STATION'], blocks['SITE']
        for _key, record in stations.items():
            code, name = record['code'], record['ref']['SITE'][0]
            if name in sites:
                site = sites[name]
                code, name = self.decode(site['site_ID']), self.decode(site.get('site_name', name))
            sta = SKD.init_sta(code, name)
            self.stations['codes'][code] = self.stations['names'][name] = sta

        # Keep source information
        for record in blocks['SOURCE'].values():
            name, code = self.decode(record['source_name']), record['code']
            self.sources[name] = SKD.init_src(code, name)
        # Keep scans self.data
        for record in blocks['SCHED'].values():
            code = self.decode(record['source'])
            source = self.decode(blocks['SOURCE'][code]['source_name'])
            start = utc(vex=self.decode(record['start']))
            self.start = self.start if self.start else start

            name = record['code'].lower()
            scan = {'name': name, 'source': source, 'start': start, 'station_codes': {}}
            self.sources[source]['scans'][name] = self.scans[name] = scan
            nbr_obs = len(record['station']) - 1
            self.scheduled_obs += int((nbr_obs * (nbr_obs + 1)) / 2)
            for info in record['station']:
                code = info[0].strip().capitalize()
                start_rec, stop_rec = int(info[1].split()[0].strip()), int(info[2].split()[0].strip())
                scan['station_codes'][code] = {'duration': stop_rec - start_rec}
                sta = self.stations['codes'][code]
                sta['scans'][name] = scan
                sta['scheduled_obs'] += nbr_obs

            scan['station_codes'] = dict(sorted(scan['station_codes'].items()))
            src = self.sources[source]

            for fr in scan['station_codes']:
                if fr not in src:
                    src[fr] = {}
                for to in scan['station_codes']:
                    if fr != to:
                        if to not in src[fr]:
                            src[fr][to] = []
                        src[fr][to].append(scan)

            if source not in self.observations:
                self.observations[source] = {}
            src = self.observations[source]
            for fr in scan['station_codes']:
                if fr not in src:
                    src[fr] = {}
                for to in scan['station_codes']:
                    if fr < to:
                        if to not in src[fr]:
                            src[fr][to] = []
                        obs = SKD.init_obs(scan, fr, to)
                        src[fr][to].append(obs)
                        self.obs_list.append(obs)

        self.end = self.end if self.end else start
        self.set_first_sources()
        self.count_observations()

        return


if __name__ == '__main__':

    import sys
    import argparse
    from pathlib import Path


    def main():

        parser = argparse.ArgumentParser(description='Edit Station downtime')
        parser.add_argument('path')

        args = parser.parse_args()

        if not (path := Path(args.path)).exists():
            print(f"{path.name} does not exist")
            exit(1)
        cls = VEX if path.suffix == '.vex' else SKD
        with cls(args.path) as skd:
            skd.read()
            print(skd.scheduling_software, skd.session_code, skd.correlator)
            print(skd.start, skd.end)
            for code, info in skd.stations['codes'].items():
                print(code, len(info['scans']))
                for name, data in info['scans'].items():
                    print(name, data['start'], data['start'] + timedelta(seconds=data['station_codes'][code]['duration']))


    sys.exit(main())
