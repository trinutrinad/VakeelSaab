# Lawyer Booking App

A complete web application for booking appointments with lawyers. Features user authentication, location-based lawyer search, case submission, and payment processing.

## Features

- 🔐 **User Authentication**: Sign up and login system
- 📍 **Location Services**: Find nearby lawyers based on your location
- ⭐ **Rating-based Search**: Lawyers sorted by ratings
- 📝 **Case Details Form**: Submit your case details with payment
- 💳 **Payment Integration**: Secure payment processing
- 📅 **Consultation Confirmation**: Get consultation date and time after booking
- 📋 **Appointment Management**: View all your appointments

## Installation

1. **Navigate to the project directory:**
   ```bash
   cd LAWYER
   ```

2. **Create a virtual environment (recommended):**
   ```bash
   python -m venv venv
   
   # On Windows:
   venv\Scripts\activate
   
   # On macOS/Linux:
   source venv/bin/activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Run the application:**
   ```bash
   python app.py
   ```

5. **Open your browser and visit:**
   ```
   http://localhost:5000
   ```

## Usage Flow

1. **Sign Up/Login**: Create an account or login
2. **Enable Location**: Allow location access when booking a lawyer
3. **Browse Lawyers**: View nearby lawyers sorted by rating
4. **Select Lawyer**: Choose a lawyer to book
5. **Submit Case**: Fill in case details and payment information
6. **Confirmation**: Receive consultation date and time

## Database configuration

The connection is read from the `DATABASE_URL` environment variable.

| Environment | Value | Notes |
| --- | --- | --- |
| Local development | *(unset)* | Falls back to SQLite at `instance/lawyer_booking.db`. Convenient, and fine for a single developer. |
| Render / any host | `postgresql://user:pass@host:5432/dbname` | **Required in production.** A container filesystem is ephemeral, so a SQLite file is lost on every deploy and restart. |

A legacy `postgres://` URL (the scheme Render and Heroku still hand out) is
normalised to `postgresql://` automatically, because SQLAlchemy 2.x refuses the
old prefix.

### Schema creation and seeding

The app creates missing tables and seeds the demo directory **when it starts**,
at import time, before the first request is served. There is exactly one
`init_db()` implementation and it is called on import; no user has to visit a
route to bring the schema into existence.

Both steps are idempotent and safe with several Gunicorn workers starting at
once:

- `db.create_all()` only issues `CREATE TABLE` for tables that do not exist.
- Each demo profile has a **unique** email address, so the database itself
  rejects a duplicate if two workers race. The loser of the race catches the
  `IntegrityError` and carries on.

Nothing is ever dropped, and no existing row is modified or deleted. A database
created before the unique index existed gets the index added on the next start;
if duplicates are already present they are logged and left untouched rather
than deleted.

### Demo data

The directory contains **100 fictional profiles**, one per Indian city, covering
the metros and tier-2/tier-3 cities (Delhi NCR, Mumbai, Pune, Hyderabad,
Visakhapatnam, Vijayawada, Bengaluru, Chennai, Kochi, Coimbatore, Indore,
Bhopal, Patna, Guwahati, Bhubaneswar, Raipur, Jaipur, Lucknow, and others).

Every profile is fictional and is labelled as such in its name (`Demo Lawyer
<City>`), its bio, and its email domain (`@demo.vakeelsaab.test`). No real
practitioner, credential, phone number, or genuine review is represented.
Ratings are illustrative values used to exercise the rating sort, not reviews.
Consultation fees are indicative INR amounts.

Seeding is idempotent: restarting the app never creates duplicates, and genuine
profiles (any other email address) are never overwritten or removed.

## Database setup and migration commands

There is no separate migration step. Start the app and the schema is created:

```bash
python app.py            # creates tables and seeds demo data
```

To inspect a SQLite database directly:

```bash
sqlite3 instance/lawyer_booking.db ".tables"
sqlite3 instance/lawyer_booking.db "SELECT COUNT(*) FROM lawyer;"
```

Schema changes are applied additively at startup (for example, the unique index
on `lawyer.email`). There is no destructive reset, and no command in this
project drops a table.

## Running the tests

Tests use a temporary SQLite file created for the run, so they never touch a
development or production database.

```bash
pip install -r requirements.txt
python -m pytest tests/ -v
```

They cover schema creation, seeding idempotency, the multi-worker insert race,
legacy-schema index creation, signup/login, the My Appointments route with zero
appointments, appointment queries after initialisation, nearby search distance
filtering, and case-submission validation.

## Deployment

### Render

