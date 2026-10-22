"""Tests for the VakeelSaab Flask application.

Every test runs against a temporary SQLite file created for the session, so the
suite can never touch a real database. ``DATABASE_URL`` is set before ``app`` is
imported, because the application resolves its connection and initialises the
schema at import time.
"""

import importlib
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture(scope='session')
def db_path():
    fd, path = tempfile.mkstemp(prefix='vakeelsaab-test-', suffix='.db')
    os.close(fd)
    os.unlink(path)  # let SQLite create it, so we know it started empty
    yield path
    if os.path.exists(path):
        os.unlink(path)


@pytest.fixture(scope='session')
def app_module(db_path):
    os.environ['DATABASE_URL'] = 'sqlite:///' + db_path
    os.environ.setdefault('SECRET_KEY', 'test-secret-key-not-used-in-production')
    if 'app' in sys.modules:
        del sys.modules['app']
    return importlib.import_module('app')


@pytest.fixture()
def app(app_module):
    app_module.app.config.update(TESTING=True)
    return app_module.app


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def auth_client(client):
    """A client with an account created and logged in."""
    response = client.post('/signup', json={
        'username': 'testuser',
        'email': 'testuser@example.com',
        'password': 'test-password',
        'phone': '9999999999',
    })
    assert response.status_code in (200, 400), response.get_data(as_text=True)
    response = client.post('/login', json={
        'username': 'testuser',
        'password': 'test-password',
    })
    assert response.status_code == 200
    return client


