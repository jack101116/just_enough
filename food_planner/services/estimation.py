"""Food quantity estimation engine (pure Python, no database access).

METHOD (documented so every number can be traced)
-------------------------------------------------
Inputs that are KNOWN (entered by the organiser):
    expected guests N, registrations, portion size per dish, participation
    rate per dish, optional cost per kg, vegetarian share of guests.

Assumptions that are ESTIMATES (editable, each with a valid range):
    confidence_pct      0-100   How sure the organiser is of the headcount N.
                                It does NOT shift the mean; it widens the
                                uncertainty (see below). 100 = no extra doubt.
    no_show_rate_pct    0-90    Share of the N guests expected NOT to attend.
    shortage_risk_pct   1-40    Acceptable chance a dish runs short.
    safety_buffer_pct   0-50    Extra explicit cushion added on top of the
                                risk-based quantity (default 0, so that the
                                same protection is never added twice).
    portion_adjust_pct  -30-50  Global scaling of every dish's portion size.
    veg_percent         0-100   Share of guests who eat only vegetarian food.

Steps:
 1. Attendance mean   mu = N * (1 - no_show)
 2. Attendance spread var_A = N*p*(1-p)            (binomial show-up, p = 1-no_show)
                          + (K * (1-confidence) * mu)^2   (headcount doubt)
                      where K = 0.25 is a documented modelling constant: with
                      0% confidence the headcount is assumed uncertain by one
                      standard deviation of 25% of mu. K is NOT calibrated.
 3. Dish pool         f = 1 for vegetarian / vegan dishes (everyone may eat),
                      f = 1 - veg% for non-vegetarian dishes.
 4. Dish demand       mean  m = mu * f * r            (r = participation rate)
                      var   v = mu*f*r*(1-r) + (f*r)^2 * var_A
 5. Risk quantity     Q = m + z * sqrt(v),  z = Phi^-1(1 - risk)   (normal approx.)
 6. Buffer            servings = ceil(Q * (1 + buffer))
 7. Weight            kg = servings * portion_g * (1 + portion_adjust) / 1000
 8. Expected leftover E[max(servings - D, 0)] from the same normal model.
 9. Cost              kg * cost_per_kg (only when a cost is entered).

LIMITS: This is a transparent planning model under a normal approximation. The
reported "modelled shortage probability" is a model output, NOT a statistically
calibrated probability. Validate against real attendance records before relying
on it for large events.
"""
import math
from dataclasses import dataclass, asdict
from statistics import NormalDist

UNCERTAINTY_K = 0.25
RISK_LEVELS = (1, 2, 5, 10, 15, 20, 30, 40)

RANGES = {
    "confidence_pct": (0, 100, "Attendance confidence"),
    "no_show_rate_pct": (0, 90, "No-show rate"),
    "shortage_risk_pct": (1, 40, "Acceptable shortage risk"),
    "safety_buffer_pct": (0, 50, "Safety buffer"),
    "portion_adjust_pct": (-30, 50, "Portion size adjustment"),
    "veg_percent": (0, 100, "Vegetarian guests share"),
}

ASSUMPTION_HELP = {
    "confidence_pct": "How sure you are of the expected guest count. Lower confidence widens the uncertainty range (it does not lower the average).",
    "no_show_rate_pct": "Share of expected guests who will not turn up. Lowers the average attendance.",
    "shortage_risk_pct": "How often you accept a dish running short. Lower risk means more food (and more potential surplus).",
    "safety_buffer_pct": "Extra cushion on top of the risk-based quantity. Leave at 0 to avoid double protection.",
    "portion_adjust_pct": "Scales every portion size up or down (e.g. smaller plates, buffet vs. plated).",
    "veg_percent": "Share of guests who eat only vegetarian food. Non-vegetarian dishes are sized for the remaining guests.",
}

METHOD_NOTES = [
    "All quantities are estimates from a documented planning model, not guarantees.",
    "Attendance confidence widens the uncertainty range; it does not change the average attendance.",
    "The shortage-risk setting uses a normal approximation with an uncalibrated uncertainty constant (K=0.25). "
    "The reported shortage probability is a model output, not a calibrated probability.",
    "Expected leftover is the modelled average over many similar events, not a prediction for this one.",
    "Costs are shown only for dishes where a cost per kg was entered.",
]


