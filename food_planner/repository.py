"""Data-access layer. All SQL is parameterised."""
import sqlite3
from datetime import datetime

from .services.estimation import Assumptions, estimate_event


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------------- events
def create_event(db, data, dish_ids=()):
    ts = now()
    cur = db.execute(
        """INSERT INTO events (name, event_type, event_date, expected_guests, registration_count,
           confidence_pct, meal_type, veg_percent, dietary_tags, notes, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (data["name"], data["event_type"], data["event_date"], data["expected_guests"],
         data["registration_count"], data["confidence_pct"], data["meal_type"], data["veg_percent"],
         data["dietary_tags"], data["notes"], ts, ts),
    )
    event_id = cur.lastrowid
    db.execute("INSERT INTO planning_assumptions (event_id, updated_at) VALUES (?, ?)", (event_id, ts))
    for dish_id in dish_ids:
        add_dish_to_event(db, event_id, dish_id, commit=False)
    db.commit()
    store_estimates(db, event_id)
    return event_id


def update_event(db, event_id, data):
    db.execute(
        """UPDATE events SET name=?, event_type=?, event_date=?, expected_guests=?, registration_count=?,
           confidence_pct=?, meal_type=?, veg_percent=?, dietary_tags=?, notes=?, updated_at=? WHERE id=?""",
        (data["name"], data["event_type"], data["event_date"], data["expected_guests"],
         data["registration_count"], data["confidence_pct"], data["meal_type"], data["veg_percent"],
         data["dietary_tags"], data["notes"], now(), event_id),
    )
    db.commit()
    store_estimates(db, event_id)


def get_event(db, event_id):
    return db.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()


def delete_event(db, event_id):
    db.execute("DELETE FROM events WHERE id = ?", (event_id,))
    db.commit()


def list_events(db, search=""):
    sql = """SELECT e.*,
                (SELECT COUNT(*) FROM event_dishes ed WHERE ed.event_id = e.id) AS dish_count,
                (SELECT ROUND(SUM(recommended_kg),2) FROM food_estimates fe WHERE fe.event_id = e.id) AS total_kg,
                (SELECT ROUND(SUM(expected_leftover_kg),2) FROM food_estimates fe WHERE fe.event_id = e.id) AS leftover_kg
             FROM events e"""
    params = []
    if search:
        sql += " WHERE e.name LIKE ? OR e.event_type LIKE ?"
        params += [f"%{search}%", f"%{search}%"]
    sql += " ORDER BY e.event_date DESC, e.id DESC"
    return db.execute(sql, params).fetchall()


# ---------------------------------------------------------------- dishes
def list_catalog(db):
    return db.execute("SELECT * FROM dishes ORDER BY food_category, name").fetchall()


def get_dish(db, dish_id):
    return db.execute("SELECT * FROM dishes WHERE id = ?", (dish_id,)).fetchone()


def create_dish(db, data):
    cur = db.execute(
        """INSERT INTO dishes (name, food_category, dietary_category, default_portion_g, default_rate_pct,
           default_cost_per_kg, created_at) VALUES (?,?,?,?,?,?,?)""",
        (data["name"], data["food_category"], data["dietary_category"], data["default_portion_g"],
         data["default_rate_pct"], data["default_cost_per_kg"], now()),
    )
    db.commit()
    return cur.lastrowid


def update_dish(db, dish_id, data):
    db.execute(
        """UPDATE dishes SET name=?, food_category=?, dietary_category=?, default_portion_g=?,
           default_rate_pct=?, default_cost_per_kg=? WHERE id=?""",
        (data["name"], data["food_category"], data["dietary_category"], data["default_portion_g"],
         data["default_rate_pct"], data["default_cost_per_kg"], dish_id),
    )
    db.commit()


def delete_dish(db, dish_id):
    """Returns False if the dish is still used by an event."""
    try:
        db.execute("DELETE FROM dishes WHERE id = ?", (dish_id,))
        db.commit()
        return True
    except sqlite3.IntegrityError:
        db.rollback()
        return False


def add_dish_to_event(db, event_id, dish_id, commit=True):
    dish = get_dish(db, dish_id)
    if dish is None:
        return None
    try:
        cur = db.execute(
            """INSERT INTO event_dishes (event_id, dish_id, portion_g, rate_pct, cost_per_kg)
               VALUES (?,?,?,?,?)""",
            (event_id, dish_id, dish["default_portion_g"], dish["default_rate_pct"], dish["default_cost_per_kg"]),
        )
    except sqlite3.IntegrityError:
        db.rollback()
        return None
    if commit:
        db.commit()
        store_estimates(db, event_id)
    return cur.lastrowid


def remove_event_dish(db, event_id, event_dish_id):
    cur = db.execute("DELETE FROM event_dishes WHERE id = ? AND event_id = ?", (event_dish_id, event_id))
    db.commit()
    store_estimates(db, event_id)
    return cur.rowcount > 0


def update_event_dish(db, event_id, event_dish_id, portion_g, rate_pct, cost_per_kg):
    db.execute(
        "UPDATE event_dishes SET portion_g=?, rate_pct=?, cost_per_kg=? WHERE id=? AND event_id=?",
        (portion_g, rate_pct, cost_per_kg, event_dish_id, event_id),
    )


def get_event_dishes(db, event_id):
    return db.execute(
        """SELECT ed.id AS event_dish_id, ed.event_id, ed.dish_id, ed.portion_g, ed.rate_pct, ed.cost_per_kg,
                  d.name, d.food_category, d.dietary_category
           FROM event_dishes ed JOIN dishes d ON d.id = ed.dish_id
           WHERE ed.event_id = ? ORDER BY d.food_category, d.name""",
        (event_id,),
    ).fetchall()


# ----------------------------------------------------------- assumptions
def get_assumptions(db, event):
    row = db.execute("SELECT * FROM planning_assumptions WHERE event_id = ?", (event["id"],)).fetchone()
    base = Assumptions(confidence_pct=event["confidence_pct"], veg_percent=event["veg_percent"])
    if row is None:
        return base
    return Assumptions(
        confidence_pct=event["confidence_pct"],
        no_show_rate_pct=row["no_show_rate_pct"],
        shortage_risk_pct=row["shortage_risk_pct"],
        safety_buffer_pct=row["safety_buffer_pct"],
        portion_adjust_pct=row["portion_adjust_pct"],
        veg_percent=event["veg_percent"],
    )


def save_assumptions(db, event_id, a, commit=True):
    db.execute(
        """INSERT INTO planning_assumptions (event_id, no_show_rate_pct, shortage_risk_pct, safety_buffer_pct,
           portion_adjust_pct, updated_at) VALUES (?,?,?,?,?,?)
           ON CONFLICT(event_id) DO UPDATE SET no_show_rate_pct=excluded.no_show_rate_pct,
           shortage_risk_pct=excluded.shortage_risk_pct, safety_buffer_pct=excluded.safety_buffer_pct,
           portion_adjust_pct=excluded.portion_adjust_pct, updated_at=excluded.updated_at""",
        (event_id, a.no_show_rate_pct, a.shortage_risk_pct, a.safety_buffer_pct, a.portion_adjust_pct, now()),
    )
    db.execute("UPDATE events SET confidence_pct=?, veg_percent=?, updated_at=? WHERE id=?",
               (a.confidence_pct, a.veg_percent, now(), event_id))
    if commit:
        db.commit()


# -------------------------------------------------------------- estimates
def dish_inputs(rows):
    return [dict(r) for r in rows]


def compute_for_event(db, event, assumptions=None, dishes=None, with_curve=True):
    if assumptions is None:
        assumptions = get_assumptions(db, event)
    if dishes is None:
        dishes = dish_inputs(get_event_dishes(db, event["id"]))
    return estimate_event(event["expected_guests"], event["registration_count"], assumptions, dishes, with_curve)


def store_estimates(db, event_id):
    """Recalculate and persist the estimate snapshot for an event."""
    event = get_event(db, event_id)
    if event is None:
        return None
    result = compute_for_event(db, event, with_curve=False)
    ts = now()
    for row in result["dishes"]:
        db.execute(
            """INSERT INTO food_estimates (event_id, event_dish_id, estimated_attendance, expected_servings,
               recommended_servings, recommended_kg, expected_leftover_kg, food_cost, surplus_cost, calculated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(event_dish_id) DO UPDATE SET estimated_attendance=excluded.estimated_attendance,
               expected_servings=excluded.expected_servings, recommended_servings=excluded.recommended_servings,
               recommended_kg=excluded.recommended_kg, expected_leftover_kg=excluded.expected_leftover_kg,
               food_cost=excluded.food_cost, surplus_cost=excluded.surplus_cost, calculated_at=excluded.calculated_at""",
            (event_id, row["event_dish_id"], result["attendance"]["estimated_attendance"],
             row["expected_servings"], row["recommended_servings"], row["recommended_kg"],
             row["expected_leftover_kg"], row["food_cost"], row["surplus_cost"], ts),
        )
    db.commit()
    return result


def last_calculated(db, event_id):
    row = db.execute("SELECT MAX(calculated_at) AS t FROM food_estimates WHERE event_id = ?", (event_id,)).fetchone()
    return row["t"] if row else None


# -------------------------------------------------------------- dashboard
def dashboard_stats(db):
    row = db.execute(
        """SELECT (SELECT COUNT(*) FROM events) AS events,
                  (SELECT COALESCE(SUM(expected_guests),0) FROM events) AS guests,
                  (SELECT COALESCE(ROUND(SUM(recommended_kg),1),0) FROM food_estimates) AS total_kg,
                  (SELECT COALESCE(ROUND(SUM(expected_leftover_kg),1),0) FROM food_estimates) AS surplus_kg,
                  (SELECT COUNT(*) FROM donations) AS donations,
                  (SELECT COALESCE(ROUND(SUM(di.quantity_kg),1),0) FROM donation_items di
                       JOIN donations d ON d.id = di.donation_id WHERE d.status = 'completed') AS donated_kg"""
    ).fetchone()
    status_counts = {r["status"]: r["n"] for r in db.execute(
        "SELECT status, COUNT(*) AS n FROM donations GROUP BY status")}
    return dict(row), status_counts


# ------------------------------------------------------------------- ngos
def search_ngos(db, q="", city="", food=""):
    sql = "SELECT * FROM ngos WHERE 1=1"
    params = []
    if q:
        sql += " AND (name LIKE ? OR service_areas LIKE ? OR address LIKE ? OR notes LIKE ?)"
        params += [f"%{q}%"] * 4
    if city:
        sql += " AND city = ?"
        params.append(city)
    if food:
        sql += " AND food_types LIKE ?"
        params.append(f"%{food}%")
    sql += " ORDER BY city, name"
    return db.execute(sql, params).fetchall()


def ngo_cities(db):
    return [r["city"] for r in db.execute("SELECT DISTINCT city FROM ngos WHERE city <> '' ORDER BY city")]


def get_ngo(db, ngo_id):
    return db.execute("SELECT * FROM ngos WHERE id = ?", (ngo_id,)).fetchone()


def create_ngo(db, data):
    cur = db.execute(
        """INSERT INTO ngos (name, city, service_areas, food_types, contact_person, phone, email, address,
           notes, is_sample, source_label, created_at) VALUES (?,?,?,?,?,?,?,?,?,0,'Added by user',?)""",
        (data["name"], data["city"], data["service_areas"], data["food_types"], data["contact_person"],
         data["phone"], data["email"], data["address"], data["notes"], now()),
    )
    db.commit()
    return cur.lastrowid
