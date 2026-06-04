# LifeLink

LifeLink is a Flask and PostgreSQL emergency response system that connects three important groups in one workflow:

- People reporting an emergency
- Ambulance drivers receiving and accepting alerts
- Hospitals updating capacity and availability

The goal is to reduce manual coordination during emergencies by helping route reports, ambulances, and hospital recommendations through one simple web app.

## Core Modules

### 1. Emergency Reporting

Users can submit an emergency report with their name, location, severity, and injury type. The system stores the emergency and assigns an available ambulance when possible.

### 2. Ambulance Driver Alerts

Drivers can view pending emergency alerts, accept a case, and move the case through the response flow.

### 3. Hospital Capacity Updates

Hospitals can update available beds, ICU capacity, doctor availability, and special facilities such as trauma support, neurosurgeon support, burn unit, and blood bank.

## Added AI-Like Features

These features are rule-based and do not require model training.

### Emergency Severity Detection

Function: `detect_severity(text)`

Detects emergency severity from text:

- `critical`: bleeding, unconscious, not breathing, severe accident
- `moderate`: fracture, pain, injury
- `mild`: small injury, minor pain

### Smart Nearest Ambulance Selection

The `/api/emergency` route now supports nearest ambulance selection when coordinates are available.

- Uses simple Euclidean distance with latitude and longitude
- Supports `lat/lng` or `latitude/longitude`
- Falls back to the original first-free ambulance behavior if coordinates are missing
- Keeps the existing API response structure unchanged

### Hospital Scoring System

The `/api/suggest-hospital` route now ranks hospitals using a scoring formula:

```text
score = (available_beds * 2) + (icu_available * 5) + (doctors_available * 3)
```

Trauma support adds a bonus:

```text
+10 if has_trauma is true
```

Hospitals are returned sorted by score in descending order.

### Emergency Summary Generator

Function: `generate_emergency_summary(emergency_data)`

Creates a short summary such as:

```text
Critical emergency at Main Road, injury type bleeding. Ambulance assigned.
```

### Additional Helper-Only AI Features

The project also includes helper functions for future integration:

- `detect_injury_category(text)`: detects burn, fracture, cardiac, breathing, trauma, neurological, or general cases
- `calculate_emergency_risk_score(emergency_data)`: returns a 0-100 rule-based risk score
- `estimate_ambulance_eta(distance_km, average_speed_kmph=30)`: estimates ETA in minutes
- `is_possible_duplicate_emergency(new_emergency, existing_emergencies)`: checks for duplicate reports
- `explain_hospital_match(hospital)`: explains why a hospital was recommended
- `get_hospital_capacity_status(hospital)`: labels hospital capacity as `low`, `medium`, or `good`
- `generate_driver_alert_message(emergency_data)`: creates a driver-friendly alert message
- `suggest_route_decision(emergency_data)`: suggests whether to go directly to hospital or reach patient first
- `generate_first_aid_checklist(injury_type)`: returns basic first-aid checklist steps

## Tech Stack

- Backend: Python, Flask
- Database: PostgreSQL
- Frontend: HTML, CSS, JavaScript
- Database Driver: psycopg2
- Environment Variables: python-dotenv

## Project Structure

```text
LifeLink/
├── Main/
│   ├── app.py
│   ├── ai_features.py
│   ├── database.py
│   └── .env
├── static/
│   ├── script.js
│   └── style.css
├── templates/
│   ├── index.html
│   ├── user.html
│   ├── driver.html
│   └── hospital.html
└── README.md
```

## Environment Variables

Create or update `Main/.env` with your PostgreSQL settings:

```env
DB_HOST=localhost
DB_NAME=your_database_name
DB_USER=your_database_user
DB_PASSWORD=your_database_password
```

## Run The Project

From the project root:

```bash
cd Main
python3 app.py
```

Then open the Flask URL shown in the terminal, usually:

```text
http://127.0.0.1:5000
```

## Validation

The backend files can be checked with:

```bash
python3 -m py_compile Main/app.py Main/ai_features.py
```

## Safety Notes

The added AI-like features were implemented with backward compatibility in mind:

- No existing routes were removed
- No frontend files were changed
- No database tables were renamed
- No database schema changes were required
- Existing API response structures were preserved
- New helper functions are available for future integration
