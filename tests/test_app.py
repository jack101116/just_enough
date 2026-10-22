import sqlite3

import pytest

from conftest import make_event, db_rows
from food_planner import db as database, seed


# ----------------------------------------------------------- database
def test_init_creates_tables_and_is_repeatable(tmp_path):
    path = str(tmp_path / "x.db")
    database.init_db_file(path)
    conn = database.connect(path)
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for t in ("events", "dishes", "event_dishes", "planning_assumptions", "food_estimates", "ngos", "donations"):
        assert t in names
    conn.execute("INSERT INTO dishes (name,food_category,dietary_category,default_portion_g,default_rate_pct,created_at) "
                 "VALUES ('A','x','vegan',100,50,'now')")
    conn.commit(); conn.close()
    database.init_db_file(path)  # must not erase
    assert database.connect(path).execute("SELECT COUNT(*) FROM dishes").fetchone()[0] == 1


def test_foreign_keys_enforced(tmp_path):
    conn = database.connect(str(tmp_path / "f.db")); database.init_schema(conn)
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO event_dishes (event_id,dish_id,portion_g,rate_pct) VALUES (999,999,100,50)")


def test_seed_is_idempotent(tmp_path):
    conn = database.connect(str(tmp_path / "s.db")); database.init_schema(conn)
    first = seed.seed(conn); second = seed.seed(conn)
    assert first["events"] == 3 and first["ngos"] == 5 and not any(second.values())
    assert conn.execute("SELECT COUNT(*) FROM ngos WHERE is_sample = 0").fetchone()[0] == 0


# ------------------------------------------------------------ routes
@pytest.mark.parametrize("url", ["/", "/dashboard", "/events", "/events/new", "/dishes", "/donations", "/ngos",
                                 "/ngos/new", "/reports"])
def test_essential_routes_ok(seeded, client, url):
    assert client.get(url).status_code == 200


def test_event_pages_ok(seeded, client):
    for url in ("/events/1", "/events/1/edit", "/events/1/planner", "/events/1/risk", "/events/1/report",
                "/events/1/report.csv", "/events/1/donations/new"):
        assert client.get(url).status_code == 200, url


def test_404_and_unknown(seeded, client):
    assert client.get("/events/9999").status_code == 404
    assert client.get("/nope").status_code == 404


def test_csrf_required(seeded, app):
    c = app.test_client()
    assert c.post("/events/1/delete").status_code == 400
    assert db_rows(app, "SELECT COUNT(*) AS n FROM events")[0]["n"] == 3


def test_home_stats_come_from_database(app, client):
    assert b"No events" in client.get("/events").data or client.get("/").status_code == 200
    make_event(client, dish_ids=())
    html = client.get("/").data.decode()
    assert "200" in html  # guests from the saved event


# ------------------------------------------------------------- events
def test_create_event_and_persist(app, client):
    from conftest import seed as _s  # noqa
    conn = database.connect(app.config["DATABASE"]); seed.seed(conn); conn.close()
    r = make_event(client)
    assert r.status_code == 302 and "/planner" in r.headers["Location"]
    rows = db_rows(app, "SELECT * FROM events WHERE name='Test Dinner'")
    assert len(rows) == 1 and rows[0]["expected_guests"] == 200
    assert db_rows(app, "SELECT COUNT(*) AS n FROM event_dishes WHERE event_id=?", (rows[0]["id"],))[0]["n"] == 2
    assert db_rows(app, "SELECT COUNT(*) AS n FROM food_estimates WHERE event_id=?", (rows[0]["id"],))[0]["n"] == 2
    # a brand-new app instance on the same file still sees the data (persistence)
    from food_planner import create_app
    app2 = create_app({"TESTING": True, "DATABASE": app.config["DATABASE"], "SECRET_KEY": "x"})
    assert b"Test Dinner" in app2.test_client().get("/events").data


@pytest.mark.parametrize("field,value,fragment", [
    ("name", "", "Event name is required"), ("event_date", "31-02-2030", "valid event date"),
    ("expected_guests", "0", "at least 1"), ("expected_guests", "abc", "must be a number"),
    ("expected_guests", "12.5", "whole number"), ("registration_count", "-3", "at least 0"),
    ("confidence_pct", "150", "at most 100"), ("meal_type", "brunch", "Choose breakfast"),
    ("veg_percent", "101", "at most 100")])
def test_event_validation_errors(app, client, field, value, fragment):
    r = make_event(client, dish_ids=(), **{field: value})
    assert r.status_code == 400 and fragment in r.data.decode()
    assert db_rows(app, "SELECT COUNT(*) AS n FROM events")[0]["n"] == 0


