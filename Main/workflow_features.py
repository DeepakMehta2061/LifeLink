from ai_features import (
    calculate_emergency_risk_score,
    detect_injury_category,
    detect_severity,
    estimate_ambulance_eta,
)


EMERGENCY_KEYWORDS = [
    'bleeding',
    'unconscious',
    'emergency',
    'accident',
    'fire',
    'injury',
    'not breathing',
    'fracture',
    'burn',
]


KTM_CCTV_ZONES = [
    {
        'keywords': ['baneshwor', 'new baneshwor'],
        'zone_name': 'Baneshwor CCTV Zone',
        'camera_id': 'KTM-CCTV-BNS-01',
    },
    {
        'keywords': ['koteshwor'],
        'zone_name': 'Koteshwor Traffic CCTV Zone',
        'camera_id': 'KTM-CCTV-KTW-02',
    },
    {
        'keywords': ['chabahil'],
        'zone_name': 'Chabahil Chowk CCTV Zone',
        'camera_id': 'KTM-CCTV-CHB-03',
    },
    {
        'keywords': ['kalanki'],
        'zone_name': 'Kalanki Junction CCTV Zone',
        'camera_id': 'KTM-CCTV-KLK-04',
    },
    {
        'keywords': ['ratna park', 'ratnapark'],
        'zone_name': 'Ratna Park CCTV Zone',
        'camera_id': 'KTM-CCTV-RTP-05',
    },
    {
        'keywords': ['thamel'],
        'zone_name': 'Thamel CCTV Zone',
        'camera_id': 'KTM-CCTV-THM-06',
    },
]


