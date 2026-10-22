"""Donation workflow: food-safety guidance, status rules, summary text.

Food-safety timing here is GENERAL GUIDANCE ONLY. It is not certified food-safety
advice. Organisers must follow local regulations and the receiving organisation's
requirements. A donation is never shown as accepted/completed unless a person has
recorded that status.
"""
from datetime import datetime

DISCLAIMER = (
    "Food-safety timing shown here is general guidance, not certified food-safety advice. "
    "Cooked food should be kept hot (above about 60 °C / 140 °F) or chilled, and handed over as quickly as "
    "possible. Follow your local food-safety rules and the receiving organisation's requirements. "
    "The receiving organisation decides whether it can accept the food."
)

STATUSES = ("draft", "ready_for_contact", "contacted", "accepted", "completed", "cancelled")

TRANSITIONS = {
    "draft": ("ready_for_contact", "cancelled"),
    "ready_for_contact": ("draft", "contacted", "cancelled"),
    "contacted": ("ready_for_contact", "accepted", "cancelled"),
    "accepted": ("completed", "cancelled"),
    "completed": (),
    "cancelled": (),
}

TRANSITION_HINTS = {
    "draft": "Move back to Draft",
    "ready_for_contact": "Mark Ready for Contact",
    "contacted": "Record: NGO has been contacted",
    "accepted": "Record: NGO accepted",
    "completed": "Record: handoff completed",
    "cancelled": "Cancel donation",
}

EDITABLE_STATUSES = ("draft", "ready_for_contact", "contacted")


def safety_window(prepared_at, deadline):
    """Classify the time between preparation and the handoff deadline."""
    if prepared_at is None or deadline is None:
        return {"hours": None, "level": "unknown", "message": "Enter both times to see guidance."}
    hours = (deadline - prepared_at).total_seconds() / 3600
    if hours <= 0:
        return {"hours": hours, "level": "error", "message": "The handoff deadline must be after the preparation time."}
    if hours <= 2:
        level, msg = "ok", "Short holding window. Keep food hot or chilled until handoff."
    elif hours <= 4:
        level, msg = "caution", ("Holding window is over 2 hours. Take extra care with temperature control "
                                 "and consider an earlier handoff.")
    else:
        level, msg = "warning", ("Holding window is over 4 hours. Many food-safety guidelines advise against "
                                 "donating perishable cooked food held this long. Check local rules or choose an earlier handoff.")
    return {"hours": round(hours, 1), "level": level, "message": msg}


def can_transition(current, new, donation, items_count):
    """Return (allowed, reason)."""
    if new not in TRANSITIONS.get(current, ()):
        return False, f"A donation cannot move from {current.replace('_', ' ')} to {new.replace('_', ' ')}."
    if new in ("ready_for_contact", "contacted", "accepted", "completed"):
        if donation["ngo_id"] is None:
            return False, "Select an NGO before moving the donation forward."
        if items_count == 0:
            return False, "Add at least one food item first."
        if not donation["safety_acknowledged"]:
            return False, "The food-safety disclaimer must be acknowledged first."
    return True, ""


def build_summary(event, ngo, items, prepared_at, deadline, status, pickup_notes, window):
    lines = [
        "FOOD SURPLUS DONATION SUMMARY",
        "",
        f"Event: {event['name']} ({event['event_type']}), {event['event_date']}",
        f"Meal: {event['meal_type'].capitalize()}",
        f"Food prepared at: {prepared_at.strftime('%d %b %Y, %H:%M')}",
        f"Proposed handoff deadline: {deadline.strftime('%d %b %Y, %H:%M')}"
        + (f" ({window['hours']} h after preparation)" if window.get("hours") is not None else ""),
        "",
        "Food available:",
    ]
    total = 0.0
    for it in items:
        lines.append(f"  - {it['dish_name']} ({it['food_category']}): {it['quantity_kg']:.2f} kg")
        total += it["quantity_kg"]
    lines.append(f"  Total: {total:.2f} kg")
    lines.append("")
    if ngo is not None:
        lines.append(f"Proposed recipient: {ngo['name']}" + (f", {ngo['city']}" if ngo["city"] else ""))
        if ngo["is_sample"]:
            lines.append("  (Sample directory entry. Verify contact details independently.)")
    else:
        lines.append("Proposed recipient: not selected yet")
    if pickup_notes:
        lines.append(f"Pickup notes: {pickup_notes}")
    lines += [
        "",
        f"Status recorded in this app: {status.replace('_', ' ').title()}",
        "This status is only a record kept by the organiser. It does not mean any NGO has agreed to collect the food "
        "unless the status shows Accepted or Completed.",
        "",
        "Food-safety note: " + DISCLAIMER,
    ]
    return "\n".join(lines)