1. Create a **PostgreSQL** instance in Render and copy its Internal Database URL.
2. Create a **Web Service** from this repository, branch `production-readiness`.
3. Build command: `pip install -r requirements.txt`
4. Start command: `gunicorn app:app` (already in the `Procfile`).
5. Set the environment variables:

| Variable | Required | Value |
| --- | --- | --- |
| `DATABASE_URL` | Yes | The Render PostgreSQL Internal Database URL |
| `SECRET_KEY` | Yes | A long random string. Without it the app falls back to a development default, which makes sessions forgeable. |
| `PYTHON_VERSION` | Optional | e.g. `3.13.0` |
| `LOG_LEVEL` | Optional | Defaults to `INFO` |

Generate a secret key with `python -c "import secrets; print(secrets.token_hex(32))"`.

6. Deploy. On boot the log should show the database target (password redacted),
   `Schema ready`, and the seeded profile count.

Never commit `.env`. `.gitignore` already excludes it.

### Health checks

| Endpoint | Purpose | Success |
| --- | --- | --- |
| `GET /healthz` | Liveness: the process is up | `200` |
| `GET /readyz` | Readiness: the database answers a query | `200`, or `503` if the database is unreachable |

Point the Render health check path at `/readyz`.

### Rollback

Application code: redeploy the previous commit from the Render dashboard
("Rollback" on the deploy). The schema is only ever extended additively, so an
older build can still read a database created by a newer one.

### Backups

Use Render's PostgreSQL backups (or `pg_dump`) for production data. A SQLite
file on a deployed host is not backed up and not persistent, which is the main
reason `DATABASE_URL` is required in production.

## Project Structure

```
VakeelSaab/
├── app.py                  # Flask application (single module)
├── wsgi.py                 # Optional WSGI entry point
├── Procfile                # Render start command
├── requirements.txt        # Python dependencies
├── tests/
│   └── test_app.py         # Automated tests (temporary database)
├── templates/              # HTML templates
│   ├── login.html          # Login page
│   ├── signup.html         # Sign up page
│   ├── dashboard.html      # User dashboard
│   ├── book_lawyer.html    # Find nearby lawyers
│   ├── lawyer_detail.html  # Lawyer profile & booking
│   ├── confirmation.html   # Booking confirmation
│   └── my_appointments.html # View appointments
├── static/
│   └── css/style.css       # Stylesheet
└── README.md
```

## Database Models

- **User**: User accounts with hashed passwords
- **Lawyer**: Lawyer profiles with location coordinates; `email` is unique
- **Appointment**: Booking records, foreign keys to user and lawyer

## API Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/` | Redirects to dashboard or login |
| `GET`/`POST` | `/signup` | Sign up page / create account (JSON) |
| `GET`/`POST` | `/login` | Login page / authenticate (JSON) |
| `GET` | `/logout` | Clear the session |
| `GET` | `/dashboard` | User dashboard |
| `GET` | `/book-lawyer` | Find nearby lawyers |
| `POST` | `/api/nearby-lawyers` | Nearby lawyers (JSON). Requires login. |
| `GET` | `/lawyer/<id>` | Lawyer detail page |
| `POST` | `/submit-case` | Create an appointment (JSON) |
| `GET` | `/confirmation/<id>` | Booking confirmation |
| `GET` | `/my-appointments` | View appointments |
| `GET` | `/healthz`, `/readyz` | Health and readiness probes |

### Nearby search

`POST /api/nearby-lawyers` accepts:

```json
{ "latitude": 28.6139, "longitude": 77.2090, "max_distance": 50 }
```

It returns only profiles within `max_distance` kilometres (default 50) and says
so in the response via `distance_filter_applied: true`. It is a **distance
filter, not a nationwide listing** — a search in Delhi will not return a lawyer
in Chennai.

To review profiles from other cities without travelling, pass
`"include_all": true`. The distance filter is then skipped and the response
reports `distance_filter_applied: false` together with `demo_data: true`, so the
result cannot be mistaken for a genuine nearby search. This is a testing aid,
not a feature of the product.

## Notes and known limitations

- Location services require HTTPS in production (localhost works for development).
- **Payments are not integrated.** No gateway is connected, so a booking is
  recorded with `payment_status = "simulated"` and shown as such in the UI. It
  is never reported as paid. Real payment collection requires a gateway
  integration and server-side signature verification.
- Lawyer profiles are demo data, as described above. There is no verification
  workflow for real practitioners yet.
- The app uses session cookies for authentication. `SECRET_KEY` must be set in
  production, and cookies should be `Secure` when served over HTTPS.

## License

This project is open source and available for use.

