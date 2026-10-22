"""VakeelSaab — lawyer discovery and appointment booking.

Single-module Flask application. The database schema is created and the demo
directory is seeded once at import time, so the app never depends on a user
visiting a particular route before the tables exist.
"""

from flask import Flask, render_template, request, jsonify, redirect, url_for, session, flash
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
from math import radians, cos, sin, asin, sqrt
import logging
import os
import re
import sys

from sqlalchemy import func, inspect
from sqlalchemy.exc import IntegrityError, OperationalError

app = Flask(__name__)

app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-only-change-me')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False


def _database_uri():
    """Resolve the database connection.

    ``DATABASE_URL`` wins so a hosted platform can inject PostgreSQL. When it is
    absent we fall back to a SQLite file in the instance folder, which is a
    convenient local default. The instance folder is used rather than the
    working directory so the file is not importable as a module.
    """
    url = os.environ.get('DATABASE_URL', '').strip()
    if not url:
        os.makedirs(app.instance_path, exist_ok=True)
        return 'sqlite:///' + os.path.join(app.instance_path, 'lawyer_booking.db')

    # Platforms such as Render and Heroku still hand out the legacy
    # ``postgres://`` scheme, which SQLAlchemy 2.x rejects with
    # "Can't load plugin: sqlalchemy.dialects:postgres". Normalise it.
    if url.startswith('postgres://'):
        url = 'postgresql://' + url[len('postgres://'):]

    # A SQLite URL whose directory does not exist fails at startup with
    # "unable to open database file". Create the directory so a configured path
    # works on the first run.
    if url.startswith('sqlite:///') and not url.startswith('sqlite:///:memory:'):
        db_file = url[len('sqlite:///'):]
        parent = os.path.dirname(db_file)
        if parent:
            os.makedirs(parent, exist_ok=True)

    return url


app.config['SQLALCHEMY_DATABASE_URI'] = _database_uri()

db = SQLAlchemy(app)


def _redact_database_uri(uri):
    """Hide any password embedded in a connection URL before logging it."""
    return re.sub(r'//[^@/]*@', '//***@', uri)


logging.basicConfig(
    level=os.environ.get('LOG_LEVEL', 'INFO'),
    format='%(asctime)s %(levelname)s %(name)s %(message)s',
    stream=sys.stdout,
)
logger = logging.getLogger('vakeelsaab')


# Database Models
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    phone = db.Column(db.String(20))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    appointments = db.relationship('Appointment', backref='user', lazy=True)


class Lawyer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    specialization = db.Column(db.String(100), nullable=False)
    experience = db.Column(db.Integer, nullable=False)
    rating = db.Column(db.Float, default=0.0)
    bio = db.Column(db.Text)
    phone = db.Column(db.String(20))
    # Unique so the database itself refuses a duplicate demo profile. Two
    # Gunicorn workers booting at the same time would otherwise both pass the
    # "does it exist?" check and insert the same row twice.
    email = db.Column(db.String(100), unique=True)
    latitude = db.Column(db.Float, nullable=False)
    longitude = db.Column(db.Float, nullable=False)
    location = db.Column(db.String(100))
    hourly_rate = db.Column(db.Float, nullable=False)
    image_url = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    appointments = db.relationship('Appointment', backref='lawyer', lazy=True)


class Appointment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    lawyer_id = db.Column(db.Integer, db.ForeignKey('lawyer.id'), nullable=False)
    case_type = db.Column(db.String(100), nullable=False)
    case_description = db.Column(db.Text, nullable=False)
    payment_amount = db.Column(db.Float, nullable=False)
    payment_status = db.Column(db.String(20), default='pending')
    # A DateTime, because the model declares DateTime and the templates call
    # .strftime() on it. Storing a date object here raised AttributeError.
    consultation_date = db.Column(db.DateTime, nullable=False)
    consultation_time = db.Column(db.String(20), nullable=False)
    status = db.Column(db.String(20), default='confirmed')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


