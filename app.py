from flask import Flask, render_template, request, jsonify, redirect, url_for, session, flash
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
from math import radians, cos, sin, asin, sqrt
import os

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-only-change-me')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///lawyer_booking.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

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
    email = db.Column(db.String(100))
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
    consultation_date = db.Column(db.DateTime, nullable=False)
    consultation_time = db.Column(db.String(20), nullable=False)
    status = db.Column(db.String(20), default='confirmed')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# Helper function to calculate distance between two coordinates
def calculate_distance(lat1, lon1, lat2, lon2):
    """Calculate the great circle distance between two points on Earth (in km)"""
    R = 6371  # Radius of earth in kilometers
    
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    
    a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
    c = 2 * asin(sqrt(a))
    
    return R * c

# Routes
@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        data = request.get_json()
        username = data.get('username')
        email = data.get('email')
        password = data.get('password')
        phone = data.get('phone', '')
        
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
        data = request.get_json()
        username = data.get('username')
        password = data.get('password')
        
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
    
    data = request.get_json()
    user_lat = float(data.get('latitude'))
    user_lon = float(data.get('longitude'))
    max_distance = float(data.get('max_distance', 50))  # Default 50km
    
    # Get all lawyers
    all_lawyers = Lawyer.query.all()
    
    # Calculate distance and filter nearby lawyers
    nearby = []
    for lawyer in all_lawyers:
        distance = calculate_distance(user_lat, user_lon, lawyer.latitude, lawyer.longitude)
        if distance <= max_distance:
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
    
    return jsonify({'lawyers': nearby})

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
    
    data = request.get_json()
    lawyer_id = data.get('lawyer_id')
    case_type = data.get('case_type')
    case_description = data.get('case_description')
    payment_amount = data.get('payment_amount')
    
    if not all([lawyer_id, case_type, case_description, payment_amount]):
        return jsonify({'success': False, 'message': 'All fields are required'}), 400
    
    # Generate consultation date and time (next available slot)
    consultation_datetime = datetime.now() + timedelta(days=1)
    consultation_datetime = consultation_datetime.replace(hour=10, minute=0, second=0, microsecond=0)
    
    appointment = Appointment(
        user_id=session['user_id'],
        lawyer_id=lawyer_id,
        case_type=case_type,
        case_description=case_description,
        payment_amount=float(payment_amount),
        payment_status='paid',
        consultation_date=consultation_datetime.date(),
        consultation_time=consultation_datetime.strftime('%I:%M %p'),
        status='confirmed'
    )
    
    db.session.add(appointment)
    db.session.commit()
    
    return jsonify({
        'success': True,
        'appointment_id': appointment.id,
        'consultation_date': consultation_datetime.strftime('%B %d, %Y'),
        'consultation_time': consultation_datetime.strftime('%I:%M %p')
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

# Initialize database
def init_db():
    with app.app_context():
        db.create_all()
        # Add sample lawyers if database is empty
        if Lawyer.query.count() == 0:
            sample_lawyers = [
                Lawyer(
                    name='John Smith',
                    specialization='Criminal Law',
                    experience=15,
                    rating=4.9,
                    bio='Experienced criminal defense attorney with over 15 years of practice.',
                    phone='+1-555-0101',
                    email='john.smith@lawfirm.com',
                    latitude=40.7128,
                    longitude=-74.0060,
                    location='New York, NY',
                    hourly_rate=250.00,
                    image_url='https://via.placeholder.com/300x300?text=John+Smith'
                ),
                Lawyer(
                    name='Sarah Johnson',
                    specialization='Family Law',
                    experience=12,
                    rating=4.8,
                    bio='Compassionate family law attorney specializing in divorce and child custody.',
                    phone='+1-555-0102',
                    email='sarah.johnson@lawfirm.com',
                    latitude=34.0522,
                    longitude=-118.2437,
                    location='Los Angeles, CA',
                    hourly_rate=200.00,
                    image_url='https://via.placeholder.com/300x300?text=Sarah+Johnson'
                ),
                Lawyer(
                    name='Michael Chen',
                    specialization='Corporate Law',
                    experience=20,
                    rating=4.7,
                    bio='Corporate law expert with extensive experience in mergers and acquisitions.',
                    phone='+1-555-0103',
                    email='michael.chen@lawfirm.com',
                    latitude=37.7749,
                    longitude=-122.4194,
                    location='San Francisco, CA',
                    hourly_rate=300.00,
                    image_url='https://via.placeholder.com/300x300?text=Michael+Chen'
                ),
                Lawyer(
                    name='Emily Davis',
                    specialization='Immigration Law',
                    experience=8,
                    rating=4.6,
                    bio='Dedicated immigration attorney helping individuals navigate the immigration process.',
                    phone='+1-555-0104',
                    email='emily.davis@lawfirm.com',
                    latitude=41.8781,
                    longitude=-87.6298,
                    location='Chicago, IL',
                    hourly_rate=180.00,
                    image_url='https://via.placeholder.com/300x300?text=Emily+Davis'
                ),
                Lawyer(
                    name='Robert Williams',
                    specialization='Personal Injury',
                    experience=18,
                    rating=4.8,
                    bio='Personal injury attorney with a proven track record of securing maximum compensation.',
                    phone='+1-555-0105',
                    email='robert.williams@lawfirm.com',
                    latitude=29.7604,
                    longitude=-95.3698,
                    location='Houston, TX',
                    hourly_rate=220.00,
                    image_url='https://via.placeholder.com/300x300?text=Robert+Williams'
                ),
                Lawyer(
                    name='Lisa Anderson',
                    specialization='Real Estate Law',
                    experience=10,
                    rating=4.7,
                    bio='Real estate attorney specializing in property transactions and disputes.',
                    phone='+1-555-0106',
                    email='lisa.anderson@lawfirm.com',
                    latitude=25.7617,
                    longitude=-80.1918,
                    location='Miami, FL',
                    hourly_rate=190.00,
                    image_url='https://via.placeholder.com/300x300?text=Lisa+Anderson'
                )
            ]
            db.session.add_all(sample_lawyers)
            db.session.commit()

# Initialize database for both local development and Render/Gunicorn
init_db()

if __name__ == '__main__':
    app.run(debug=True, host='127.0.0.1', port=5000)

