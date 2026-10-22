"""All web routes (one blueprint). Calculations and persistence happen here, on the server."""
import csv
import io

from flask import (Blueprint, Response, abort, flash, jsonify, redirect, render_template, request, url_for)

from . import donation_repo as drepo
from . import repository as repo
from .db import get_db
from .services import donations as dsvc
from .services.estimation import (ASSUMPTION_HELP, METHOD_NOTES, RANGES, parse_assumptions)
from .utils import validation as val

bp = Blueprint("main", __name__)


def _event_or_404(db, event_id):
    event = repo.get_event(db, event_id)
    if event is None:
        abort(404)
    return event


def _form_ctx():
    return {"event_types": val.EVENT_TYPES, "meal_types": val.MEAL_TYPES, "dietary_tags": val.DIETARY_TAGS,
            "food_categories": val.FOOD_CATEGORIES, "diet_categories": val.DIETARY_CATEGORIES}


# ------------------------------------------------------------------ home
@bp.route("/")
def index():
    db = get_db()
    stats, _ = repo.dashboard_stats(db)
    return render_template("index.html", stats=stats, recent=repo.list_events(db)[:3])


@bp.route("/dashboard")
def dashboard():
    db = get_db()
    stats, status_counts = repo.dashboard_stats(db)
    events = repo.list_events(db)
    return render_template("dashboard.html", stats=stats, status_counts=status_counts, events=events[:8],
                           chart_events=[e for e in events if e["total_kg"]][:8])


# ---------------------------------------------------------------- events
@bp.route("/events")
def events():
    q = request.args.get("q", "").strip()
    return render_template("events/list.html", events=repo.list_events(get_db(), q), q=q)


@bp.route("/events/new", methods=["GET", "POST"])
def event_new():
    db = get_db()
    catalog = repo.list_catalog(db)
    if request.method == "POST":
        data, errors = val.validate_event(request.form)
        valid_ids = {d["id"] for d in catalog}
        dish_ids = []
        for raw in request.form.getlist("dish_ids"):
            if raw.isdigit() and int(raw) in valid_ids:
                dish_ids.append(int(raw))
        if errors:
            flash("Please fix the highlighted fields.", "error")
            return render_template("events/form.html", form=request.form, errors=errors, catalog=catalog,
                                   selected=set(dish_ids), mode="new", **_form_ctx()), 400
        event_id = repo.create_event(db, data, dish_ids)
        flash("Event created. Review the planning assumptions below.", "success")
        return redirect(url_for("main.planner", event_id=event_id))
    defaults = {"confidence_pct": 80, "veg_percent": 40, "registration_count": 0, "meal_type": "lunch"}
    return render_template("events/form.html", form=defaults, errors={}, catalog=catalog, selected=set(),
                           mode="new", **_form_ctx())


@bp.route("/events/<int:event_id>")
def event_detail(event_id):
    db = get_db()
    event = _event_or_404(db, event_id)
    result = repo.compute_for_event(db, event, with_curve=False)
    return render_template("events/detail.html", event=event, result=result,
                           donations=drepo.list_donations(db, event_id), tags=[t for t in event["dietary_tags"].split(",") if t])


@bp.route("/events/<int:event_id>/edit", methods=["GET", "POST"])
def event_edit(event_id):
    db = get_db()
    event = _event_or_404(db, event_id)
    if request.method == "POST":
        data, errors = val.validate_event(request.form)
        if errors:
            flash("Please fix the highlighted fields.", "error")
            return render_template("events/form.html", form=request.form, errors=errors, catalog=[], selected=set(),
                                   mode="edit", event=event, **_form_ctx()), 400
        repo.update_event(db, event_id, data)
        flash("Event updated and estimates recalculated.", "success")
        return redirect(url_for("main.event_detail", event_id=event_id))
    form = dict(event)
    form["dietary_tags"] = event["dietary_tags"].split(",")
    return render_template("events/form.html", form=form, errors={}, catalog=[], selected=set(), mode="edit",
                           event=event, **_form_ctx())


@bp.route("/events/<int:event_id>/delete", methods=["POST"])
def event_delete(event_id):
    db = get_db()
    event = _event_or_404(db, event_id)
    repo.delete_event(db, event_id)
    flash(f"Event “{event['name']}” and its plans were deleted.", "success")
    return redirect(url_for("main.events"))