def _ensure_unique_lawyer_email(engine):
    """Add the unique index to a ``lawyer.email`` column that predates it.

    ``create_all`` does not alter existing tables, so a database created before
    the constraint existed keeps its old schema. A non-unique index would not
    stop the duplicate, so this adds a real unique one. If duplicates are
    already present we log them and leave the schema alone rather than deleting
    a single row.
    """
    inspector = inspect(engine)
    if 'lawyer' not in inspector.get_table_names():
        return
    index_names = {i['name'] for i in inspector.get_indexes('lawyer')}
    constraints = {c['name'] for c in inspector.get_unique_constraints('lawyer')}
    if 'ix_lawyer_email' in index_names or 'uq_lawyer_email' in constraints:
        return

    from sqlalchemy import text
    with engine.begin() as connection:
        duplicates = connection.execute(text(
            'SELECT email, COUNT(*) AS n FROM lawyer '
            'WHERE email IS NOT NULL GROUP BY email HAVING COUNT(*) > 1'
        )).fetchall()
        if duplicates:
            logger.error(
                'Cannot enforce unique lawyer emails: %d duplicated address(es) '
                'already present, e.g. %s. Resolve these manually, then restart.',
                len(duplicates), duplicates[0][0],
            )
            return
        connection.execute(text(
            'CREATE UNIQUE INDEX IF NOT EXISTS ix_lawyer_email ON lawyer (email)'
        ))
        logger.info('Added unique index on lawyer.email (existing database).')


# Helper function to calculate distance between two coordinates
def calculate_distance(lat1, lon1, lat2, lon2):
    """Calculate the great circle distance between two points on Earth (in km)"""
    R = 6371  # Radius of earth in kilometers

    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    c = 2 * asin(sqrt(a))
    return R * c


# Demo directory ------------------------------------------------------------
# Every seeded record is fictional and is labelled as such in the name, the
# bio, and the email domain. No real practitioner, credential, phone number, or
# verified rating is invented anywhere in this data. Ratings are illustrative
# demo values used to exercise the rating sort in the UI, not reviews.
DEMO_EMAIL_DOMAIN = 'demo.vakeelsaab.test'
DEMO_BIO = (
    'Fictional demo profile for app testing only. '
    'Not a real or verified lawyer.'
)