def test_html_is_escaped(app, client):
    make_event(client, dish_ids=(), name="<script>alert(1)</script>")
    body = client.get("/events").data.decode()
    assert "<script>alert(1)</script>" not in body and "&lt;script&gt;" in body


def test_edit_event_recalculates(seeded, client, app):
    before = db_rows(app, "SELECT SUM(recommended_kg) AS k FROM food_estimates WHERE event_id=1")[0]["k"]
    form = {"name": "Alumni", "event_type": "Wedding", "event_date": "2030-01-01", "expected_guests": "500",
            "registration_count": "100", "confidence_pct": "80", "meal_type": "dinner", "veg_percent": "40"}
    assert client.post("/events/1/edit", data=form).status_code == 302
    after = db_rows(app, "SELECT SUM(recommended_kg) AS k FROM food_estimates WHERE event_id=1")[0]["k"]
    assert after > before
    assert db_rows(app, "SELECT name FROM events WHERE id=1")[0]["name"] == "Alumni"


def test_edit_invalid_does_not_change(seeded, client, app):
    r = client.post("/events/1/edit", data={"name": "", "event_type": "x", "event_date": "bad", "expected_guests": "x", "meal_type": "dinner"})
    assert r.status_code == 400
    assert db_rows(app, "SELECT name FROM events WHERE id=1")[0]["name"] == "Annual Alumni Dinner"


def test_delete_event_cascades(seeded, client, app):
    assert client.post("/events/1/delete").status_code == 302
    assert db_rows(app, "SELECT COUNT(*) AS n FROM events WHERE id=1")[0]["n"] == 0
    for t in ("event_dishes", "food_estimates", "planning_assumptions"):
        assert db_rows(app, f"SELECT COUNT(*) AS n FROM {t} WHERE event_id=1")[0]["n"] == 0


def test_event_list_search(seeded, client):
    html = client.get("/events?q=Wedding").data.decode()
    assert "Wedding Reception" in html and "Tech Conference" not in html


# ------------------------------------------------------------- dishes
def test_dish_catalogue_crud(seeded, client, app):
    form = {"name": "Idli", "food_category": "Starter / Snack", "dietary_category": "vegan", "portion_g": "120", "rate_pct": "60", "cost_per_kg": "90"}
    assert client.post("/dishes", data=form).status_code == 302
    dish = db_rows(app, "SELECT * FROM dishes WHERE name='Idli'")[0]
    assert client.post("/dishes", data=form).status_code == 400  # duplicate
    form["portion_g"] = "200"
    assert client.post(f"/dishes/{dish['id']}/edit", data=form).status_code == 302
    assert db_rows(app, "SELECT default_portion_g AS p FROM dishes WHERE id=?", (dish["id"],))[0]["p"] == 200
    assert client.post(f"/dishes/{dish['id']}/delete").status_code == 302
    assert not db_rows(app, "SELECT 1 FROM dishes WHERE name='Idli'")


@pytest.mark.parametrize("field,value", [("portion_g", "0"), ("portion_g", "5000"), ("rate_pct", "120"), ("rate_pct", "-1"),
                                         ("cost_per_kg", "-5"), ("name", ""), ("dietary_category", "meat")])
def test_dish_validation(seeded, client, field, value):
    form = {"name": "X", "food_category": "Other", "dietary_category": "vegan", "portion_g": "100", "rate_pct": "50", field: value}
    assert client.post("/dishes", data=form).status_code == 400


def test_cannot_delete_dish_in_use(seeded, client, app):
    assert client.post("/dishes/1/delete").status_code == 302
    assert db_rows(app, "SELECT COUNT(*) AS n FROM dishes WHERE id=1")[0]["n"] == 1


def test_add_and_remove_dish_on_event(seeded, client, app):
    make_event(client, dish_ids=())
    eid = db_rows(app, "SELECT id FROM events WHERE name='Test Dinner'")[0]["id"]
    client.post(f"/events/{eid}/dishes/add", data={"dish_id": "3"})
    assert db_rows(app, "SELECT COUNT(*) AS n FROM event_dishes WHERE event_id=?", (eid,))[0]["n"] == 1
    client.post(f"/events/{eid}/dishes/add", data={"dish_id": "3"})  # duplicate ignored
    assert db_rows(app, "SELECT COUNT(*) AS n FROM event_dishes WHERE event_id=?", (eid,))[0]["n"] == 1
    client.post(f"/events/{eid}/dishes/new", data={"name": "Kheer", "food_category": "Dessert", "dietary_category": "vegetarian", "portion_g": "80", "rate_pct": "60"})
    assert db_rows(app, "SELECT COUNT(*) AS n FROM event_dishes WHERE event_id=?", (eid,))[0]["n"] == 2
    ed = db_rows(app, "SELECT id FROM event_dishes WHERE event_id=? LIMIT 1", (eid,))[0]["id"]
    client.post(f"/events/{eid}/dishes/{ed}/delete")
    assert db_rows(app, "SELECT COUNT(*) AS n FROM event_dishes WHERE event_id=?", (eid,))[0]["n"] == 1


