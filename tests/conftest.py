import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from food_planner import create_app, db as database, seed  # noqa: E402


class Client:
    """Flask test client wrapper that attaches a valid CSRF token to POSTs."""
    def __init__(self, client):
        self.c = client
        with client.session_transaction() as s:
            s["_csrf"] = "test-token"

    def get(self, url, **kw):
        return self.c.get(url, **kw)

    def post(self, url, data=None, **kw):
        data = dict(data or {})
        data.setdefault("csrf_token", "test-token")
        return self.c.post(url, data=data, **kw)

    def post_json(self, url, payload):
        return self.c.post(url, json=payload, headers={"X-CSRF-Token": "test-token"})


@pytest.fixture()
def app(tmp_path):
    path = str(tmp_path / "test.db")
    app = create_app({"TESTING": True, "DATABASE": path, "SECRET_KEY": "test-secret"})
    app.config["DB_PATH"] = path
    return app


@pytest.fixture()
def client(app):
    return Client(app.test_client())


@pytest.fixture()
def seeded(app):
    conn = database.connect(app.config["DATABASE"])
    seed.seed(conn)
    conn.close()
    return app


EVENT_FORM = {"name": "Test Dinner", "event_type": "Wedding", "event_date": "2030-05-20", "expected_guests": "200",
              "registration_count": "180", "confidence_pct": "80", "meal_type": "dinner", "veg_percent": "40",
              "notes": "No peanuts"}


def make_event(client, dish_ids=(1, 6), **over):
    form = dict(EVENT_FORM)
    form.update(over)
    form["dish_ids"] = [str(i) for i in dish_ids]
    return client.post("/events/new", data=form)


def db_rows(app, sql, params=()):
    conn = database.connect(app.config["DATABASE"])
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()