# (city, state, latitude, longitude) — 100 Indian cities: the metros plus
# tier-2 and tier-3 cities across every region, so the distance search has a
# realistic spread to work with.
DEMO_CITIES = [
    # North — Delhi NCR, Uttar Pradesh, Punjab, Haryana, Himachal, Uttarakhand, J&K
    ('New Delhi', 'Delhi', 28.6139, 77.2090),
    ('Lucknow', 'Uttar Pradesh', 26.8467, 80.9462),
    ('Kanpur', 'Uttar Pradesh', 26.4499, 80.3319),
    ('Ghaziabad', 'Uttar Pradesh', 28.6692, 77.4538),
    ('Agra', 'Uttar Pradesh', 27.1767, 78.0081),
    ('Varanasi', 'Uttar Pradesh', 25.3176, 82.9739),
    ('Meerut', 'Uttar Pradesh', 28.9845, 77.7064),
    ('Prayagraj', 'Uttar Pradesh', 25.4358, 81.8463),
    ('Bareilly', 'Uttar Pradesh', 28.3670, 79.4304),
    ('Aligarh', 'Uttar Pradesh', 27.8974, 78.0880),
    ('Moradabad', 'Uttar Pradesh', 28.8386, 78.7733),
    ('Gorakhpur', 'Uttar Pradesh', 26.7606, 83.3732),
    ('Noida', 'Uttar Pradesh', 28.5355, 77.3910),
    ('Chandigarh', 'Chandigarh', 30.7333, 76.7794),
    ('Ludhiana', 'Punjab', 30.9010, 75.8573),
    ('Amritsar', 'Punjab', 31.6340, 74.8723),
    ('Jalandhar', 'Punjab', 31.3260, 75.5762),
    ('Gurugram', 'Haryana', 28.4595, 77.0266),
    ('Faridabad', 'Haryana', 28.4089, 77.3178),
    ('Panipat', 'Haryana', 29.3909, 76.9635),
    ('Shimla', 'Himachal Pradesh', 31.1048, 77.1734),
    ('Dehradun', 'Uttarakhand', 30.3165, 78.0322),
    ('Haridwar', 'Uttarakhand', 29.9457, 78.1642),
    ('Jammu', 'Jammu and Kashmir', 32.7266, 74.8570),
    ('Srinagar', 'Jammu and Kashmir', 34.0837, 74.7973),
    # West — Maharashtra, Gujarat, Madhya Pradesh, Chhattisgarh, Goa
    ('Mumbai', 'Maharashtra', 19.0760, 72.8777),
    ('Pune', 'Maharashtra', 18.5204, 73.8567),
    ('Nagpur', 'Maharashtra', 21.1458, 79.0882),
    ('Nashik', 'Maharashtra', 19.9975, 73.7898),
    ('Aurangabad', 'Maharashtra', 19.8762, 75.3433),
    ('Solapur', 'Maharashtra', 17.6599, 75.9064),
    ('Kolhapur', 'Maharashtra', 16.7050, 74.2433),
    ('Amravati', 'Maharashtra', 20.9374, 77.7796),
    ('Nanded', 'Maharashtra', 19.1383, 77.3210),
    ('Ahmedabad', 'Gujarat', 23.0225, 72.5714),
    ('Surat', 'Gujarat', 21.1702, 72.8311),
    ('Vadodara', 'Gujarat', 22.3072, 73.1812),
    ('Rajkot', 'Gujarat', 22.3039, 70.8022),
    ('Bhavnagar', 'Gujarat', 21.7645, 72.1519),
    ('Jamnagar', 'Gujarat', 22.4707, 70.0577),
    ('Gandhinagar', 'Gujarat', 23.2156, 72.6369),
    ('Indore', 'Madhya Pradesh', 22.7196, 75.8577),
    ('Bhopal', 'Madhya Pradesh', 23.2599, 77.4126),
    ('Gwalior', 'Madhya Pradesh', 26.2183, 78.1828),
    ('Jabalpur', 'Madhya Pradesh', 23.1815, 79.9864),
    ('Ujjain', 'Madhya Pradesh', 23.1765, 75.7885),
    ('Raipur', 'Chhattisgarh', 21.2514, 81.6296),
    ('Bhilai', 'Chhattisgarh', 21.1938, 81.3509),
    ('Bilaspur', 'Chhattisgarh', 22.0797, 82.1409),
    ('Panaji', 'Goa', 15.4909, 73.8278),
    # Rajasthan
    ('Jaipur', 'Rajasthan', 26.9124, 75.7873),
    ('Jodhpur', 'Rajasthan', 26.2389, 73.0243),
    ('Kota', 'Rajasthan', 25.2138, 75.8648),
    ('Udaipur', 'Rajasthan', 24.5854, 73.7125),
    ('Ajmer', 'Rajasthan', 26.4499, 74.6399),
    # South — Karnataka, Tamil Nadu, Kerala, Telangana, Andhra Pradesh
    ('Bengaluru', 'Karnataka', 12.9716, 77.5946),
    ('Mysuru', 'Karnataka', 12.2958, 76.6394),
    ('Mangaluru', 'Karnataka', 12.9141, 74.8560),
    ('Hubballi', 'Karnataka', 15.3647, 75.1240),
    ('Belagavi', 'Karnataka', 15.8497, 74.4977),
    ('Davanagere', 'Karnataka', 14.4644, 75.9218),
    ('Shivamogga', 'Karnataka', 13.9299, 75.5681),
    ('Vijayapura', 'Karnataka', 16.8302, 75.7100),
    ('Chennai', 'Tamil Nadu', 13.0827, 80.2707),
    ('Coimbatore', 'Tamil Nadu', 11.0168, 76.9558),
    ('Madurai', 'Tamil Nadu', 9.9252, 78.1198),
    ('Tiruchirappalli', 'Tamil Nadu', 10.7905, 78.7047),
    ('Salem', 'Tamil Nadu', 11.6643, 78.1460),
    ('Tirunelveli', 'Tamil Nadu', 8.7139, 77.7567),
    ('Erode', 'Tamil Nadu', 11.3410, 77.7172),
    ('Vellore', 'Tamil Nadu', 12.9165, 79.1325),
    ('Thoothukudi', 'Tamil Nadu', 8.7642, 78.1348),
    ('Kochi', 'Kerala', 9.9312, 76.2673),
    ('Thiruvananthapuram', 'Kerala', 8.5241, 76.9366),
    ('Kozhikode', 'Kerala', 11.2588, 75.7804),
    ('Thrissur', 'Kerala', 10.5276, 76.2144),
    ('Kollam', 'Kerala', 8.8932, 76.6141),
    ('Kannur', 'Kerala', 11.8745, 75.3704),
    ('Hyderabad', 'Telangana', 17.3850, 78.4867),
    ('Warangal', 'Telangana', 17.9689, 79.5941),
    ('Nizamabad', 'Telangana', 18.6725, 78.0941),
    ('Karimnagar', 'Telangana', 18.4386, 79.1288),
    ('Visakhapatnam', 'Andhra Pradesh', 17.6868, 83.2185),
    ('Vijayawada', 'Andhra Pradesh', 16.5062, 80.6480),
    ('Guntur', 'Andhra Pradesh', 16.3067, 80.4365),
    ('Tirupati', 'Andhra Pradesh', 13.6288, 79.4192),
    ('Nellore', 'Andhra Pradesh', 14.4426, 79.9865),
    # East and North-East
    ('Kolkata', 'West Bengal', 22.5726, 88.3639),
    ('Siliguri', 'West Bengal', 26.7271, 88.3953),
    ('Asansol', 'West Bengal', 23.6739, 86.9524),
    ('Durgapur', 'West Bengal', 23.5204, 87.3119),
    ('Patna', 'Bihar', 25.5941, 85.1376),
    ('Gaya', 'Bihar', 24.7955, 85.0002),
    ('Muzaffarpur', 'Bihar', 26.1209, 85.3647),
    ('Ranchi', 'Jharkhand', 23.3441, 85.3096),
    ('Jamshedpur', 'Jharkhand', 22.8046, 86.2029),
    ('Dhanbad', 'Jharkhand', 23.7957, 86.4304),
    ('Bhubaneswar', 'Odisha', 20.2961, 85.8245),
    ('Cuttack', 'Odisha', 20.4625, 85.8830),
    ('Guwahati', 'Assam', 26.1445, 91.7362),
]