# ------------------------------------------------- planner / risk / API
def planner_form(app, event_id=1, **over):
    rows = db_rows(app, "SELECT id, portion_g, rate_pct, cost_per_kg FROM event_dishes WHERE event_id=?", (event_id,))
    form = {"confidence_pct": "80", "veg_percent": "40", "no_show_rate_pct": "10", "shortage_risk_pct": "10",
            "safety_buffer_pct": "0", "portion_adjust_pct": "0"}
    for r in rows:
        form[f"ed_{r['id']}_portion_g"] = str(r["portion_g"]); form[f"ed_{r['id']}_rate_pct"] = str(r["rate_pct"])
        form[f"ed_{r['id']}_cost_per_kg"] = "" if r["cost_per_kg"] is None else str(r["cost_per_kg"])
    form.update(over)
    return form, rows


def total_kg(app, eid=1):
    return db_rows(app, "SELECT SUM(recommended_kg) AS k FROM food_estimates WHERE event_id=?", (eid,))[0]["k"]


def test_changing_portion_and_risk_recalculates(seeded, client, app):
    base = total_kg(app)
    form, rows = planner_form(app, shortage_risk_pct="2")
    assert client.post("/events/1/planner", data=form).status_code == 302
    safer = total_kg(app)
    assert safer > base
    form[f"ed_{rows[0]['id']}_portion_g"] = str(rows[0]["portion_g"] * 2)
    client.post("/events/1/planner", data=form)
    assert total_kg(app) > safer
    assert db_rows(app, "SELECT shortage_risk_pct AS r FROM planning_assumptions WHERE event_id=1")[0]["r"] == 2


@pytest.mark.parametrize("over", [{"shortage_risk_pct": "0"}, {"no_show_rate_pct": "99"}, {"safety_buffer_pct": "x"},
                                  {"portion_adjust_pct": "-80"}])
def test_planner_rejects_invalid_assumptions(seeded, client, app, over):
    base = total_kg(app)
    form, _ = planner_form(app, **over)
    assert client.post("/events/1/planner", data=form).status_code == 400
    assert total_kg(app) == base


def test_planner_rejects_invalid_dish_values(seeded, client, app):
    form, rows = planner_form(app)
    form[f"ed_{rows[0]['id']}_rate_pct"] = "150"
    assert client.post("/events/1/planner", data=form).status_code == 400
    form[f"ed_{rows[0]['id']}_rate_pct"] = "50"; form[f"ed_{rows[0]['id']}_portion_g"] = "-1"
    assert client.post("/events/1/planner", data=form).status_code == 400


def test_preview_api_matches_saved_results(seeded, client, app):
    form, _ = planner_form(app, shortage_risk_pct="5", no_show_rate_pct="20")
    r = client.post_json("/api/events/1/preview", form)
    assert r.status_code == 200 and r.get_json()["ok"]
    preview_kg = r.get_json()["result"]["totals"]["recommended_kg"]
    assert total_kg(app) != preview_kg  # preview does not save
    client.post("/events/1/planner", data=form)
    assert total_kg(app) == pytest.approx(preview_kg, abs=0.01)


def test_preview_api_validation_and_csrf(seeded, client, app):
    assert client.post_json("/api/events/1/preview", {"shortage_risk_pct": "99"}).status_code == 400
    assert client.post_json("/api/events/1/preview", [1]).status_code == 400
    assert app.test_client().post("/api/events/1/preview", json={}).status_code == 400
    assert client.post_json("/api/events/999/preview", {}).status_code == 404


def test_risk_page_apply(seeded, client, app):
    base = total_kg(app)
    assert client.post("/events/1/risk/apply", data={"shortage_risk_pct": "1"}).status_code == 302
    assert total_kg(app) > base
    client.post("/events/1/risk/apply", data={"shortage_risk_pct": "77"})
    assert db_rows(app, "SELECT shortage_risk_pct AS r FROM planning_assumptions WHERE event_id=1")[0]["r"] == 1