class TestInitialization:
    def test_tables_are_created(self, app_module):
        with app_module.app.app_context():
            names = set(app_module.db.metadata.tables)
            assert {'user', 'lawyer', 'appointment'} <= names
            # A real query proves the tables physically exist.
            assert app_module.User.query.count() >= 0

    def test_demo_lawyers_are_seeded(self, app_module):
        with app_module.app.app_context():
            assert app_module.Lawyer.query.count() == len(app_module.DEMO_LAWYERS)

    def test_directory_covers_100_indian_cities(self, app_module):
        """The directory spans the metros and tier-2/tier-3 cities."""
        assert len(app_module.DEMO_CITIES) == 100
        cities = [c[0] for c in app_module.DEMO_CITIES]
        assert len(set(cities)) == 100, 'city names must be unique'
        assert len(app_module.DEMO_LAWYERS) == 100
        names = [l['name'] for l in app_module.DEMO_LAWYERS]
        assert len(set(names)) == 100, 'profile names must be unique'

    def test_repeated_initialization_does_not_duplicate(self, app_module):
        with app_module.app.app_context():
            before = app_module.Lawyer.query.count()
            created = app_module.seed_demo_lawyers()
            after = app_module.Lawyer.query.count()
            assert created == 0, 'a second seed run must create nothing'
            assert after == before

    def test_init_db_is_idempotent(self, app_module):
        """Running the whole init twice must be safe."""
        before = app_module.init_db()
        assert before == 0
        with app_module.app.app_context():
            assert app_module.Lawyer.query.count() == len(app_module.DEMO_LAWYERS)

    def test_only_one_init_db_definition(self, app_module):
        """The module must expose exactly one authoritative init_db."""
        source = open(app_module.__file__, encoding='utf-8').read()
        assert source.count('def init_db(') == 1

    def test_demo_profiles_are_labelled_fictional(self, app_module):
        with app_module.app.app_context():
            for lawyer in app_module.Lawyer.query.all():
                assert lawyer.name.startswith('Demo Lawyer')
                assert 'Fictional demo profile' in lawyer.bio
                assert lawyer.email.endswith('@' + app_module.DEMO_EMAIL_DOMAIN)
                # No invented contact details or credentials.
                assert lawyer.phone is None

    def test_demo_cities_cover_major_indian_cities(self, app_module):
        with app_module.app.app_context():
            locations = ' '.join(l.location for l in app_module.Lawyer.query.all())
            for city in ['New Delhi', 'Mumbai', 'Hyderabad', 'Visakhapatnam',
                         'Vijayawada', 'Bengaluru', 'Chennai', 'Kolkata',
                         'Ahmedabad', 'Pune', 'Jaipur', 'Lucknow']:
                assert city in locations, f'{city} missing from demo data'

    def test_demo_directory_includes_tier_two_cities(self, app_module):
        with app_module.app.app_context():
            locations = ' '.join(l.location for l in app_module.Lawyer.query.all())
            for city in ['Kochi', 'Coimbatore', 'Indore', 'Bhopal', 'Patna',
                         'Guwahati', 'Bhubaneswar', 'Raipur', 'Dehradun',
                         'Mysuru', 'Madurai', 'Ranchi', 'Nagpur', 'Surat',
                         'Varanasi', 'Amritsar', 'Siliguri', 'Jodhpur']:
                assert city in locations, f'tier-2 city {city} missing'

    def test_demo_fees_are_positive_inr(self, app_module):
        with app_module.app.app_context():
            for lawyer in app_module.Lawyer.query.all():
                assert lawyer.hourly_rate > 0
                assert -90 <= lawyer.latitude <= 90
                assert -180 <= lawyer.longitude <= 180

    def test_duplicate_demo_email_is_rejected_by_the_database(self, app_module):
        """The unique index is what stops two workers racing on insert.

        Without it, both workers pass the "does it exist?" check and the same
        profile is stored twice.
        """
        from sqlalchemy.exc import IntegrityError
        with app_module.app.app_context():
            existing = app_module.Lawyer.query.first()
            duplicate = app_module.Lawyer(
                name='Demo Lawyer Duplicate',
                specialization='Civil Law',
                experience=5,
                latitude=1.0,
                longitude=1.0,
                hourly_rate=500,
                email=existing.email,
            )
            app_module.db.session.add(duplicate)
            with pytest.raises(IntegrityError):
                app_module.db.session.commit()
            app_module.db.session.rollback()

    def test_concurrent_seed_inserts_do_not_duplicate(self, app_module):
        """Simulates a worker losing the race: it must not raise or duplicate."""
        from sqlalchemy.exc import IntegrityError
        with app_module.app.app_context():
            item = app_module.DEMO_LAWYERS[0]
            email = app_module.demo_lawyer_email(item['name'])
            before = app_module.Lawyer.query.count()
            # Force the insert path even though the row already exists.
            try:
                app_module.db.session.add(app_module.Lawyer(
                    **item, email=email, bio=app_module.DEMO_BIO,
                    phone=None, image_url=None,
                ))
                app_module.db.session.commit()
            except IntegrityError:
                app_module.db.session.rollback()
            assert app_module.Lawyer.query.count() == before

    def test_unique_index_is_added_to_a_legacy_database(self, tmp_path):
        """A database created before the constraint existed gets the index."""
        from sqlalchemy import create_engine, inspect, text
        import app as module

        path = tmp_path / 'legacy.db'
        engine = create_engine('sqlite:///' + str(path))
        with engine.begin() as connection:
            connection.execute(text(
                'CREATE TABLE lawyer (id INTEGER PRIMARY KEY, email VARCHAR(100))'
            ))
        assert 'ix_lawyer_email' not in {
            i['name'] for i in inspect(engine).get_indexes('lawyer')
        }

        module._ensure_unique_lawyer_email(engine)

        assert 'ix_lawyer_email' in {
            i['name'] for i in inspect(engine).get_indexes('lawyer')
        }
        engine.dispose()

    def test_legacy_database_with_duplicates_is_left_alone(self, tmp_path):
        """Existing duplicates are reported, never silently deleted."""
        from sqlalchemy import create_engine, inspect, text
        import app as module

        path = tmp_path / 'dupes.db'
        engine = create_engine('sqlite:///' + str(path))
        with engine.begin() as connection:
            connection.execute(text(
                'CREATE TABLE lawyer (id INTEGER PRIMARY KEY, email VARCHAR(100))'
            ))
            connection.execute(text(
                "INSERT INTO lawyer (email) VALUES ('a@b.test'), ('a@b.test')"
            ))

        module._ensure_unique_lawyer_email(engine)

        # No index added, and both rows still present.
        assert 'ix_lawyer_email' not in {
            i['name'] for i in inspect(engine).get_indexes('lawyer')
        }
        with engine.connect() as connection:
            count = connection.execute(text('SELECT COUNT(*) FROM lawyer')).scalar()
        assert count == 2
        engine.dispose()


