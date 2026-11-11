"""美国来源的统一到期策略；赛前完成和多源checkpoint共用。"""
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo


def next_poll(*, event, kind, now):
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError('us_poll_naive_clock')
    if kind not in {'race_time', 'racecard', 'result'}:
        raise ValueError('us_poll_kind')
    if event.status in {'cancelled', 'postponed'} or not event.local_date:
        return None
    zone = ZoneInfo(event.timezone_name)
    today = now.astimezone(zone).date()
    age = (today-event.local_date).days
    midnight = datetime.combine(today+timedelta(days=1), time(), tzinfo=zone)
    interval = timedelta(minutes=5 if event.priority in {'P0', 'P1'} else 10)
    if kind != 'result':
        if age > 0 or (event.race_datetime and now >= event.race_datetime+timedelta(minutes=5)):
            return None
        due = now + (interval if age == 0 else timedelta(hours=1 if age == -1 else 3))
        if age in {-2, -1, 0}:
            due = min(due, midnight)
        if event.race_datetime:
            due = min(due, event.race_datetime+timedelta(minutes=5))
        return due
    # 只有日期时允许检查完整的当地第七日；不得虚构开赛时刻。
    horizon = (event.race_datetime+timedelta(days=7) if event.race_datetime else
               datetime.combine(event.local_date+timedelta(days=8), time(), tzinfo=zone))
    if now >= horizon:
        return None
    if event.race_datetime and now < event.race_datetime+timedelta(minutes=3):
        return event.race_datetime+timedelta(minutes=3)
    if age < 0:
        return datetime.combine(event.local_date, time(), tzinfo=zone)
    if event.result_confirmed_at:
        due = now+timedelta(hours=6 if age < 2 else 24)
    else:
        due = now+(interval if age == 0 else timedelta(hours=6))
    return min(due, horizon)