DEMO_SPECIALIZATIONS = [
    'Criminal Law', 'Family Law', 'Civil Law', 'Property Law',
    'Corporate Law', 'Labour Law', 'Tax Law', 'Consumer Law',
    'Cyber Law', 'Constitutional Law', 'Immigration Law', 'Banking Law',
]

# Indicative Indian Rupee consultation fees. Kept modest and varied so the
# listing and sorting are exercised with plausible values.
DEMO_FEES = [500, 600, 700, 800, 900, 1000, 1200, 1500]


def _build_demo_lawyers():
    """Derive one fictional profile per city.

    Values are deterministic, so a given city always maps to the same
    specialization, fee, and rating. That keeps seeding reproducible and makes
    a missing or duplicated profile obvious.
    """
    lawyers = []
    for index, (city, state, latitude, longitude) in enumerate(DEMO_CITIES):
        lawyers.append({
            'name': f'Demo Lawyer {city}',
            'specialization': DEMO_SPECIALIZATIONS[index % len(DEMO_SPECIALIZATIONS)],
            'experience': 5 + (index * 3) % 21,
            'rating': round(4.0 + (index * 7) % 9 / 10, 1),
            'latitude': latitude,
            'longitude': longitude,
            'location': f'{city}, {state}',
            'hourly_rate': DEMO_FEES[index % len(DEMO_FEES)],
        })
    return lawyers


DEMO_LAWYERS = _build_demo_lawyers()


def demo_lawyer_email(name):
    """Stable, recognisable address used to detect an already-seeded profile."""
    return name.lower().replace(' ', '.') + '@' + DEMO_EMAIL_DOMAIN


def seed_demo_lawyers():
    """Insert any missing demo profiles. Returns how many were created.

    Idempotent and safe when several processes start at once. A profile is
    identified by its unique demo email address, so a repeated run inserts
    nothing. If two workers pass the existence check simultaneously the
    database rejects the second insert with an IntegrityError, which is caught
    and treated as "already present" rather than a failure. Real profiles use a
    different address and are never touched or deleted.
    """
    created = 0
    for item in DEMO_LAWYERS:
        email = demo_lawyer_email(item['name'])
        if Lawyer.query.filter_by(email=email).first():
            continue
        try:
            db.session.add(Lawyer(
                **item,
                email=email,
                bio=DEMO_BIO,
                phone=None,
                image_url=None,
            ))
            db.session.commit()
            created += 1
        except IntegrityError:
            # Another worker inserted this exact profile first. Not an error.
            db.session.rollback()
            logger.debug('Demo profile already inserted concurrently: %s', email)
    return created


