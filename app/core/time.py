from datetime import datetime
from zoneinfo import ZoneInfo


GUATEMALA_TIMEZONE = ZoneInfo("America/Guatemala")


def fecha_actual_guatemala():
    return datetime.now(GUATEMALA_TIMEZONE).date()
