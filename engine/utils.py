import datetime
from datetime import timezone, timedelta

IST = timezone(timedelta(hours=5, minutes=30))

def get_now_utc():
    """Get current time in UTC (naive for DB storage)."""
    return datetime.datetime.now(timezone.utc).replace(tzinfo=None)

def get_now_ist():
    """Get current time in IST (tz-aware)."""
    return datetime.datetime.now(IST)

def to_ist(dt):
    """Convert a datetime object (naive or aware) to IST."""
    if dt is None:
        return None

    # Handle string input (from SQLite)
    if isinstance(dt, str):
        try:
            dt = dt.replace(' ', 'T')
            if dt.endswith('Z'):
                dt = dt[:-1] + '+00:00'
            dt = datetime.datetime.fromisoformat(dt)
        except Exception:
            return dt

    if hasattr(dt, 'tzinfo') and dt.tzinfo is None:
        # convention: naive in DB is UTC
        dt = dt.replace(tzinfo=timezone.utc)

    if hasattr(dt, 'astimezone'):
        return dt.astimezone(IST)
    return dt

def format_timestamp(dt):
    """Format a datetime object for the UI."""
    ist_dt = to_ist(dt)
    if ist_dt is None:
        return "-"
    if not isinstance(ist_dt, datetime.datetime):
        return str(ist_dt)
    return ist_dt.strftime('%H:%M:%S')

def ist_to_utc_naive(dt):
    """Convert an IST datetime (aware or naive) to UTC naive for DB."""
    if dt is None: return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=IST)
    return dt.astimezone(timezone.utc).replace(tzinfo=None)