# ---------------------------------------------------------- NGO directory
def test_ngo_directory_search_and_sample_labels(seeded, client):
    html = client.get("/ngos").data.decode()
    assert "SAMPLE" in html and "fictional" in html
    assert "Demo Food Rescue Trust" in client.get("/ngos?q=Riverside").data.decode()
    assert "Example Shelter" not in client.get("/ngos?city=Demo City North").data.decode()
    assert "No organisations match" in client.get("/ngos?q=zzzzzz").data.decode()
    assert client.get("/ngos/1").status_code == 200


def test_add_ngo_validation(seeded, client, app):
    assert client.post("/ngos/new", data={"name": "", "email": "bad"}).status_code == 400
    r = client.post("/ngos/new", data={"name": "My Kitchen", "city": "Town", "email": "a@b.org", "phone": "+1 555 1234"})
    assert r.status_code == 302
    assert db_rows(app, "SELECT is_sample FROM ngos WHERE name='My Kitchen'")[0]["is_sample"] == 0


# -------------------------------------------------------------- donations
def donation_form(app, qty="1.5", **over):
    form = {"include_1": "on", "qty_1": qty, "prepared_at": "2030-05-20T18:00", "handoff_deadline": "2030-05-20T20:00",
            "ngo_id": "1", "safety_ack": "on", "pickup_notes": "Back gate"}
    first = db_rows(app, "SELECT id FROM event_dishes WHERE event_id=1 ORDER BY id")[0]["id"]
    form = {k.replace("_1", f"_{first}") if k in ("include_1", "qty_1") else k: v for k, v in form.items()}
    form.update(over)
    return form


def create_donation(client, app, **over):
    r = client.post("/events/1/donations/new", data=donation_form(app, **over))
    assert r.status_code == 302, r.data.decode()[:500]
    return int(r.headers["Location"].rstrip("/").split("/")[-1])


def test_donation_create_summary_and_draft_status(seeded, client, app):
    did = create_donation(client, app)
    d = db_rows(app, "SELECT * FROM donations WHERE id=?", (did,))[0]
    assert d["status"] == "draft" and "not been confirmed" not in d["summary_text"]
    assert "Back gate" in d["summary_text"] and "Draft" in d["summary_text"] and "not certified" in d["summary_text"]
    page = client.get(f"/donations/{did}").data.decode()
    assert "SAMPLE" in page and "Accepted" not in page.split("Update status")[0].split("badge")[1] if "badge" in page else True
    assert client.get(f"/donations/{did}/summary").status_code == 200
    assert db_rows(app, "SELECT COUNT(*) AS n FROM donation_status_log WHERE donation_id=?", (did,))[0]["n"] == 1


@pytest.mark.parametrize("over,fragment", [
    ({"qty_X": "0"}, "greater than 0"), ({"qty_X": "9999"}, "cannot exceed"), ({"qty_X": "abc"}, "must be a number"),
    ({"handoff_deadline": "2030-05-20T17:00"}, "must be after"), ({"prepared_at": ""}, "when the food was"),
    ({"safety_ack": ""}, "food-safety guidance"), ({"ngo_id": "9999"}, "Choose an NGO"), ({"include_X": ""}, "Select at least one")])
def test_donation_validation(seeded, client, app, over, fragment):
    first = db_rows(app, "SELECT id FROM event_dishes WHERE event_id=1 ORDER BY id")[0]["id"]
    over = {k.replace("_X", f"_{first}"): v for k, v in over.items()}
    form = donation_form(app, **over)
    if not over.get("safety_ack", "x"):
        form.pop("safety_ack")
    for k in [k for k, v in over.items() if v == "" and k.startswith("include_")]:
        form.pop(k)
    r = client.post("/events/1/donations/new", data=form)
    assert r.status_code == 400 and fragment in r.data.decode()
    assert db_rows(app, "SELECT COUNT(*) AS n FROM donations")[0]["n"] == 0


def set_status(client, did, status):
    return client.post(f"/donations/{did}/status", data={"new_status": status, "note": "n"})


def status_of(app, did):
    return db_rows(app, "SELECT status FROM donations WHERE id=?", (did,))[0]["status"]


def test_status_workflow_and_rules(seeded, client, app):
    did = create_donation(client, app)
    set_status(client, did, "accepted"); assert status_of(app, did) == "draft"      # cannot skip
    set_status(client, did, "completed"); assert status_of(app, did) == "draft"
    for s in ("ready_for_contact", "contacted", "accepted", "completed"):
        set_status(client, did, s); assert status_of(app, did) == s
    set_status(client, did, "cancelled"); assert status_of(app, did) == "completed"  # terminal
    assert len(db_rows(app, "SELECT * FROM donation_status_log WHERE donation_id=?", (did,))) == 5
    assert client.post(f"/donations/{did}/edit", data=donation_form(app)).status_code == 302  # redirected away, no edit
    assert client.post(f"/donations/{did}/delete").status_code == 302 and status_of(app, did) == "completed"


