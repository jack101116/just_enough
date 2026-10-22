"""Server-side validation. Every function returns (clean_data, errors)."""
import re
from datetime import date, datetime

MEAL_TYPES = ("breakfast", "lunch", "dinner", "snacks")
DIETARY_CATEGORIES = ("vegetarian", "vegan", "non_vegetarian")
DIETARY_LABELS = {"vegetarian": "Vegetarian", "vegan": "Vegan", "non_vegetarian": "Non-vegetarian"}
EVENT_TYPES = ("Wedding", "Corporate event", "Conference", "College fest", "Community meal",
               "Religious gathering", "Birthday / Party", "Other")
FOOD_CATEGORIES = ("Main course", "Rice & grains", "Bread", "Curry / Gravy", "Dal & lentils",
                   "Starter / Snack", "Dessert", "Beverage", "Salad / Sides", "Other")
DIETARY_TAGS = ("Vegan", "Jain", "Halal", "Gluten-free", "Nut-free", "Diabetic-friendly")
MEAL_LABELS = {m: m.capitalize() for m in MEAL_TYPES}


def clean_text(value, max_len):
    return re.sub(r"\s+", " ", (value or "")).strip()[:max_len]


def clean_multiline(value, max_len):
    return (value or "").replace("\r\n", "\n").strip()[:max_len]


def _number(raw, label, errors, key, low=None, high=None, integer=False, required=True):
    raw = (raw if raw is not None else "").strip() if isinstance(raw, str) else raw
    if raw in (None, ""):
        if required:
            errors[key] = f"{label} is required."
        return None
    try:
        value = float(raw)
        if value != value or value in (float("inf"), float("-inf")):
            raise ValueError
    except (TypeError, ValueError):
        errors[key] = f"{label} must be a number."
        return None
    if integer:
        if value != int(value):
            errors[key] = f"{label} must be a whole number."
            return None
        value = int(value)
    if low is not None and value < low:
        errors[key] = f"{label} must be at least {low}."
        return None
    if high is not None and value > high:
        errors[key] = f"{label} must be at most {high}."
        return None
    return value


def parse_date(raw):
    try:
        return datetime.strptime((raw or "").strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


def parse_datetime(raw):
    raw = (raw or "").strip()
    for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


def validate_event(form):
    errors = {}
    data = {
        "name": clean_text(form.get("name"), 120),
        "event_type": clean_text(form.get("event_type"), 60),
        "meal_type": (form.get("meal_type") or "").strip().lower(),
        "notes": clean_multiline(form.get("notes"), 2000),
    }
    if not data["name"]:
        errors["name"] = "Event name is required."
    if not data["event_type"]:
        errors["event_type"] = "Event type is required."
    if data["meal_type"] not in MEAL_TYPES:
        errors["meal_type"] = "Choose breakfast, lunch, dinner or snacks."
    d = parse_date(form.get("event_date"))
    if d is None:
        errors["event_date"] = "Enter a valid event date."
    elif d.year < 2000 or d.year > 2100:
        errors["event_date"] = "Event date must be between the years 2000 and 2100."
    data["event_date"] = d.isoformat() if d else ""
    data["expected_guests"] = _number(form.get("expected_guests"), "Expected guest count", errors,
                                      "expected_guests", 1, 100000, integer=True)
    data["registration_count"] = _number(form.get("registration_count") or "0", "Registration count", errors,
                                         "registration_count", 0, 100000, integer=True)
    data["confidence_pct"] = _number(form.get("confidence_pct") or "80", "Attendance confidence", errors,
                                     "confidence_pct", 0, 100)
    data["veg_percent"] = _number(form.get("veg_percent") or "40", "Vegetarian guests share", errors,
                                  "veg_percent", 0, 100)
    tags = form.getlist("dietary_tags") if hasattr(form, "getlist") else []
    data["dietary_tags"] = ",".join(t for t in tags if t in DIETARY_TAGS)
    return data, errors


def validate_dish(form):
    errors = {}
    data = {
        "name": clean_text(form.get("name"), 80),
        "food_category": clean_text(form.get("food_category"), 60) or "Other",
        "dietary_category": (form.get("dietary_category") or "").strip(),
    }
    if not data["name"]:
        errors["name"] = "Dish name is required."
    if data["dietary_category"] not in DIETARY_CATEGORIES:
        errors["dietary_category"] = "Choose vegetarian, vegan or non-vegetarian."
    data["default_portion_g"] = _number(form.get("portion_g"), "Portion size", errors, "portion_g", 1, 2000)
    data["default_rate_pct"] = _number(form.get("rate_pct"), "Consumption rate", errors, "rate_pct", 0, 100)
    data["default_cost_per_kg"] = _number(form.get("cost_per_kg"), "Cost per kg", errors, "cost_per_kg",
                                          0, 1000000, required=False)
    return data, errors


def validate_event_dish_row(portion, rate, cost, prefix=""):
    errors = {}
    data = {
        "portion_g": _number(portion, "Portion size", errors, prefix + "portion_g", 1, 2000),
        "rate_pct": _number(rate, "Consumption rate", errors, prefix + "rate_pct", 0, 100),
        "cost_per_kg": _number(cost, "Cost per kg", errors, prefix + "cost_per_kg", 0, 1000000, required=False),
    }
    return data, errors


def validate_ngo(form):
    errors = {}
    data = {
        "name": clean_text(form.get("name"), 140),
        "city": clean_text(form.get("city"), 80),
        "service_areas": clean_text(form.get("service_areas"), 300),
        "food_types": clean_text(form.get("food_types"), 200),
        "contact_person": clean_text(form.get("contact_person"), 80),
        "phone": clean_text(form.get("phone"), 40),
        "email": clean_text(form.get("email"), 120),
        "address": clean_text(form.get("address"), 240),
        "notes": clean_multiline(form.get("notes"), 500),
    }
    if not data["name"]:
        errors["name"] = "Organisation name is required."
    if data["email"] and not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", data["email"]):
        errors["email"] = "Enter a valid email address or leave it blank."
    if data["phone"] and not re.match(r"^[0-9+()\-\s]{5,40}$", data["phone"]):
        errors["phone"] = "Phone may contain digits, spaces, +, - and brackets only."
    return data, errors