# --------------------------------------------------------------- planner
def parse_planner(event, dish_rows, data):
    """Parse planner inputs from a form or JSON mapping. Returns (assumptions, dishes, errors)."""
    base = repo.get_assumptions(get_db(), event)
    a, errors = parse_assumptions(data, base)
    dishes = []
    for row in dish_rows:
        key = row["event_dish_id"]
        clean, derr = val.validate_event_dish_row(
            str(data.get(f"ed_{key}_portion_g", row["portion_g"])),
            str(data.get(f"ed_{key}_rate_pct", row["rate_pct"])),
            str(data.get(f"ed_{key}_cost_per_kg", "" if row["cost_per_kg"] is None else row["cost_per_kg"])),
            prefix=f"ed_{key}_")
        errors.update(derr)
        item = dict(row)
        item.update(clean)
        dishes.append(item)
    return a, dishes, errors


@bp.route("/events/<int:event_id>/planner", methods=["GET", "POST"])
def planner(event_id):
    db = get_db()
    event = _event_or_404(db, event_id)
    rows = [dict(r) for r in repo.get_event_dishes(db, event_id)]
    errors = {}
    if request.method == "POST":
        a, dishes, errors = parse_planner(event, rows, request.form)
        if not errors:
            for d in dishes:
                repo.update_event_dish(db, event_id, d["event_dish_id"], d["portion_g"], d["rate_pct"], d["cost_per_kg"])
            repo.save_assumptions(db, event_id, a, commit=False)
            db.commit()
            repo.store_estimates(db, event_id)
            flash("Assumptions saved and recommendations recalculated.", "success")
            return redirect(url_for("main.planner", event_id=event_id))
        flash("Some values are invalid. Nothing was saved.", "error")
        status = 400
    else:
        a, dishes, status = repo.get_assumptions(db, event), rows, 200
    from .services.estimation import estimate_event
    result = estimate_event(event["expected_guests"], event["registration_count"], a, dishes) if not errors else \
        repo.compute_for_event(db, event)
    catalog = [d for d in repo.list_catalog(db) if d["id"] not in {r["dish_id"] for r in rows}]
    return render_template("planner/planner.html", event=event, result=result, a=a, errors=errors, catalog=catalog,
                           ranges=RANGES, help=ASSUMPTION_HELP, form=request.form if request.method == "POST" else {},
                           **_form_ctx()), status


@bp.route("/api/events/<int:event_id>/preview", methods=["POST"])
def preview(event_id):
    """Live recalculation using the same server-side engine (nothing is saved)."""
    db = get_db()
    event = _event_or_404(db, event_id)
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"ok": False, "errors": {"_": "Expected a JSON object."}}), 400
    rows = [dict(r) for r in repo.get_event_dishes(db, event_id)]
    a, dishes, errors = parse_planner(event, rows, payload)
    if errors:
        return jsonify({"ok": False, "errors": errors}), 400
    from .services.estimation import estimate_event
    return jsonify({"ok": True, "result": estimate_event(event["expected_guests"], event["registration_count"], a, dishes)})


@bp.route("/events/<int:event_id>/dishes/add", methods=["POST"])
def dish_add(event_id):
    db = get_db()
    _event_or_404(db, event_id)
    raw = request.form.get("dish_id", "")
    if raw.isdigit() and repo.add_dish_to_event(db, event_id, int(raw)):
        flash("Dish added to the plan.", "success")
    else:
        flash("That dish could not be added (it may already be in the plan).", "error")
    return redirect(url_for("main.planner", event_id=event_id))


@bp.route("/events/<int:event_id>/dishes/new", methods=["POST"])
def dish_new_for_event(event_id):
    db = get_db()
    _event_or_404(db, event_id)
    data, errors = val.validate_dish(request.form)
    if errors:
        flash(" ".join(errors.values()), "error")
        return redirect(url_for("main.planner", event_id=event_id))
    try:
        dish_id = repo.create_dish(db, data)
    except Exception:
        db.rollback()
        flash("A dish with that name already exists. Pick it from the list instead.", "error")
        return redirect(url_for("main.planner", event_id=event_id))
    repo.add_dish_to_event(db, event_id, dish_id)
    flash(f"Dish “{data['name']}” created and added.", "success")
    return redirect(url_for("main.planner", event_id=event_id))


@bp.route("/events/<int:event_id>/dishes/<int:event_dish_id>/delete", methods=["POST"])
def dish_remove(event_id, event_dish_id):
    db = get_db()
    _event_or_404(db, event_id)
    if repo.remove_event_dish(db, event_id, event_dish_id):
        flash("Dish removed from the plan.", "success")
    else:
        flash("Dish not found in this plan.", "error")
    return redirect(url_for("main.planner", event_id=event_id))


