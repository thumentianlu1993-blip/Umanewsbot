"""公开北京日期/赛时合同：不修改来源身份时间，不推断缺失时区。"""
from dataclasses import dataclass
from contextvars import ContextVar
from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from django.db import connections
from django.db.models import Case, When, F, Func, DateTimeField, DateField
from django.db.models.functions import Coalesce, TruncDate, TruncTime
from django.db.models.sql import Query
from django.db.models.sql.compiler import SQLCompiler

BEIJING = ZoneInfo('Asia/Shanghai')

# 只在公开时间 SELECT 的编译期间复用目录；不跨 SQL 缓存业务数据或时区信息。
_TIMEZONE_CTE = '"__umanews_public_timezones"'
_timezone_scope = ContextVar('umanews_public_time_compile_scope', default=None)


class _PublicTimeSQLCompiler(SQLCompiler):
    def as_sql(self, *args, **kwargs):
        if _timezone_scope.get() is not None:
            return super().as_sql(*args, **kwargs)
        scope = {"used": False}
        token = _timezone_scope.set(scope)
        try:
            sql, params = super().as_sql(*args, **kwargs)
            if sql and scope["used"]:
                # Django 已将 EXPLAIN 放到 SELECT 前；它必须位于 WITH 外层。
                explain_prefix = ''
                if self.query.explain_info:
                    info = self.query.explain_info
                    explain_prefix = self.connection.ops.explain_query_prefix(
                        info.format, **info.options
                    ) + ' '
                    sql = sql.removeprefix(explain_prefix)
                sql = (f"WITH {_TIMEZONE_CTE} AS MATERIALIZED "
                       f"(SELECT name FROM pg_timezone_names) {sql}")
                sql = explain_prefix + sql
            return sql, params
        finally:
            _timezone_scope.reset(token)


class _PublicTimeQuery(Query):
    def get_compiler(self, using=None, connection=None, elide_empty=True):
        if connection is None:
            connection = connections[using]
        if connection.vendor == 'postgresql':
            return _PublicTimeSQLCompiler(self, connection, using, elide_empty)
        return super().get_compiler(using, connection, elide_empty)

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
        elif day:
            if clock is None:
                # date-only 赛事（无 UTC 时刻、无当地开赛时刻）：按当地赛日公开，
                # 九地区后不限于 Asia/Shanghai；不推断缺失时区的时刻。
                return PublicTime(day=day)
            if zone != 'Asia/Shanghai':
                return PublicTime()
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
        scope = _timezone_scope.get()
        if scope is not None:
            scope["used"] = True
        # 非专用 SELECT（例如 Django 的 UPDATE compiler）仍可独立编译表达式。
        directory = _TIMEZONE_CTE if scope is not None else 'pg_timezone_names'
        known=f"{zone} IN (SELECT name FROM {directory})"
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
        connection.ensure_connection()
        connection.connection.create_function('umanews_public_instant',4,convert,deterministic=True)
        return super().as_sql(compiler,connection,function='umanews_public_instant',**extra_context)


def annotate_public_time(queryset):
    queryset = queryset.all()
    queryset.query = queryset.query.chain(klass=_PublicTimeQuery)
    return queryset.annotate(public_instant=_PublicInstant(F('race_datetime'),F('local_date'),F('local_start_time'),F('timezone_name'))).annotate(
        public_date=Coalesce(TruncDate('public_instant',tzinfo=BEIJING),Case(
            # date-only 赛事（无 UTC 时刻、无当地开赛时刻）按当地赛日参与公开日期窗口；
            # 九地区后不再限于 Asia/Shanghai。当地开赛时刻存在时仍不推断时区。
            When(race_datetime__isnull=True,local_start_time__isnull=True,then=F('local_date')),
            output_field=DateField())),
        public_start_time=TruncTime('public_instant',tzinfo=BEIJING))
