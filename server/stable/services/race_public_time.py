"""公开北京日期/赛时合同：不修改来源身份时间，不推断缺失时区。"""
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from django.db.models import Case, When, F, Func, DateTimeField, DateField
from django.db.models.functions import Coalesce, TruncDate, TruncTime

BEIJING = ZoneInfo('Asia/Shanghai')

@dataclass(frozen=True)
class PublicTime:
    instant: datetime | None = None
    day: date | None = None
    clock: time | None = None
    reason: str = "missing"


def public_time(obj):
    get = obj.get if isinstance(obj, dict) else lambda k, default=None: getattr(obj, k, default)
    day, clock, instant, zone = (get(k) for k in ('local_date','local_start_time','race_datetime','timezone_name'))
    try:
        if isinstance(day,str): day=date.fromisoformat(day)
        if isinstance(clock,str): clock=time.fromisoformat(clock)
        if isinstance(instant,str): instant=datetime.fromisoformat(instant.replace('Z','+00:00'))
        if instant:
            if instant.tzinfo is None: return PublicTime(reason="invalid_datetime")
            local=instant.astimezone(ZoneInfo(zone))
            if (day and local.date()!=day) or (clock and local.time()!=clock): return PublicTime(reason="time_conflict")
        elif zone == 'Asia/Shanghai' and day:
            if clock is None: return PublicTime(day=day)
            # Only the observed modern fixed +08 legacy form is admitted.
            if day.year < 1992: return PublicTime()
            instant=datetime.combine(day,clock,BEIJING)
        else:
            return PublicTime()
        bj=instant.astimezone(BEIJING)
        return PublicTime(instant.astimezone(timezone.utc),bj.date(),bj.time(),"normalized")
    except (ValueError,TypeError,ZoneInfoNotFoundError):
        return PublicTime(reason="invalid_datetime")


class _PublicInstant(Func):
    output_field=DateTimeField()
    arity=4

    def as_postgresql(self, compiler, connection, **extra_context):
        parts=[compiler.compile(e) for e in self.source_expressions]
        # All arguments are model-column expressions, not interpolated values.
        if any(params for _,params in parts): raise ValueError('public_time_requires_columns')
        instant,day,clock,zone=[sql for sql,_ in parts]
        known=f"{zone} IN (SELECT name FROM pg_timezone_names)"
        safe_zone=f"CASE WHEN {known} THEN {zone} ELSE 'UTC' END"
        local=f"({instant} AT TIME ZONE ({safe_zone}))"
        sql=f"""CASE WHEN {instant} IS NOT NULL THEN
          CASE WHEN {known} AND ({day} IS NULL OR {local}::date = {day})
            AND ({clock} IS NULL OR {local}::time = {clock}) THEN {instant} END
          WHEN {zone} = 'Asia/Shanghai' AND {day} >= DATE '1992-01-01'
            AND {clock} IS NOT NULL THEN ({day} + {clock}) AT TIME ZONE 'Asia/Shanghai' END"""
        return sql,[]

    def as_sqlite(self, compiler, connection, **extra_context):
        def convert(instant,day,clock,zone):
            # Django SQLite stores aware timestamps as naive UTC text.
            if instant:
                instant=datetime.fromisoformat(instant)
                if instant.tzinfo is None: instant=instant.replace(tzinfo=timezone.utc)
            value=public_time(dict(race_datetime=instant,local_date=day,local_start_time=clock,timezone_name=zone)).instant
            return value.replace(tzinfo=None).isoformat(' ') if value else None
        connection.connection.create_function('umanews_public_instant',4,convert,deterministic=True)
        return super().as_sql(compiler,connection,function='umanews_public_instant',**extra_context)


def annotate_public_time(queryset):
    return queryset.annotate(public_instant=_PublicInstant(F('race_datetime'),F('local_date'),F('local_start_time'),F('timezone_name'))).annotate(
        public_date=Coalesce(TruncDate('public_instant',tzinfo=BEIJING),Case(
            When(race_datetime__isnull=True,local_start_time__isnull=True,timezone_name='Asia/Shanghai',then=F('local_date')),
            output_field=DateField())),
        public_start_time=TruncTime('public_instant',tzinfo=BEIJING))
