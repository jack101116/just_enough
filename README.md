# Just Enough: Design 4: Modern Minimalist UI

**Plan meals. Reduce waste. Share surplus.**

Just Enough is a local web application for event organisers. It estimates how much of each dish to prepare, lets you
adjust the assumptions and the acceptable shortage risk, shows the expected leftover, and helps you prepare and track a
surplus-donation plan using a searchable NGO directory.

This package is **Design 4: Modern Minimalist UI** (white, hairline borders, compact top navigation, one accent colour). All four design packages share the same backend, calculation engine,
database schema, routes, validation and features. Only the visual design and layout differ.

Stack: Python 3 + Flask, SQLite (built-in `sqlite3`), Jinja2, HTML/CSS/JavaScript. No paid APIs or cloud services.

## Run it on Windows (step by step)

You need Python 3.9 or newer from https://www.python.org/downloads/ (tick **Add python.exe to PATH** during install).

1. **Extract** the ZIP file (right-click, Extract All).
2. **Open the project folder** `just_enough` in VS Code (File, Open Folder) and open a terminal, or open Command Prompt
   and `cd` into the folder.
3. **Create a virtual environment**
   ```bat
   py -m venv .venv
   ```
4. **Activate it**
   ```bat
   .venv\Scripts\activate
   ```
   (PowerShell users: `.venv\Scripts\Activate.ps1`. If scripts are blocked, run
   `Set-ExecutionPolicy -Scope Process RemoteSigned` first.)
5. **Install dependencies**
   ```bat
   python -m pip install -r requirements.txt
   ```
6. **Initialise (and optionally seed) the database**
   ```bat
   python init_db.py
   python seed_db.py
   ```
   `init_db.py` only creates missing tables and never erases data. `seed_db.py` is optional: it adds sample dishes, three
   sample events and a **clearly labelled fictional** NGO directory, and only fills empty tables, so running it twice is safe.
7. **Start the app**
   ```bat
   python app.py
   ```
8. **Open** http://127.0.0.1:5000 in your browser. Stop the server with Ctrl+C.

The app also creates its tables automatically on first start, so steps 6 can be skipped if you want an empty app.

macOS / Linux: use `python3 -m venv .venv`, `source .venv/bin/activate`, then the same pip and python commands.

## Using the app

| Area | What you can do |
|------|-----------------|
| Home / Dashboard | Figures (events, guests, estimated food, potential surplus) are read from the SQLite database. |
| Events | Create, view, edit and delete (with confirmation) event plans with validation. |
| Planner | Edit assumptions and per-dish portion, consumption rate and cost. Results recalculate live (server-side) and are saved with one click. |
| Risk explorer | Slide the acceptable shortage risk and see quantity, expected leftover, cost and the trade-off. |
| Dishes | Maintain a reusable dish catalogue. |
| Donations | Review surplus per dish, set prepared time and handoff deadline, acknowledge food-safety guidance, choose an NGO, save a donation summary and record status (Draft, Ready for Contact, Contacted, Accepted, Completed, Cancelled). |
| NGO directory | Search by name, service area, city and food type. Add your own verified organisations. |
| Reports | Printable event report (use the browser's Print, then Save as PDF) and CSV export; history of all plans. |

## How the estimate works (summary)

Full details are in the docstring at the top of `food_planner/services/estimation.py` and on every report.

1. Estimated attendance = expected guests x (1 - no-show rate).
2. Attendance uncertainty combines normal show-up variation with a headcount-doubt term driven by *attendance confidence*
   (lower confidence widens the range; it does **not** reduce the average, so nothing is counted twice).
3. Dish demand = attending guests who can eat the dish (non-vegetarian dishes use the non-vegetarian share) x the dish's consumption rate.
4. Recommended servings = demand mean + z x spread, where z comes from the acceptable shortage risk (normal approximation), then an optional separate safety buffer.
5. Recommended kg = servings x portion size (after the global portion adjustment). Expected leftover is the modelled average unused amount. Costs only appear when a cost per kg is entered.

**Limits:** the shortage probability shown is a model output, not a statistically calibrated probability. The uncertainty
constant (0.25) is a documented modelling assumption. Validate against your own attendance history for large events.

## Important notes on donations and the NGO directory

* The NGO entries supplied by `seed_db.py` are **fictional sample data** with placeholder contact details. They are not real organisations and are labelled SAMPLE throughout the app.
* There is no live map, geolocation or availability. The directory is searchable by name, city and service area.
* The app never contacts an NGO. Status values are records you enter. A donation is only shown as Accepted or Completed after you record it.
* Food-safety timing is general guidance, not certified food-safety advice. Follow local regulations and the recipient's requirements.

## Configuration (optional)

Copy `.env.example` to `.env` and edit. Supported settings: `SECRET_KEY`, `JUST_ENOUGH_DB`, `FLASK_DEBUG`, `HOST`, `PORT`,
`SESSION_COOKIE_SECURE`, `CURRENCY_SYMBOL`. If `SECRET_KEY` is not set, a random key is generated once and stored in
`instance/secret_key` (never hard-coded). Debug mode is off unless `FLASK_DEBUG=1`. Do not use Flask's built-in server for
public hosting; use a production WSGI server and HTTPS.

## Tests

```bat
python -m pip install -r requirements-dev.txt
python -m pytest
```
The tests cover database initialisation, event CRUD, dishes, calculations, validation, surplus, NGO search,
donation status rules, reports, CSV export, persistence and essential routes.

## Project layout

```
app.py  config.py  init_db.py  seed_db.py  requirements.txt

food_planner/   models (db.py), routes.py, repository.py, donation_repo.py, seed.py,
                services/estimation.py, services/donations.py, utils/
templates/      Jinja2 templates (base.html and index.html are specific to this design)
static/         css/components.css (shared components), css/design.css (this design), js/app.js
tests/          pytest suite     instance/   SQLite database lives here
```

Round 2 introduced a contemporary minimalist UI design along with enhancements in event and food organizing, real-time food amount and price calculations, food shortage explorer and estimated leftovers calculator. It also featured an additional module for managing excess food donations with NGO database for searching organizations that will accept these donations and track their current status with printable reports and CSV exports.
