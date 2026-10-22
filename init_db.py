"""Create the SQLite database and tables. Safe to run repeatedly: existing data is never erased."""
import config
from food_planner import db

if __name__ == "__main__":
    settings = config.build_config()
    db.init_db_file(settings["DATABASE"])
    print(f"Database ready at: {settings['DATABASE']}")
    print("Existing data (if any) was left untouched.")