@dataclass
class Assumptions:
    confidence_pct: float = 80.0
    no_show_rate_pct: float = 10.0
    shortage_risk_pct: float = 10.0
    safety_buffer_pct: float = 0.0
    portion_adjust_pct: float = 0.0
    veg_percent: float = 40.0

    def as_dict(self):
        return asdict(self)


def _to_float(value):
    if isinstance(value, bool):
        raise ValueError
    if isinstance(value, str):
        value = value.strip()
        if value == "":
            raise ValueError
    number = float(value)
    if math.isnan(number) or math.isinf(number):
        raise ValueError
    return number


def parse_assumptions(raw, base=None):
    """Validate a mapping of assumption values. Returns (Assumptions, errors)."""
    values = (base or Assumptions()).as_dict()
    errors = {}
    for key, (low, high, label) in RANGES.items():
        if raw is None or key not in raw or raw[key] in (None, ""):
            continue
        try:
            number = _to_float(raw[key])
        except (TypeError, ValueError):
            errors[key] = f"{label} must be a number."
            continue
        if not low <= number <= high:
            errors[key] = f"{label} must be between {low} and {high}."
            continue
        values[key] = number
    return Assumptions(**values), errors


def _phi(x):
    return math.exp(-0.5 * x * x) / math.sqrt(2 * math.pi)


def expected_leftover_servings(servings, mean, sd):
    """E[max(servings - D, 0)] for D ~ Normal(mean, sd)."""
    if sd <= 1e-9:
        return max(servings - mean, 0.0)
    d = (servings - mean) / sd
    return (servings - mean) * NormalDist().cdf(d) + sd * _phi(d)


def attendance_model(expected_guests, a):
    show = 1 - a.no_show_rate_pct / 100
    mu = expected_guests * show
    var_binomial = expected_guests * show * (1 - show)
    sd_doubt = UNCERTAINTY_K * (1 - a.confidence_pct / 100) * mu
    var = var_binomial + sd_doubt ** 2
    return mu, var


def _dish_row(dish, mu, var_a, a):
    r = dish["rate_pct"] / 100
    f = (1 - a.veg_percent / 100) if dish["dietary_category"] == "non_vegetarian" else 1.0
    mean = mu * f * r
    variance = mu * f * r * (1 - r) + (f * r) ** 2 * var_a
    sd = math.sqrt(max(variance, 0.0))
    z = NormalDist().inv_cdf(1 - a.shortage_risk_pct / 100)
    q_risk = max(mean + z * sd, 0.0)
    servings = math.ceil(round(q_risk * (1 + a.safety_buffer_pct / 100), 9))
    portion = dish["portion_g"] * (1 + a.portion_adjust_pct / 100)
    kg = servings * portion / 1000
    leftover_servings = expected_leftover_servings(servings, mean, sd)
    leftover_kg = leftover_servings * portion / 1000
    if sd <= 1e-9:
        shortage_prob = 0.0 if servings >= mean else 1.0
    else:
        shortage_prob = 1 - NormalDist().cdf((servings - mean) / sd)
    cost = dish.get("cost_per_kg")
    food_cost = kg * cost if cost is not None else None
    surplus_cost = leftover_kg * cost if cost is not None else None
    eligible = mu * f
    explanation = (
        f"About {eligible:.0f} attending guests can eat this dish and ~{dish['rate_pct']:.0f}% of them are expected "
        f"to take it, so average demand is ~{mean:.0f} servings. To keep shortage risk near "
        f"{a.shortage_risk_pct:.0f}% the plan adds a cushion of {z:.2f} standard deviations "
        f"(~{sd:.1f} servings each)"
        + (f" plus a {a.safety_buffer_pct:.0f}% safety buffer" if a.safety_buffer_pct else "")
        + f", giving {servings} servings of {portion:.0f} g = {kg:.2f} kg."
    )
    return {
        "event_dish_id": dish.get("event_dish_id"),
        "name": dish["name"],
        "food_category": dish.get("food_category", ""),
        "dietary_category": dish["dietary_category"],
        "portion_g": dish["portion_g"],
        "effective_portion_g": round(portion, 2),
        "rate_pct": dish["rate_pct"],
        "cost_per_kg": cost,
        "eligible_guests": round(eligible, 2),
        "expected_servings": round(mean, 2),
        "sd_servings": round(sd, 2),
        "required_servings": round(mean, 2),
        "recommended_servings": servings,
        "recommended_kg": round(kg, 3),
        "expected_demand_kg": round(mean * portion / 1000, 3),
        "expected_leftover_servings": round(leftover_servings, 2),
        "expected_leftover_kg": round(leftover_kg, 3),
        "modelled_shortage_pct": round(shortage_prob * 100, 1),
        "food_cost": round(food_cost, 2) if food_cost is not None else None,
        "surplus_cost": round(surplus_cost, 2) if surplus_cost is not None else None,
        "explanation": explanation,
    }


