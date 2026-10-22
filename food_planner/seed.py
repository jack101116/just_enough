"""Idempotent sample data. Safe to run repeatedly: it only fills empty tables."""
from datetime import date, datetime, timedelta

from . import repository as repo
from .services.estimation import Assumptions

DISHES = [
    ("Jeera Rice", "Rice & grains", "vegetarian", 150, 85, 90),
    ("Veg Biryani", "Rice & grains", "vegetarian", 200, 55, 130),
    ("Dal Tadka", "Dal & lentils", "vegetarian", 120, 80, 110),
    ("Paneer Butter Masala", "Curry / Gravy", "vegetarian", 130, 70, 360),
    ("Mixed Veg Curry", "Curry / Gravy", "vegan", 120, 60, 100),
    ("Chicken Curry", "Curry / Gravy", "non_vegetarian", 150, 80, 280),
    ("Mutton Rogan Josh", "Curry / Gravy", "non_vegetarian", 130, 50, 700),
    ("Tandoori Roti", "Bread", "vegetarian", 60, 90, 70),
    ("Green Salad", "Salad / Sides", "vegan", 60, 45, 60),
    ("Gulab Jamun", "Dessert", "vegetarian", 60, 75, 220),
    ("Masala Chai", "Beverage", "vegetarian", 120, 85, 40),
    ("Veg Sandwich", "Starter / Snack", "vegetarian", 100, 70, 150),
    ("Poha", "Starter / Snack", "vegan", 150, 80, 60),
]

# Clearly fictional demonstration entries. Contact values are placeholders on purpose.
NGOS = [
    ("Demo Food Rescue Trust", "Demo City North", "Sector 1-5, Riverside, Old Market", "Cooked meals, Bakery items",
     "Sample Coordinator", "+00 000 000 0001", "contact@example.org", "1 Sample Lane, Demo City North",
     "Sample entry for demonstration. Not a real organisation."),
    ("Sample Community Kitchen Collective", "Demo City North", "Lakeside, University Area",
     "Cooked meals, Packaged food", "Sample Coordinator", "+00 000 000 0002", "kitchen@example.org",
     "22 Placeholder Road, Demo City North", "Sample entry for demonstration. Not a real organisation."),
    ("Example Shelter Meals Network", "Demo City South", "Harbour District, Station Road",
     "Cooked meals", "Sample Coordinator", "+00 000 000 0003", "shelter@example.org",
     "5 Example Street, Demo City South", "Sample entry for demonstration. Not a real organisation."),
    ("Illustrative Elder Care Meals", "Demo City South", "Greenfield, Market Square",
     "Cooked meals, Fruits & sweets", "Sample Coordinator", "+00 000 000 0004", "elders@example.org",
     "9 Illustration Avenue, Demo City South", "Sample entry for demonstration. Not a real organisation."),
    ("Placeholder Children's Nutrition Programme", "Demo City East", "Eastside Schools Zone",
     "Cooked meals, Packaged food", "Sample Coordinator", "+00 000 000 0005", "children@example.org",
     "14 Dummy Close, Demo City East", "Sample entry for demonstration. Not a real organisation."),
]


def seed(db):
    """Insert sample catalogue, NGOs and events if the tables are empty. Returns counts added."""
    added = {"dishes": 0, "ngos": 0, "events": 0}
    ts = repo.now()
    if db.execute("SELECT COUNT(*) FROM dishes").fetchone()[0] == 0:
        for d in DISHES:
            db.execute("""INSERT INTO dishes (name, food_category, dietary_category, default_portion_g,
                       default_rate_pct, default_cost_per_kg, created_at) VALUES (?,?,?,?,?,?,?)""", (*d, ts))
            added["dishes"] += 1
    if db.execute("SELECT COUNT(*) FROM ngos").fetchone()[0] == 0:
        for n in NGOS:
            db.execute("""INSERT INTO ngos (name, city, service_areas, food_types, contact_person, phone, email,
                       address, notes, is_sample, source_label, created_at) VALUES (?,?,?,?,?,?,?,?,?,1,
                       'SAMPLE DATA (fictional)',?)""", (*n, ts))
            added["ngos"] += 1
    db.commit()
    if db.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0:
        base = date.today()
        samples = [
            ("Annual Alumni Dinner", "Community meal", base + timedelta(days=14), 250, 210, 80, "dinner", 45,
             ["Jeera Rice", "Dal Tadka", "Paneer Butter Masala", "Chicken Curry", "Tandoori Roti", "Gulab Jamun"],
             Assumptions(no_show_rate_pct=12, shortage_risk_pct=8, safety_buffer_pct=0)),
            ("Tech Conference Lunch", "Conference", base + timedelta(days=30), 400, 380, 90, "lunch", 55,
             ["Veg Biryani", "Mixed Veg Curry", "Green Salad", "Tandoori Roti", "Masala Chai"],
             Assumptions(no_show_rate_pct=15, shortage_risk_pct=5, safety_buffer_pct=5)),
            ("Wedding Reception", "Wedding", base - timedelta(days=20), 180, 150, 60, "dinner", 35,
             ["Jeera Rice", "Mutton Rogan Josh", "Chicken Curry", "Dal Tadka", "Gulab Jamun"],
             Assumptions(no_show_rate_pct=8, shortage_risk_pct=10, safety_buffer_pct=0)),
        ]
        for name, etype, d, guests, regs, conf, meal, veg, dishes, assum in samples:
            data = {"name": name, "event_type": etype, "event_date": d.isoformat(), "expected_guests": guests,
                    "registration_count": regs, "confidence_pct": conf, "meal_type": meal, "veg_percent": veg,
                    "dietary_tags": "Jain" if veg > 50 else "", "notes": "Sample event created by seed_db.py."}
            ids = [r["id"] for n in dishes for r in [db.execute("SELECT id FROM dishes WHERE name = ?", (n,)).fetchone()] if r]
            eid = repo.create_event(db, data, ids)
            assum.confidence_pct, assum.veg_percent = conf, veg
            repo.save_assumptions(db, eid, assum)
            repo.store_estimates(db, eid)
            added["events"] += 1
    return added