# ------------------------------------------------------------ dish catalog
@bp.route("/dishes", methods=["GET", "POST"])
def dishes():
    db = get_db()
    errors, form = {}, {}
    if request.method == "POST":
        data, errors = val.validate_dish(request.form)
        form = request.form
        if not errors:
            try:
                repo.create_dish(db, data)
                flash(f"Dish “{data['name']}” added to the catalogue.", "success")
                return redirect(url_for("main.dishes"))
            except Exception:
                db.rollback()
                errors["name"] = "A dish with this name already exists."
        flash("Please fix the highlighted fields.", "error")
    return render_template("planner/dishes.html", catalog=repo.list_catalog(db), errors=errors, form=form,
                           **_form_ctx()), (400 if errors else 200)


@bp.route("/dishes/<int:dish_id>/edit", methods=["GET", "POST"])
def dish_edit(dish_id):
    db = get_db()
    dish = repo.get_dish(db, dish_id)
    if dish is None:
        abort(404)
    errors = {}
    if request.method == "POST":
        data, errors = val.validate_dish(request.form)
        if not errors:
            try:
                repo.update_dish(db, dish_id, data)
                flash("Dish updated. Existing events keep their own saved portion, rate and cost.", "success")
                return redirect(url_for("main.dishes"))
            except Exception:
                db.rollback()
                errors["name"] = "A dish with this name already exists."
        flash("Please fix the highlighted fields.", "error")
        form = request.form
    else:
        form = {"name": dish["name"], "food_category": dish["food_category"], "dietary_category": dish["dietary_category"],
                "portion_g": dish["default_portion_g"], "rate_pct": dish["default_rate_pct"],
                "cost_per_kg": "" if dish["default_cost_per_kg"] is None else dish["default_cost_per_kg"]}
    return render_template("planner/dish_edit.html", dish=dish, errors=errors, form=form, **_form_ctx()), (400 if errors else 200)


@bp.route("/dishes/<int:dish_id>/delete", methods=["POST"])
def dish_delete(dish_id):
    db = get_db()
    if repo.get_dish(db, dish_id) is None:
        abort(404)
    if repo.delete_dish(db, dish_id):
        flash("Dish deleted from the catalogue.", "success")
    else:
        flash("This dish is used in one or more events, so it cannot be deleted.", "error")
    return redirect(url_for("main.dishes"))


# ------------------------------------------------------------------ risk
@bp.route("/events/<int:event_id>/risk")
def risk(event_id):
    db = get_db()
    event = _event_or_404(db, event_id)
    result = repo.compute_for_event(db, event)
    return render_template("planner/risk.html", event=event, result=result, a=repo.get_assumptions(db, event),
                           ranges=RANGES, help=ASSUMPTION_HELP)


@bp.route("/events/<int:event_id>/risk/apply", methods=["POST"])
def risk_apply(event_id):
    db = get_db()
    event = _event_or_404(db, event_id)
    a, errors = parse_assumptions({"shortage_risk_pct": request.form.get("shortage_risk_pct")},
                                  repo.get_assumptions(db, event))
    if errors:
        flash(" ".join(errors.values()), "error")
        return redirect(url_for("main.risk", event_id=event_id))
    repo.save_assumptions(db, event_id, a)
    repo.store_estimates(db, event_id)
    flash(f"Shortage-risk setting saved at {a.shortage_risk_pct:g}% and quantities recalculated.", "success")
    return redirect(url_for("main.risk", event_id=event_id))


# -------------------------------------------------------------- donations
def _ngo_ids(db):
    return {r["id"] for r in db.execute("SELECT id FROM ngos")}


def _donation_form_response(db, event, mode, form, errors, donation=None, status=200):
    result = repo.compute_for_event(db, event, with_curve=False)
    selected_items = {}
    if donation is not None and not form:
        selected_items = {i["event_dish_id"]: i["quantity_kg"] for i in drepo.get_items(db, donation["id"])}
    ngos = repo.search_ngos(db)
    return render_template("donations/form.html", event=event, result=result, ngos=ngos, errors=errors,
                           form=form, mode=mode, donation=donation, selected_items=selected_items,
                           disclaimer=dsvc.DISCLAIMER), status