def init_db():
    """Create tables and seed the demo directory.

    Safe to run on every start and from several workers at once: ``create_all``
    only issues CREATE TABLE for tables that do not exist yet, and seeding
    relies on a unique index rather than a prior read. Nothing is dropped and
    no existing row is modified or deleted.
    """
    with app.app_context():
        uri = app.config['SQLALCHEMY_DATABASE_URI']
        logger.info('Database target: %s', _redact_database_uri(uri))
        if uri.startswith('sqlite:'):
            logger.warning(
                'Using SQLite. This is fine for local development, but a '
                'container filesystem is ephemeral: set DATABASE_URL to a '
                'PostgreSQL instance for any deployed environment.'
            )

        engine = db.engine
        try:
            _ensure_unique_lawyer_email(engine)
        except OperationalError:
            # Concurrent workers may be adding the index at the same moment.
            logger.warning('Could not verify the lawyer email index; continuing.')

        db.create_all()
        logger.info('Schema ready. Known tables: %s',
                    ', '.join(sorted(db.metadata.tables)))

        created = seed_demo_lawyers()
        logger.info('Demo directory: %d created this start, %d total profile(s).',
                    created, Lawyer.query.count())
    return created


# Initialize at import time. Gunicorn imports ``app:app``, so tables exist
# before the first request is served. This must not be moved into a route.
init_db()


@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))


@app.route('/healthz')
def healthz():
    """Liveness probe: the process is up and can render a response."""
    return jsonify({'status': 'ok'}), 200


@app.route('/readyz')
def readyz():
    """Readiness probe: the database answers a trivial query."""
    try:
        db.session.execute(db.text('SELECT 1'))
        return jsonify({'status': 'ok', 'database': 'ok'}), 200
    except Exception:
        # Log the detail server-side; do not return it to the caller.
        logger.exception('Readiness check failed: database unreachable')
        return jsonify({'status': 'error', 'database': 'unavailable'}), 503