class TestAuthentication:
    def test_signup_and_login(self, client):
        assert client.post('/signup', json={
            'username': 'alice', 'email': 'alice@example.com',
            'password': 'pw12345',
        }).status_code == 200
        assert client.post('/login', json={
            'username': 'alice', 'password': 'pw12345',
        }).status_code == 200

    def test_duplicate_username_is_rejected(self, auth_client):
        response = auth_client.post('/signup', json={
            'username': 'testuser', 'email': 'other@example.com',
            'password': 'pw12345',
        })
        assert response.status_code == 400

    def test_login_with_wrong_password_is_401(self, client):
        response = client.post('/login', json={
            'username': 'nobody', 'password': 'wrong',
        })
        assert response.status_code == 401

    def test_signup_requires_fields(self, client):
        assert client.post('/signup', json={'username': 'x'}).status_code == 400


class TestPages:
    def test_my_appointments_returns_200_with_zero_appointments(self, auth_client):
        response = auth_client.get('/my-appointments')
        assert response.status_code == 200, response.get_data(as_text=True)

    def test_dashboard_and_booking_pages_render(self, auth_client):
        assert auth_client.get('/dashboard').status_code == 200
        assert auth_client.get('/book-lawyer').status_code == 200

    def test_protected_pages_redirect_when_anonymous(self, client):
        for path in ('/my-appointments', '/dashboard', '/book-lawyer'):
            response = client.get(path)
            assert response.status_code == 302

    def test_health_endpoints(self, client):
        assert client.get('/healthz').status_code == 200
        ready = client.get('/readyz')
        assert ready.status_code == 200
        assert ready.get_json()['database'] == 'ok'


class TestNearbySearch:
    def test_search_returns_nearby_lawyers(self, auth_client, app_module):
        # Coordinates of New Delhi; NCR cities are within 50km.
        response = auth_client.post('/api/nearby-lawyers', json={
            'latitude': 28.6139, 'longitude': 77.2090, 'max_distance': 50,
        })
        assert response.status_code == 200
        body = response.get_json()
        assert body['distance_filter_applied'] is True
        names = [l['name'] for l in body['lawyers']]
        assert 'Demo Lawyer New Delhi' in names
        # Distant cities must not appear under a 50km filter.
        assert 'Demo Lawyer Chennai' not in names
        assert 'Demo Lawyer Kochi' not in names
        # Everything returned must genuinely be within the radius.
        assert all(l['distance'] <= 50 for l in body['lawyers'])

    def test_search_respects_a_wider_radius(self, auth_client):
        """A larger radius must return at least as many profiles."""
        narrow = auth_client.post('/api/nearby-lawyers', json={
            'latitude': 28.6139, 'longitude': 77.2090, 'max_distance': 50,
        }).get_json()['lawyers']
        wide = auth_client.post('/api/nearby-lawyers', json={
            'latitude': 28.6139, 'longitude': 77.2090, 'max_distance': 1000,
        }).get_json()['lawyers']
        assert len(wide) >= len(narrow)
        assert all(l['distance'] <= 1000 for l in wide)

    def test_include_all_returns_whole_directory(self, auth_client, app_module):
        response = auth_client.post('/api/nearby-lawyers', json={
            'latitude': 28.6139, 'longitude': 77.2090, 'include_all': True,
        })
        body = response.get_json()
        assert body['distance_filter_applied'] is False
        assert len(body['lawyers']) == len(app_module.DEMO_LAWYERS)

    def test_search_validates_coordinates(self, auth_client):
        assert auth_client.post('/api/nearby-lawyers', json={}).status_code == 400
        assert auth_client.post('/api/nearby-lawyers', json={
            'latitude': 'abc', 'longitude': 'xyz',
        }).status_code == 400
        assert auth_client.post('/api/nearby-lawyers', json={
            'latitude': 999, 'longitude': 0,
        }).status_code == 400

    def test_search_requires_authentication(self, client):
        assert client.post('/api/nearby-lawyers', json={
            'latitude': 28.6, 'longitude': 77.2,
        }).status_code == 401


