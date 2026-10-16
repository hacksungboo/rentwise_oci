from __future__ import annotations

from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))


def parse(s: str | None) -> datetime | None:
    if s is None:
        return None
    d = datetime.fromisoformat(s)
    if d.tzinfo is None:  # SQLite 등에서 tz 없이 돌아온 값은 UTC로 간주
        d = d.replace(tzinfo=timezone.utc)
    return d


def iso(d: datetime | None) -> str | None:
    """API/계약용: Asia/Seoul 오프셋 ISO8601"""
    if d is None:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(KST).isoformat()


def to_db(s: str | datetime | None) -> datetime | None:
    """DB 저장용: UTC 기준 naive datetime (DB 컬럼은 TIMESTAMP, 의미는 항상 UTC).

    Oracle 드라이버별 TIMESTAMP WITH TIME ZONE 바인딩 차이를 피하려고 UTC naive 로 통일한다.
    읽을 때 parse()/iso() 가 naive 를 UTC 로 해석한다.
    """
    if s is None:
        return None
    d = parse(s) if isinstance(s, str) else s
    if d.tzinfo is None:
        return d
    return d.astimezone(timezone.utc).replace(tzinfo=None)


def now() -> datetime:
    """DB 기록용 현재 시각 (UTC naive)"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def overlaps(a0: datetime, a1: datetime | None, b0: datetime, b1: datetime | None) -> bool:
    """[a0,a1) 와 [b0,b1) 겹침. None 끝 = 무기한"""
    far = datetime.max.replace(tzinfo=timezone.utc)
    return a0 < (b1 or far) and b0 < (a1 or far)


def plus(s: str, minutes: int) -> str:
    return iso(parse(s) + timedelta(minutes=minutes))