def _totals(rows):
    priced = [r for r in rows if r["food_cost"] is not None]
    return {
        "recommended_servings": sum(r["recommended_servings"] for r in rows),
        "recommended_kg": round(sum(r["recommended_kg"] for r in rows), 3),
        "expected_demand_kg": round(sum(r["expected_demand_kg"] for r in rows), 3),
        "expected_leftover_kg": round(sum(r["expected_leftover_kg"] for r in rows), 3),
        "food_cost": round(sum(r["food_cost"] for r in priced), 2) if priced else None,
        "surplus_cost": round(sum(r["surplus_cost"] for r in priced), 2) if priced else None,
        "cost_dishes": len(priced),
        "total_dishes": len(rows),
        "cost_complete": bool(rows) and len(priced) == len(rows),
    }


def estimate_event(expected_guests, registration_count, assumptions, dishes, with_curve=True):
    """Run the full estimate. `dishes` are dicts with name, dietary_category,
    portion_g, rate_pct and optional cost_per_kg / event_dish_id / food_category."""
    a = assumptions
    mu, var_a = attendance_model(expected_guests, a)
    rows = [_dish_row(d, mu, var_a, a) for d in dishes]
    warnings = []
    if not dishes:
        warnings.append("No dishes have been added yet, so no food quantities can be calculated.")
    if registration_count and registration_count > expected_guests:
        warnings.append(
            f"Registrations ({registration_count}) exceed the expected guest count ({expected_guests}). "
            "Check whether the expected count should be higher."
        )
    if a.confidence_pct < 50:
        warnings.append("Attendance confidence is low, so quantities include a wide uncertainty cushion.")
    if expected_guests < 30:
        warnings.append("For small groups the normal approximation is rough; consider a manual check.")
    if dishes and any(r["cost_per_kg"] is None for r in rows):
        warnings.append("Some dishes have no cost per kg, so cost totals only cover dishes with a cost.")
    result = {
        "assumptions": a.as_dict(),
        "attendance": {
            "expected_guests": expected_guests,
            "registration_count": registration_count,
            "estimated_attendance": round(mu, 2),
            "attendance_sd": round(math.sqrt(var_a), 2),
            "attendance_low": round(max(mu - 1.28 * math.sqrt(var_a), 0), 1),
            "attendance_high": round(mu + 1.28 * math.sqrt(var_a), 1),
        },
        "dishes": rows,
        "totals": _totals(rows),
        "warnings": warnings,
        "notes": METHOD_NOTES,
    }
    if with_curve:
        result["curve"] = risk_curve(expected_guests, registration_count, a, dishes)
    return result


def risk_curve(expected_guests, registration_count, assumptions, dishes):
    """Totals at standard risk levels (plus the selected level) for the trade-off view."""
    levels = sorted(set(RISK_LEVELS) | {assumptions.shortage_risk_pct})
    curve = []
    for level in levels:
        a = Assumptions(**{**assumptions.as_dict(), "shortage_risk_pct": level})
        res = estimate_event(expected_guests, registration_count, a, dishes, with_curve=False)
        t = res["totals"]
        curve.append({
            "risk_pct": level,
            "selected": level == assumptions.shortage_risk_pct,
            "recommended_kg": t["recommended_kg"],
            "expected_leftover_kg": t["expected_leftover_kg"],
            "food_cost": t["food_cost"],
            "surplus_cost": t["surplus_cost"],
        })
    return curve