class TestCaseSubmission:
    def _first_lawyer_id(self, app_module):
        with app_module.app.app_context():
            return app_module.Lawyer.query.first().id

    def test_submit_case_creates_appointment(self, auth_client, app_module):
        lawyer_id = self._first_lawyer_id(app_module)
        response = auth_client.post('/submit-case', json={
            'lawyer_id': lawyer_id, 'case_type': 'Family Law',
            'case_description': 'Test case', 'payment_amount': 1000,
        })
        assert response.status_code == 200, response.get_data(as_text=True)
        body = response.get_json()
        assert body['success'] is True
        # No gateway is connected, so the payment must not claim to be real.
        assert body['payment_status'] == 'simulated'

    def test_appointment_query_works_after_init(self, auth_client, app_module):
        """The original production 500 came from this exact query."""
        lawyer_id = self._first_lawyer_id(app_module)
        auth_client.post('/submit-case', json={
            'lawyer_id': lawyer_id, 'case_type': 'Civil Law',
            'case_description': 'Query check', 'payment_amount': 500,
        })
        with app_module.app.app_context():
            user = app_module.User.query.filter_by(username='testuser').first()
            rows = (app_module.Appointment.query
                    .filter_by(user_id=user.id)
                    .order_by(app_module.Appointment.consultation_date.desc())
                    .all())
            assert len(rows) >= 1
            # Templates call strftime on this column, so it must be a datetime.
            assert hasattr(rows[0].consultation_date, 'strftime')

    def test_unknown_lawyer_is_rejected(self, auth_client):
        response = auth_client.post('/submit-case', json={
            'lawyer_id': 999999, 'case_type': 'Civil Law',
            'case_description': 'Bad ref', 'payment_amount': 500,
        })
        assert response.status_code == 404

    def test_invalid_payment_amount_is_rejected(self, auth_client, app_module):
        lawyer_id = self._first_lawyer_id(app_module)
        for amount in ('abc', 0, -5):
            response = auth_client.post('/submit-case', json={
                'lawyer_id': lawyer_id, 'case_type': 'Civil Law',
                'case_description': 'Bad amount', 'payment_amount': amount,
            })
            assert response.status_code == 400, f'{amount!r} should be rejected'

    def test_missing_fields_are_rejected(self, auth_client):
        assert auth_client.post('/submit-case', json={}).status_code == 400

    def test_my_appointments_lists_the_booking(self, auth_client, app_module):
        lawyer_id = self._first_lawyer_id(app_module)
        auth_client.post('/submit-case', json={
            'lawyer_id': lawyer_id, 'case_type': 'Tax Law',
            'case_description': 'Listing check', 'payment_amount': 750,
        })
        response = auth_client.get('/my-appointments')
        assert response.status_code == 200
        assert b'Tax Law' in response.data


class TestConfiguration:
    def test_database_url_is_honoured(self, app_module, db_path):
        assert db_path in app_module.app.config['SQLALCHEMY_DATABASE_URI']

    def test_legacy_postgres_scheme_is_normalised(self, app_module, monkeypatch):
        """Render hands out postgres://, which SQLAlchemy 2.x rejects.

        The resolver is exercised directly: re-importing the module would run
        ``init_db`` and try to reach the database.
        """
        monkeypatch.setenv('DATABASE_URL', 'postgres://u:p@host:5432/dbname')
        assert app_module._database_uri().startswith('postgresql://')

        monkeypatch.setenv('DATABASE_URL', 'postgresql://u:p@host:5432/dbname')
        assert app_module._database_uri() == 'postgresql://u:p@host:5432/dbname'

    def test_missing_database_url_falls_back_to_local_sqlite(self, app_module, monkeypatch):
        monkeypatch.delenv('DATABASE_URL', raising=False)
        uri = app_module._database_uri()
        assert uri.startswith('sqlite:///')
        assert 'lawyer_booking.db' in uri

    def test_sqlite_directory_is_created_when_missing(self, app_module, monkeypatch, tmp_path):
        """A configured SQLite path in a new directory must work on first run."""
        target = tmp_path / 'nested' / 'deeper' / 'app.db'
        assert not target.parent.exists()
        monkeypatch.setenv('DATABASE_URL', 'sqlite:///' + str(target))
        uri = app_module._database_uri()
        assert target.parent.is_dir(), 'parent directory should have been created'
        assert uri.endswith('app.db')

    def test_password_is_redacted_from_logged_uri(self, app_module):
        assert app_module._redact_database_uri(
            'postgresql://user:secret@host/db') == 'postgresql://***@host/db'