@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        data = request.get_json(silent=True) or {}
        username = (data.get('username') or '').strip()
        email = (data.get('email') or '').strip()
        password = data.get('password') or ''
        phone = (data.get('phone') or '').strip()

        if not all([username, email, password]):
            return jsonify({'success': False, 'message': 'All fields are required'}), 400

        if User.query.filter_by(username=username).first():
            return jsonify({'success': False, 'message': 'Username already exists'}), 400

        if User.query.filter_by(email=email).first():
            return jsonify({'success': False, 'message': 'Email already exists'}), 400

        user = User(
            username=username,
            email=email,
            password_hash=generate_password_hash(password),
            phone=phone
        )
        db.session.add(user)
        db.session.commit()

        session['user_id'] = user.id
        session['username'] = user.username

        return jsonify({'success': True, 'message': 'Account created successfully'})

    return render_template('signup.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        data = request.get_json(silent=True) or {}
        username = (data.get('username') or '').strip()
        password = data.get('password') or ''

        if not username or not password:
            return jsonify({'success': False, 'message': 'Username and password are required'}), 400

        user = User.query.filter_by(username=username).first()

        if user and check_password_hash(user.password_hash, password):
            session['user_id'] = user.id
            session['username'] = user.username
            return jsonify({'success': True, 'message': 'Login successful'})
        else:
            return jsonify({'success': False, 'message': 'Invalid username or password'}), 401

    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return render_template('dashboard.html')


@app.route('/book-lawyer')
def book_lawyer():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return render_template('book_lawyer.html')


@app.route('/api/nearby-lawyers', methods=['POST'])
def nearby_lawyers():
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.get_json(silent=True) or {}

    try:
        user_lat = float(data.get('latitude'))
        user_lon = float(data.get('longitude'))
    except (TypeError, ValueError):
        return jsonify({'error': 'Valid latitude and longitude are required'}), 400

    if not (-90 <= user_lat <= 90) or not (-180 <= user_lon <= 180):
        return jsonify({'error': 'Coordinates are out of range'}), 400

    try:
        max_distance = float(data.get('max_distance', 50) or 50)
    except (TypeError, ValueError):
        return jsonify({'error': 'max_distance must be a number'}), 400
    if max_distance <= 0:
        return jsonify({'error': 'max_distance must be greater than zero'}), 400

    # Testing aid. When true, the distance filter is skipped so a reviewer can
    # see the whole demo directory from any location. The response says so
    # explicitly, so a caller cannot mistake this for a nearby search.
    include_all = bool(data.get('include_all', False))

    all_lawyers = Lawyer.query.all()

    nearby = []
    for lawyer in all_lawyers:
        distance = calculate_distance(user_lat, user_lon, lawyer.latitude, lawyer.longitude)
        if include_all or distance <= max_distance:
            nearby.append({
                'id': lawyer.id,
                'name': lawyer.name,
                'specialization': lawyer.specialization,
                'rating': lawyer.rating,
                'experience': lawyer.experience,
                'distance': round(distance, 2),
                'hourly_rate': lawyer.hourly_rate,
                'location': lawyer.location,
                'image_url': lawyer.image_url or 'https://via.placeholder.com/300x300?text=Lawyer'
            })

    # Sort by rating (highest first)
    nearby.sort(key=lambda x: x['rating'], reverse=True)

    return jsonify({
        'lawyers': nearby,
        'distance_filter_applied': not include_all,
        'max_distance_km': max_distance,
        'currency': 'INR',
        'demo_data': True,
    })


@app.route('/lawyer/<int:lawyer_id>')
def lawyer_detail(lawyer_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    lawyer = Lawyer.query.get_or_404(lawyer_id)
    return render_template('lawyer_detail.html', lawyer=lawyer)


@app.route('/submit-case', methods=['POST'])
def submit_case():
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401

    data = request.get_json(silent=True) or {}
    lawyer_id = data.get('lawyer_id')
    case_type = (data.get('case_type') or '').strip()
    case_description = (data.get('case_description') or '').strip()
    payment_amount = data.get('payment_amount')

    if not all([lawyer_id, case_type, case_description, payment_amount]):
        return jsonify({'success': False, 'message': 'All fields are required'}), 400

    # Validate the lawyer reference before writing a row. Without this, a bad
    # id surfaced as an IntegrityError and a 500.
    try:
        lawyer_pk = int(lawyer_id)
    except (TypeError, ValueError):
        return jsonify({'success': False, 'message': 'Invalid lawyer id'}), 400

    lawyer = db.session.get(Lawyer, lawyer_pk)
    if lawyer is None:
        return jsonify({'success': False, 'message': 'Lawyer not found'}), 404

    try:
        amount = float(payment_amount)
    except (TypeError, ValueError):
        return jsonify({'success': False, 'message': 'Payment amount must be a number'}), 400
    if amount <= 0:
        return jsonify({'success': False, 'message': 'Payment amount must be greater than zero'}), 400

    # Generate consultation date and time (next available slot)
    consultation_datetime = datetime.now() + timedelta(days=1)
    consultation_datetime = consultation_datetime.replace(hour=10, minute=0, second=0, microsecond=0)

    appointment = Appointment(
        user_id=session['user_id'],
        lawyer_id=lawyer.id,
        case_type=case_type,
        case_description=case_description,
        payment_amount=amount,
        # No payment gateway is connected, so this is recorded as simulated
        # rather than paid. Do not report money as collected when none was.
        payment_status='simulated',
        consultation_date=consultation_datetime,
        consultation_time=consultation_datetime.strftime('%I:%M %p'),
        status='confirmed'
    )

    db.session.add(appointment)
    db.session.commit()

    return jsonify({
        'success': True,
        'appointment_id': appointment.id,
        'consultation_date': consultation_datetime.strftime('%B %d, %Y'),
        'consultation_time': consultation_datetime.strftime('%I:%M %p'),
        'payment_status': appointment.payment_status,
    })


@app.route('/confirmation/<int:appointment_id>')
def confirmation(appointment_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    appointment = Appointment.query.get_or_404(appointment_id)
    if appointment.user_id != session['user_id']:
        return redirect(url_for('dashboard'))

    return render_template('confirmation.html', appointment=appointment)


@app.route('/my-appointments')
def my_appointments():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    appointments = Appointment.query.filter_by(user_id=session['user_id']).order_by(Appointment.consultation_date.desc()).all()
    return render_template('my_appointments.html', appointments=appointments)


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
