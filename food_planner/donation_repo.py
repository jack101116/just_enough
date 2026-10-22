"""Donation persistence and validation helpers."""
from .repository import now
from .services import donations as svc
from .utils.validation import parse_datetime, clean_multiline


def get_donation(db, donation_id):
    return db.execute(
        """SELECT d.*, e.name AS event_name, e.event_date, n.name AS ngo_name, n.city AS ngo_city
           FROM donations d JOIN events e ON e.id = d.event_id
           LEFT JOIN ngos n ON n.id = d.ngo_id WHERE d.id = ?""", (donation_id,)).fetchone()


def get_items(db, donation_id):
    return db.execute("SELECT * FROM donation_items WHERE donation_id = ? ORDER BY id", (donation_id,)).fetchall()


def get_log(db, donation_id):
    return db.execute("SELECT * FROM donation_status_log WHERE donation_id = ? ORDER BY id DESC", (donation_id,)).fetchall()


def list_donations(db, event_id=None, status=""):
    sql = """SELECT d.*, e.name AS event_name, n.name AS ngo_name,
                    (SELECT ROUND(SUM(quantity_kg),2) FROM donation_items di WHERE di.donation_id = d.id) AS total_kg
             FROM donations d JOIN events e ON e.id = d.event_id LEFT JOIN ngos n ON n.id = d.ngo_id WHERE 1=1"""
    params = []
    if event_id:
        sql += " AND d.event_id = ?"
        params.append(event_id)
    if status:
        sql += " AND d.status = ?"
        params.append(status)
    sql += " ORDER BY d.updated_at DESC, d.id DESC"
    return db.execute(sql, params).fetchall()


def parse_donation_form(form, estimate_rows, valid_ngo_ids):
    """Validate a donation form. estimate_rows: result['dishes'] for the event."""
    errors = {}
    prepared = parse_datetime(form.get("prepared_at"))
    deadline = parse_datetime(form.get("handoff_deadline"))
    if prepared is None:
        errors["prepared_at"] = "Enter when the food was (or will be) prepared."
    if deadline is None:
        errors["handoff_deadline"] = "Enter the proposed serving or handoff deadline."
    if prepared and deadline and deadline <= prepared:
        errors["handoff_deadline"] = "The handoff deadline must be after the preparation time."
    ngo_raw = (form.get("ngo_id") or "").strip()
    ngo_id = None
    if ngo_raw:
        try:
            ngo_id = int(ngo_raw)
        except ValueError:
            ngo_id = -1
        if ngo_id not in valid_ngo_ids:
            errors["ngo_id"] = "Choose an NGO from the directory."
    if form.get("safety_ack") != "on":
        errors["safety_ack"] = "Please confirm you have read the food-safety guidance."
    items = []
    for row in estimate_rows:
        key = row["event_dish_id"]
        if form.get(f"include_{key}") != "on":
            continue
        raw = (form.get(f"qty_{key}") or "").strip()
        try:
            qty = float(raw)
        except ValueError:
            errors[f"qty_{key}"] = f"Quantity for {row['name']} must be a number."
            continue
        if qty != qty or qty <= 0:
            errors[f"qty_{key}"] = f"Quantity for {row['name']} must be greater than 0."
            continue
        if qty > row["recommended_kg"] + 1e-9:
            errors[f"qty_{key}"] = (f"Quantity for {row['name']} cannot exceed the {row['recommended_kg']:.2f} kg "
                                    "planned for this dish.")
            continue
        items.append({"event_dish_id": key, "dish_name": row["name"], "food_category": row["food_category"],
                      "quantity_kg": round(qty, 3), "estimated_leftover_kg": row["expected_leftover_kg"]})
    if not items and "items" not in errors and not any(k.startswith("qty_") for k in errors):
        errors["items"] = "Select at least one dish and enter the surplus quantity available."
    data = {"prepared": prepared, "deadline": deadline, "ngo_id": ngo_id,
            "pickup_notes": clean_multiline(form.get("pickup_notes"), 500),
            "safety_ack": 1 if form.get("safety_ack") == "on" else 0}
    return data, items, errors


def _write_items(db, donation_id, items):
    db.execute("DELETE FROM donation_items WHERE donation_id = ?", (donation_id,))
    for it in items:
        db.execute(
            """INSERT INTO donation_items (donation_id, event_dish_id, dish_name, food_category, quantity_kg,
               estimated_leftover_kg) VALUES (?,?,?,?,?,?)""",
            (donation_id, it["event_dish_id"], it["dish_name"], it["food_category"], it["quantity_kg"],
             it["estimated_leftover_kg"]))


def _refresh_summary(db, donation_id, event, ngo):
    d = db.execute("SELECT * FROM donations WHERE id = ?", (donation_id,)).fetchone()
    items = get_items(db, donation_id)
    prepared, deadline = parse_datetime(d["prepared_at"]), parse_datetime(d["handoff_deadline"])
    window = svc.safety_window(prepared, deadline)
    text = svc.build_summary(event, ngo, items, prepared, deadline, d["status"], d["pickup_notes"], window)
    db.execute("UPDATE donations SET summary_text = ?, updated_at = ? WHERE id = ?", (text, now(), donation_id))


def create_donation(db, event, data, items, ngo):
    ts = now()
    cur = db.execute(
        """INSERT INTO donations (event_id, ngo_id, status, prepared_at, handoff_deadline, safety_acknowledged,
           pickup_notes, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)""",
        (event["id"], data["ngo_id"], "draft", data["prepared"].strftime("%Y-%m-%dT%H:%M"),
         data["deadline"].strftime("%Y-%m-%dT%H:%M"), data["safety_ack"], data["pickup_notes"], ts, ts))
    did = cur.lastrowid
    _write_items(db, did, items)
    db.execute("INSERT INTO donation_status_log (donation_id, from_status, to_status, note, changed_at) VALUES (?,?,?,?,?)",
               (did, None, "draft", "Donation plan created", ts))
    _refresh_summary(db, did, event, ngo)
    db.commit()
    return did


def update_donation(db, donation_id, event, data, items, ngo):
    db.execute(
        """UPDATE donations SET ngo_id=?, prepared_at=?, handoff_deadline=?, safety_acknowledged=?, pickup_notes=?,
           updated_at=? WHERE id=?""",
        (data["ngo_id"], data["prepared"].strftime("%Y-%m-%dT%H:%M"), data["deadline"].strftime("%Y-%m-%dT%H:%M"),
         data["safety_ack"], data["pickup_notes"], now(), donation_id))
    _write_items(db, donation_id, items)
    _refresh_summary(db, donation_id, event, ngo)
    db.commit()


def change_status(db, donation_id, event, ngo, new_status, note):
    d = db.execute("SELECT status FROM donations WHERE id = ?", (donation_id,)).fetchone()
    ts = now()
    db.execute("UPDATE donations SET status = ?, updated_at = ? WHERE id = ?", (new_status, ts, donation_id))
    db.execute("INSERT INTO donation_status_log (donation_id, from_status, to_status, note, changed_at) VALUES (?,?,?,?,?)",
               (donation_id, d["status"], new_status, clean_multiline(note, 300), ts))
    _refresh_summary(db, donation_id, event, ngo)
    db.commit()


def delete_donation(db, donation_id):
    db.execute("DELETE FROM donations WHERE id = ?", (donation_id,))
    db.commit()
