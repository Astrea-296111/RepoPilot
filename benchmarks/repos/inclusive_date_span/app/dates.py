from datetime import date


def date_span_days(start: date, end: date) -> int:
    if end < start:
        raise ValueError("end before start")
    return (end - start).days
