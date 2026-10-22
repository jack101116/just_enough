"""Jinja filters for readable numbers, money and dates."""
from datetime import datetime


def kg(value, digits=1):
    if value is None:
        return "–"
    return f"{value:,.{digits}f} kg"


def num(value, digits=0):
    if value is None:
        return "–"
    return f"{value:,.{digits}f}"


def pct(value, digits=0):
    if value is None:
        return "–"
    return f"{value:.{digits}f}%"


def fmt_date(value):
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d").strftime("%d %b %Y")
    except (TypeError, ValueError):
        return value or "–"


def fmt_datetime(value):
    try:
        return datetime.strptime(value[:16].replace(" ", "T"), "%Y-%m-%dT%H:%M").strftime("%d %b %Y, %H:%M")
    except (TypeError, ValueError):
        return value or "–"


STATUS_LABELS = {
    "draft": "Draft",
    "ready_for_contact": "Ready for Contact",
    "contacted": "Contacted",
    "accepted": "Accepted",
    "completed": "Completed",
    "cancelled": "Cancelled",
}


def status_label(value):
    return STATUS_LABELS.get(value, value or "–")


def diet_label(value):
    return {"vegetarian": "Vegetarian", "vegan": "Vegan", "non_vegetarian": "Non-vegetarian"}.get(value, value)