@bp.route("/events/<int:event_id>/donations/new", methods=["GET", "POST"])
def donation_new(event_id):
    db = get_db()
    event = _event_or_404(db, event_id)
    if request.method == "POST":
        result = repo.compute_for_event(db, event, with_curve=False)
        data, items, errors = drepo.parse_donation_form(request.form, result["dishes"], _ngo_ids(db))
        if errors:
            flash("Please fix the highlighted fields.", "error")
            return _donation_form_response(db, event, "new", request.form, errors, status=400)
        did = drepo.create_donation(db, event, data, items, repo.get_ngo(db, data["ngo_id"]) if data["ngo_id"] else None)
        flash("Donation plan saved as Draft. Nothing has been sent to any NGO.", "success")
        return redirect(url_for("main.donation_detail", donation_id=did))
    return _donation_form_response(db, event, "new", {}, {})


@bp.route("/donations")
def donations():
    status = request.args.get("status", "")
    if status not in dsvc.STATUSES:
        status = ""
    return render_template("donations/list.html", donations=drepo.list_donations(get_db(), status=status), status=status)


@bp.route("/donations/<int:donation_id>")
def donation_detail(donation_id):
    db = get_db()
    d = drepo.get_donation(db, donation_id)
    if d is None:
        abort(404)
    items = drepo.get_items(db, donation_id)
    window = dsvc.safety_window(val.parse_datetime(d["prepared_at"]), val.parse_datetime(d["handoff_deadline"]))
    options = []
    for new in dsvc.TRANSITIONS[d["status"]]:
        ok, reason = dsvc.can_transition(d["status"], new, d, len(items))
        options.append({"status": new, "label": dsvc.TRANSITION_HINTS[new], "ok": ok, "reason": reason})
    return render_template("donations/detail.html", d=d, items=items, window=window, options=options,
                           log=drepo.get_log(db, donation_id), ngo=repo.get_ngo(db, d["ngo_id"]) if d["ngo_id"] else None,
                           editable=d["status"] in dsvc.EDITABLE_STATUSES, disclaimer=dsvc.DISCLAIMER,
                           total_kg=sum(i["quantity_kg"] for i in items))


@bp.route("/donations/<int:donation_id>/edit", methods=["GET", "POST"])
def donation_edit(donation_id):
    db = get_db()
    d = drepo.get_donation(db, donation_id)
    if d is None:
        abort(404)
    if d["status"] not in dsvc.EDITABLE_STATUSES:
        flash("Completed or cancelled donations cannot be edited.", "error")
        return redirect(url_for("main.donation_detail", donation_id=donation_id))
    event = repo.get_event(db, d["event_id"])
    if request.method == "POST":
        result = repo.compute_for_event(db, event, with_curve=False)
        data, items, errors = drepo.parse_donation_form(request.form, result["dishes"], _ngo_ids(db))
        if errors:
            flash("Please fix the highlighted fields.", "error")
            return _donation_form_response(db, event, "edit", request.form, errors, d, 400)
        drepo.update_donation(db, donation_id, event, data, items, repo.get_ngo(db, data["ngo_id"]) if data["ngo_id"] else None)
        flash("Donation plan updated.", "success")
        return redirect(url_for("main.donation_detail", donation_id=donation_id))
    form = {"prepared_at": d["prepared_at"], "handoff_deadline": d["handoff_deadline"], "ngo_id": d["ngo_id"],
            "pickup_notes": d["pickup_notes"]}
    return _donation_form_response(db, event, "edit", form, {}, d)


@bp.route("/donations/<int:donation_id>/status", methods=["POST"])
def donation_status(donation_id):
    db = get_db()
    d = drepo.get_donation(db, donation_id)
    if d is None:
        abort(404)
    new = request.form.get("new_status", "")
    items = drepo.get_items(db, donation_id)
    ok, reason = dsvc.can_transition(d["status"], new, d, len(items))
    if not ok:
        flash(reason, "error")
        return redirect(url_for("main.donation_detail", donation_id=donation_id)), 303
    event = repo.get_event(db, d["event_id"])
    drepo.change_status(db, donation_id, event, repo.get_ngo(db, d["ngo_id"]) if d["ngo_id"] else None,
                        new, request.form.get("note", ""))
    flash(f"Status recorded: {dsvc.TRANSITION_HINTS[new]}.", "success")
    return redirect(url_for("main.donation_detail", donation_id=donation_id))


@bp.route("/donations/<int:donation_id>/delete", methods=["POST"])
def donation_delete(donation_id):
    db = get_db()
    d = drepo.get_donation(db, donation_id)
    if d is None:
        abort(404)
    if d["status"] not in ("draft", "cancelled"):
        flash("Only Draft or Cancelled donation plans can be deleted.", "error")
        return redirect(url_for("main.donation_detail", donation_id=donation_id))
    drepo.delete_donation(db, donation_id)
    flash("Donation plan deleted.", "success")
    return redirect(url_for("main.donations"))


