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

## Project Structure

```
LAWYER/
├── app.py                 # Main Flask application
├── requirements.txt       # Python dependencies
├── templates/            # HTML templates
│   ├── login.html        # Login page
│   ├── signup.html       # Sign up page
│   ├── dashboard.html    # User dashboard
│   ├── book_lawyer.html  # Find nearby lawyers
│   ├── lawyer_detail.html # Lawyer profile & booking
│   ├── confirmation.html # Booking confirmation
│   └── my_appointments.html # View appointments
├── static/               # Static files
│   └── css/
│       └── style.css     # Stylesheet
└── README.md             # This file
```

## Database Models

- **User**: User accounts with authentication
- **Lawyer**: Lawyer profiles with location coordinates
- **Appointment**: Booking records with case details and payment

## API Endpoints

- `GET /` - Redirects to login or dashboard
- `GET /signup` - Sign up page
- `POST /signup` - Create new account
- `GET /login` - Login page
- `POST /login` - User login
- `GET /dashboard` - User dashboard
- `GET /book-lawyer` - Find nearby lawyers
- `POST /api/nearby-lawyers` - Get nearby lawyers (JSON)
- `GET /lawyer/<id>` - Lawyer detail page
- `POST /submit-case` - Submit case and payment
- `GET /confirmation/<id>` - Booking confirmation
- `GET /my-appointments` - View all appointments
- `GET /logout` - Logout

## Notes

- Location services require HTTPS in production (works on localhost for development)
- Payment processing is simulated (no actual payment gateway)
- Sample lawyers are automatically added on first run
- Database file `lawyer_booking.db` is created automatically

## License

This project is open source and available for use.