def ensure_workflow_schema(cur):
    cur.execute("""
        ALTER TABLE emergencies
        ADD COLUMN IF NOT EXISTS ai_emergency_type TEXT,
        ADD COLUMN IF NOT EXISTS ai_confidence INTEGER,
        ADD COLUMN IF NOT EXISTS ai_keywords TEXT,
        ADD COLUMN IF NOT EXISTS possible_medical_requirements TEXT,
        ADD COLUMN IF NOT EXISTS report_source TEXT DEFAULT 'form',
        ADD COLUMN IF NOT EXISTS reporter_lat DOUBLE PRECISION,
        ADD COLUMN IF NOT EXISTS reporter_lng DOUBLE PRECISION,
        ADD COLUMN IF NOT EXISTS accident_lat DOUBLE PRECISION,
        ADD COLUMN IF NOT EXISTS accident_lng DOUBLE PRECISION,
        ADD COLUMN IF NOT EXISTS report_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        ADD COLUMN IF NOT EXISTS verification_status TEXT DEFAULT 'pending',
        ADD COLUMN IF NOT EXISTS verification_note TEXT,
        ADD COLUMN IF NOT EXISTS verified_at TIMESTAMP,
        ADD COLUMN IF NOT EXISTS hospital_notified_at TIMESTAMP,
        ADD COLUMN IF NOT EXISTS tracking_status TEXT DEFAULT 'reported',
        ADD COLUMN IF NOT EXISTS eta_minutes INTEGER,
        ADD COLUMN IF NOT EXISTS patient_status TEXT,
        ADD COLUMN IF NOT EXISTS more_info_request TEXT
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS emergency_timeline (
            id SERIAL PRIMARY KEY,
            emergency_id INTEGER REFERENCES emergencies(id) ON DELETE CASCADE,
            event_key TEXT NOT NULL,
            event_label TEXT NOT NULL,
            details TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS dispatch_requests (
            id SERIAL PRIMARY KEY,
            emergency_id INTEGER REFERENCES emergencies(id) ON DELETE CASCADE,
            ambulance_id INTEGER REFERENCES ambulances(id),
            status TEXT DEFAULT 'sent',
            sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            responded_at TIMESTAMP
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS hospital_notifications (
            id SERIAL PRIMARY KEY,
            emergency_id INTEGER REFERENCES emergencies(id) ON DELETE CASCADE,
            hospital_id INTEGER REFERENCES hospitals(id),
            status TEXT DEFAULT 'sent',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS police_notifications (
            id SERIAL PRIMARY KEY,
            emergency_id INTEGER REFERENCES emergencies(id) ON DELETE CASCADE,
            cctv_zone TEXT,
            camera_id TEXT,
            cctv_available BOOLEAN DEFAULT FALSE,
            ai_summary TEXT,
            status TEXT DEFAULT 'cctv_review',
            verification_note TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            verified_at TIMESTAMP
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS ambulance_locations (
            id SERIAL PRIMARY KEY,
            emergency_id INTEGER REFERENCES emergencies(id) ON DELETE CASCADE,
            ambulance_id INTEGER REFERENCES ambulances(id),
            lat DOUBLE PRECISION,
            lng DOUBLE PRECISION,
            status TEXT,
            eta_minutes INTEGER,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)


def get_optional_float(data, *keys):
    for key in keys:
        value = data.get(key)
        if value is None or value == '':
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def analyze_emergency_report(data):
    data = data or {}
    report_text = (
        data.get('voice_text')
        or data.get('description')
        or data.get('injury_type')
        or ''
    )
    combined_text = f"{data.get('severity', '')} {report_text}".strip()
    lower_text = combined_text.lower()
    matched_keywords = [
        keyword
        for keyword in EMERGENCY_KEYWORDS
        if keyword in lower_text
    ]

    severity = detect_severity(combined_text)
    injury_category = detect_injury_category(report_text)
    emergency_type = {
        'burn': 'Fire or Burn Injury',
        'fracture': 'Road Accident',
        'cardiac': 'Medical Emergency',
        'breathing': 'Medical Emergency',
        'trauma': 'Road Accident',
        'neurological': 'Critical Injury',
    }.get(injury_category, 'General Emergency')

    requirements = []
    if severity == 'critical':
        requirements.extend(['ICU readiness', 'doctor on duty'])
    if 'bleeding' in lower_text or injury_category == 'trauma':
        requirements.append('blood bank support')
    if injury_category == 'burn':
        requirements.append('burn unit')
    if injury_category in ['neurological', 'trauma']:
        requirements.append('trauma support')
    if not requirements:
        requirements.append('emergency bed')

    confidence = min(98, 58 + (len(matched_keywords) * 8))
    risk_score = calculate_emergency_risk_score({
        'severity': severity,
        'injury_type': report_text,
    })

    return {
        'emergency_type': emergency_type,
        'severity': severity,
        'injury_category': injury_category,
        'keywords': matched_keywords,
        'medical_requirements': requirements,
        'confidence_score': confidence,
        'risk_score': risk_score,
    }


def match_cctv_zone(location_name):
    location_text = (location_name or '').lower()
    for zone in KTM_CCTV_ZONES:
        if any(keyword in location_text for keyword in zone['keywords']):
            return {
                'cctv_available': True,
                'zone_name': zone['zone_name'],
                'camera_id': zone['camera_id'],
                'feed_label': 'Mock CCTV feed for hackathon demo',
            }

    return {
        'cctv_available': False,
        'zone_name': 'No nearby KTM CCTV zone matched',
        'camera_id': None,
        'feed_label': 'No mock CCTV feed available',
    }


def add_timeline_event(cur, emergency_id, event_key, event_label, details=None):
    cur.execute("""
        INSERT INTO emergency_timeline (emergency_id, event_key, event_label, details)
        VALUES (%s, %s, %s, %s)
    """, (emergency_id, event_key, event_label, details))


def create_initial_timeline(cur, emergency_id, analysis):
    add_timeline_event(cur, emergency_id, 'reported', 'Reported', 'Emergency report received.')
    add_timeline_event(
        cur,
        emergency_id,
        'ai_analysis_completed',
        'AI Analysis Completed',
        f"{analysis['emergency_type']} marked {analysis['severity']} with {analysis['confidence_score']}% confidence."
    )
    add_timeline_event(cur, emergency_id, 'location_detected', 'Location Detected', 'Reporter and accident location saved.')


def create_police_cctv_notification(cur, emergency_id, cctv_match, analysis):
    if not cctv_match.get('cctv_available'):
        add_timeline_event(
            cur,
            emergency_id,
            'cctv_not_matched',
            'CCTV Not Matched',
            'No mock Kathmandu CCTV zone matched this location.'
        )
        return False

    ai_summary = (
        f"Possible {analysis['emergency_type']} in {cctv_match['zone_name']}. "
        f"Severity {analysis['severity']} with {analysis['confidence_score']}% AI confidence."
    )
    cur.execute("""
        INSERT INTO police_notifications (
            emergency_id,
            cctv_zone,
            camera_id,
            cctv_available,
            ai_summary,
            status
        )
        VALUES (%s, %s, %s, TRUE, %s, 'cctv_review')
    """, (
        emergency_id,
        cctv_match['zone_name'],
        cctv_match['camera_id'],
        ai_summary,
    ))

    add_timeline_event(
        cur,
        emergency_id,
        'cctv_matched',
        'CCTV Zone Matched',
        f"{cctv_match['zone_name']} using {cctv_match['camera_id']}."
    )
    add_timeline_event(
        cur,
        emergency_id,
        'police_alert_sent',
        'Police CCTV Alert Sent',
        'Internal demo alert sent to Police Control Dashboard.'
    )
    return True


def send_dispatch_requests(cur, emergency_id, limit=5):
    cur.execute("""
        SELECT id
        FROM ambulances
        WHERE status = 'free'
        ORDER BY id ASC
        LIMIT %s
    """, (limit,))

    ambulance_rows = cur.fetchall()
    for row in ambulance_rows:
        cur.execute("""
            INSERT INTO dispatch_requests (emergency_id, ambulance_id, status)
            VALUES (%s, %s, 'sent')
        """, (emergency_id, row[0]))

    if ambulance_rows:
        add_timeline_event(
            cur,
            emergency_id,
            'dispatch_requests_sent',
            'Dispatch Requests Sent',
            f"Request sent to {len(ambulance_rows)} nearby ambulance drivers."
        )

    return [row[0] for row in ambulance_rows]


def mark_dispatch_accepted(cur, emergency_id, ambulance_id):
    cur.execute("""
        UPDATE dispatch_requests
        SET status = 'cancelled', responded_at = CURRENT_TIMESTAMP
        WHERE emergency_id = %s
          AND status = 'sent'
          AND ambulance_id <> %s
    """, (emergency_id, ambulance_id))

    cur.execute("""
        UPDATE dispatch_requests
        SET status = 'accepted', responded_at = CURRENT_TIMESTAMP
        WHERE emergency_id = %s
          AND ambulance_id = %s
    """, (emergency_id, ambulance_id))

    add_timeline_event(
        cur,
        emergency_id,
        'ambulance_assigned',
        'Ambulance Assigned',
        f"Ambulance {ambulance_id} accepted the case."
    )


def notify_hospital(cur, emergency_id, hospital_id):
    if not hospital_id:
        return

    cur.execute("""
        INSERT INTO hospital_notifications (emergency_id, hospital_id, status)
        VALUES (%s, %s, 'sent')
    """, (emergency_id, hospital_id))

    cur.execute("""
        UPDATE emergencies
        SET hospital_notified_at = CURRENT_TIMESTAMP
        WHERE id = %s
    """, (emergency_id,))

    add_timeline_event(cur, emergency_id, 'hospital_recommended', 'Hospital Recommended', f"Hospital {hospital_id} selected.")
    add_timeline_event(cur, emergency_id, 'hospital_notified', 'Hospital Notified', f"Hospital {hospital_id} notified.")


def update_tracking_status(cur, emergency_id, status, ambulance_id=None, lat=None, lng=None, eta_minutes=None):
    cur.execute("""
        UPDATE emergencies
        SET tracking_status = %s,
            eta_minutes = COALESCE(%s, eta_minutes)
        WHERE id = %s
    """, (status, eta_minutes, emergency_id))

    if ambulance_id or lat is not None or lng is not None:
        cur.execute("""
            INSERT INTO ambulance_locations (emergency_id, ambulance_id, lat, lng, status, eta_minutes)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (emergency_id, ambulance_id, lat, lng, status, eta_minutes))

    event_labels = {
        'assigned': 'Live Tracking Started',
        'en_route': 'En Route',
        'near_hospital': 'Near Hospital',
        'arrived': 'Patient Arrived',
        'completed': 'Case Completed',
    }
    if status in event_labels:
        add_timeline_event(cur, emergency_id, status, event_labels[status], f"Tracking status updated to {status}.")


def calculate_demo_eta(distance_km=None, severity='moderate'):
    if distance_km is not None:
        eta = estimate_ambulance_eta(distance_km)
        if eta is not None:
            return eta

    return {
        'critical': 4,
        'moderate': 6,
        'mild': 8,
    }.get((severity or 'moderate').lower(), 6)
