"""Add sample dishes, a clearly-labelled sample NGO directory and sample events.
Only fills EMPTY tables, so running it twice does not duplicate or overwrite anything."""
import config
from food_planner import db, seed

if __name__ == "__main__":
    settings = config.build_config()
    conn = db.connect(settings["DATABASE"])
    db.init_schema(conn)
    added = seed.seed(conn)
    conn.close()
    print("Sample data added:", added)
    if not any(added.values()):
        print("Nothing added: tables already contain data.")