@bp.route("/donations/<int:donation_id>/summary")
def donation_summary(donation_id):
    db = get_db()
    d = drepo.get_donation(db, donation_id)
    if d is None:
        abort(404)
    return render_template("donations/summary.html", d=d)


# ------------------------------------------------------------------- NGOs
@bp.route("/ngos")
def ngos():
    db = get_db()
    q, city, food = (request.args.get(k, "").strip() for k in ("q", "city", "food"))
    return render_template("ngos/list.html", ngos=repo.search_ngos(db, q, city, food), cities=repo.ngo_cities(db),
                           q=q, city=city, food=food)


@bp.route("/ngos/new", methods=["GET", "POST"])
def ngo_new():
    errors = {}
    if request.method == "POST":
        data, errors = val.validate_ngo(request.form)
        if not errors:
            nid = repo.create_ngo(get_db(), data)
            flash("Organisation added to your directory. Please verify its details independently.", "success")
            return redirect(url_for("main.ngo_detail", ngo_id=nid))
        flash("Please fix the highlighted fields.", "error")
    return render_template("ngos/form.html", errors=errors, form=request.form), (400 if errors else 200)


@bp.route("/ngos/<int:ngo_id>")
def ngo_detail(ngo_id):
    db = get_db()
    ngo = repo.get_ngo(db, ngo_id)
    if ngo is None:
        abort(404)
    return render_template("ngos/detail.html", ngo=ngo)


# ---------------------------------------------------------------- reports
@bp.route("/reports")
def reports():
    db = get_db()
    events = repo.list_events(db)
    latest = {}
    for d in drepo.list_donations(db):
        latest.setdefault(d["event_id"], d["status"])
    return render_template("reports/list.html", events=events, latest=latest,
                           calc={e["id"]: repo.last_calculated(db, e["id"]) for e in events})


@bp.route("/events/<int:event_id>/report")
def report(event_id):
    db = get_db()
    event = _event_or_404(db, event_id)
    result = repo.compute_for_event(db, event)
    donations = []
    for d in drepo.list_donations(db, event_id):
        donations.append({"d": d, "lines": drepo.get_items(db, d["id"])})
    return render_template("reports/report.html", event=event, result=result, donations=donations,
                           tags=[t for t in event["dietary_tags"].split(",") if t], notes=METHOD_NOTES,
                           calculated=repo.last_calculated(db, event_id), help=ASSUMPTION_HELP,
                           disclaimer=dsvc.DISCLAIMER)


def _csv_safe(value):
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return value


@bp.route("/events/<int:event_id>/report.csv")
def report_csv(event_id):
    db = get_db()
    event = _event_or_404(db, event_id)
    r = repo.compute_for_event(db, event, with_curve=False)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Just Enough event report (estimates, not guarantees)"])
    for label, value in (("Event", event["name"]), ("Type", event["event_type"]), ("Date", event["event_date"]),
                         ("Meal", event["meal_type"]), ("Expected guests", event["expected_guests"]),
                         ("Registrations", event["registration_count"]),
                         ("Estimated attendance", r["attendance"]["estimated_attendance"])):
        w.writerow([label, _csv_safe(value)])
    for key, value in r["assumptions"].items():
        w.writerow([f"Assumption: {key}", value])
    w.writerow([])
    w.writerow(["Dish", "Category", "Dietary", "Portion g", "Rate %", "Expected servings", "Recommended servings",
                "Recommended kg", "Expected leftover kg", "Food cost", "Surplus cost"])
    for d in r["dishes"]:
        w.writerow([_csv_safe(d["name"]), _csv_safe(d["food_category"]), d["dietary_category"], d["portion_g"],
                    d["rate_pct"], d["expected_servings"], d["recommended_servings"], d["recommended_kg"],
                    d["expected_leftover_kg"], "" if d["food_cost"] is None else d["food_cost"],
                    "" if d["surplus_cost"] is None else d["surplus_cost"]])
    t = r["totals"]
    w.writerow(["TOTAL", "", "", "", "", "", t["recommended_servings"], t["recommended_kg"],
                t["expected_leftover_kg"], "" if t["food_cost"] is None else t["food_cost"],
                "" if t["surplus_cost"] is None else t["surplus_cost"]])
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename=just_enough_event_{event_id}.csv"})
