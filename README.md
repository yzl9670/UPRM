Chem PR Technical Report Feedback
================================

Overview
--------

This is a lightweight Flask web app that provides rubric-based feedback for Chemical Engineering in Puerto Rico technical reports. It keeps the key HTTP interfaces from your previous LEED project so you can swap rubrics easily and deploy on Render with a managed PostgreSQL database.

Highlights
- Same-style endpoints for rubric management and feedback:
  - `GET /get_WRITING_RUBRICs` returns the active rubric JSON
  - `POST /save_WRITING_RUBRICs` saves a new rubric (admin only)
  - `POST /get_feedback` generates rubric-focused feedback for a provided report
  - `GET /get_last_feedback` returns the latest feedback text for the current user
  - `POST /submit_feedback` stores user rating/comments for a feedback interaction
- No LEED form or credit endpoints.
- Rubric lives in `data/rubric.json` and can be edited directly or via the admin API.
- Render-ready DB via `DATABASE_URL` (PostgreSQL) and `render.yaml`.

Quick Start (Local)
-------------------

1) Python 3.10+ recommended.
2) Create a virtual environment and install deps:
   - `python -m venv .venv`
   - `.venv/Scripts/activate` (Windows) or `source .venv/bin/activate` (macOS/Linux)
   - `pip install -r requirements.txt`
3) Copy `.env.example` to `.env` and set values as needed.
4) Run the app:
   - `flask --app app run --debug`
   - Or `python app.py`

Login & Roles
-------------

- Register via `/register`, then login at `/login`.
- Make an admin by updating the `account.role` column to `admin` in the DB. For a quick bootstrap you can set `ADMIN_USERNAME` and `ADMIN_PASSWORD` in the environment; the app will create an admin account at startup if it doesn’t exist.

Rubric
------

- File location: `data/rubric.json`
- Shape (example):
  [
    {"name": "Executive Summary", "scoringCriteria": [ {"points": 4, "description": "..."}, ... ]},
    {"name": "Context: Puerto Rico", "scoringCriteria": [ ... ]},
    ...
  ]
- You can edit this file directly and restart, or use the admin endpoint `POST /save_WRITING_RUBRICs` with a JSON array body.

Render Deployment
-----------------

- This repo includes `render.yaml` to define a Python web service and a managed PostgreSQL database.
- Render will inject `DATABASE_URL` automatically via `envVars.fromDatabase`.
- Build uses `pip install -r requirements.txt`; start uses `gunicorn app:app`.

Environment Variables
---------------------

- `SECRET_KEY`: Flask session secret. In Render this is generated automatically by `render.yaml`.
- `DATABASE_URL`: PostgreSQL URL from Render. The app also supports SQLite locally if unset.
- `OPENAI_API_KEY` (optional): Enables LLM-based scoring in `feedback_tech.py`. Without it, the app returns a simple rules-based fallback.
- `ADMIN_USERNAME`/`ADMIN_PASSWORD` (optional): Seed an admin account on first boot.

Files
-----

- `app.py`: Flask app, routes, DB wiring.
- `feedback_tech.py`: Feedback generation (LLM + fallback) focused on writing rubric only.
- `models.py`: SQLAlchemy models.
- `templates/`: Jinja templates for pages.
- `data/rubric.json`: Active rubric definition.
- `render.yaml`: Render web service + managed DB.
- `requirements.txt`: Python dependencies.
- `Procfile`: Heroku/Render-compatible start command.