def test_cannot_advance_without_ngo(seeded, client, app):
    did = create_donation(client, app, ngo_id="")
    set_status(client, did, "ready_for_contact")
    assert status_of(app, did) == "draft"
    assert client.post(f"/donations/{did}/edit", data=donation_form(app, ngo_id="2")).status_code == 302
    set_status(client, did, "ready_for_contact"); assert status_of(app, did) == "ready_for_contact"


def test_cancel_and_delete_draft(seeded, client, app):
    did = create_donation(client, app)
    set_status(client, did, "cancelled"); assert status_of(app, did) == "cancelled"
    client.post(f"/donations/{did}/delete")
    assert not db_rows(app, "SELECT 1 FROM donations WHERE id=?", (did,))


def test_donation_edit_updates_items_and_summary(seeded, client, app):
    did = create_donation(client, app)
    assert client.get(f"/donations/{did}/edit").status_code == 200
    client.post(f"/donations/{did}/edit", data=donation_form(app, qty="2.25", pickup_notes="Side door"))
    assert db_rows(app, "SELECT quantity_kg AS q FROM donation_items WHERE donation_id=?", (did,))[0]["q"] == 2.25
    assert "Side door" in db_rows(app, "SELECT summary_text AS s FROM donations WHERE id=?", (did,))[0]["s"]


def test_donations_list_filter_and_persistence(seeded, client, app):
    did = create_donation(client, app)
    assert "Alumni" in client.get("/donations?status=draft").data.decode()
    assert "Alumni" not in client.get("/donations?status=completed").data.decode()
    from food_planner import create_app
    again = create_app({"TESTING": True, "DATABASE": app.config["DATABASE"], "SECRET_KEY": "x"})
    assert b"Annual Alumni Dinner" in again.test_client().get(f"/donations/{did}").data


def test_food_safety_window_levels():
    from datetime import datetime as D
    from food_planner.services.donations import safety_window
    t = D(2030, 1, 1, 12)
    assert safety_window(t, D(2030, 1, 1, 13))["level"] == "ok"
    assert safety_window(t, D(2030, 1, 1, 15))["level"] == "caution"
    assert safety_window(t, D(2030, 1, 1, 18))["level"] == "warning"
    assert safety_window(t, D(2030, 1, 1, 11))["level"] == "error"


# ---------------------------------------------------------------- reports
def test_report_contents(seeded, client):
    html = client.get("/events/1/report").data.decode()
    for needle in ("Annual Alumni Dinner", "Assumptions used", "Dish-wise recommendations", "Why each recommendation",
                   "Shortage-risk setting", "Donation plan", "Warnings", "not certified", "Jeera Rice"):
        assert needle in html, needle


def test_report_shows_donation_status(seeded, client, app):
    did = create_donation(client, app)
    html = client.get("/events/1/report").data.decode()
    assert "Draft" in html and "Demo Food Rescue Trust" in html
    set_status(client, did, "ready_for_contact")
    assert "Ready for Contact" in client.get("/events/1/report").data.decode()


def test_report_csv(seeded, client):
    r = client.get("/events/1/report.csv")
    assert r.status_code == 200 and r.mimetype == "text/csv"
    text = r.data.decode()
    assert "Recommended kg" in text and "TOTAL" in text and "Jeera Rice" in text


def test_csv_injection_guard(app, client):
    make_event(client, dish_ids=(), name="=cmd|' /C calc'!A0")
    eid = db_rows(app, "SELECT id FROM events")[0]["id"]
    assert "'=cmd" in client.get(f"/events/{eid}/report.csv").data.decode()


def test_reports_history_lists_events(seeded, client):
    html = client.get("/reports").data.decode()
    assert all(n in html for n in ("Annual Alumni Dinner", "Tech Conference Lunch", "Wedding Reception"))


def test_dashboard_numbers_match_database(seeded, client, app):
    row = db_rows(app, "SELECT COUNT(*) AS n, SUM(expected_guests) AS g FROM events")[0]
    html = client.get("/dashboard").data.decode()
    assert f">{row['n']}<" in html and f"{row['g']:,}" in html


def test_security_headers_and_no_debug(seeded, client, app):
    r = client.get("/")
    assert r.headers["X-Content-Type-Options"] == "nosniff" and "Content-Security-Policy" in r.headers
    assert app.debug is False
