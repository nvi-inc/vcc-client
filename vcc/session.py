from datetime import datetime, timedelta

from vcc import make_object


class Session:
    def __init__(self, data):
        self.error = False

        self.code = self.type = self.operations = self.analysis = self.correlator = ''
        self.start = datetime.utcnow() + timedelta(days=7)
        self.duration = 3600
        self.included, self.removed = [], []
        self.schedule, self.master = None, 'standard'

        make_object(data, self)

        self.end = self.start + timedelta(seconds=self.duration)

    def __str__(self):
        oc = self.operations.upper() if self.operations else 'N/A'
        cor = self.correlator.upper() if self.correlator else 'N/A'
        delta = self.start - datetime.utcnow()
        dt, unit = int(delta.days), 'day'
        upcoming, dt = dt >= 0, abs(dt)
        if dt < 1:
            dt, unit = int(delta.total_seconds() / 3600), 'hour'
        if dt < 1:
            dt, unit = int(delta.total_seconds() / 60), 'minute'
        start, ago = ('starts in', '') if upcoming else ('started', 'ago')
        unit = unit+'s' if dt > 1 else unit
        return f'{self.code:8s} {self.start} {self.duration/3600:5.2f} ' \
               f'{oc:<4s} {cor:<4s} - {start} {dt:2d} {unit} {ago}'

    def update_schedule(self, data):
        self.schedule = make_object(data) if data else None

    @property
    def network(self):
        return list(map(str.capitalize, self.schedule.observing if self.schedule else self.included))

    def get_status(self):
        now = datetime.utcnow()
        return 'waiting' if now < self.start else 'terminated' if self.end < now else 'observing'

    def total_waiting(self):
         return (self.start - datetime.utcnow()).total_seconds() if self.get_status() == 'waiting' else -1

    def observing_done(self, ):
        return (datetime.utcnow() - self.start).total_seconds()

    @property
    def sched_version(self):
        return f'V{self.schedule.version:.0f} {self.schedule.updated.strftime("%Y-%m-%d %H:%M")}' \
            if self.schedule else 'None'


