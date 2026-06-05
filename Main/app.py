from flask import Flask, render_template, request, jsonify
from database import get_connection
from ai_features import (
    calculate_emergency_risk_score,
    calculate_hospital_score,
    detect_injury_category,
    detect_severity,
    estimate_ambulance_eta,
    explain_hospital_match,
    explain_severity_detection,
    generate_driver_alert_message,
    generate_emergency_summary,
    generate_first_aid_checklist,
    get_hospital_capacity_status,
    get_priority_label,
    get_triage_confidence,
    suggest_route_decision,
)
from workflow_features import (
    add_timeline_event,
    analyze_emergency_report,
    calculate_demo_eta,
    create_police_cctv_notification,
    create_initial_timeline,
    ensure_workflow_schema,
    get_optional_float,
    mark_dispatch_accepted,
    match_cctv_zone,
    notify_hospital,
    send_dispatch_requests,
    update_tracking_status,
)
import os

basedir = os.path.dirname(os.path.abspath(__file__))
static_path = os.path.join(basedir, '..', 'static')
template_path = os.path.join(basedir, '..', 'templates')

print(f"Base directory: {basedir}")
print(f"Static folder: {static_path}")
print(f"Template folder: {template_path}")
print(f"Static folder exists: {os.path.exists(static_path)}")
print(f"Template folder exists: {os.path.exists(template_path)}")

app = Flask(
    __name__,
    static_folder=static_path,
    static_url_path='/static',
    template_folder=template_path
)


# NEW FEATURE ADDED
def get_float_value(data, *keys):
    for key in keys:
        value = data.get(key)
        if value is None or value == '':
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


# NEW FEATURE ADDED
def get_emergency_coordinates(data):
    return (
        get_float_value(data, 'lat', 'latitude'),
        get_float_value(data, 'lng', 'longitude')
    )


# NEW FEATURE ADDED
def get_ambulance_coordinate_columns(cur):
    cur.execute("""
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = 'ambulances'
          AND column_name IN ('lat', 'lng', 'latitude', 'longitude')
    """)
    columns = {row[0] for row in cur.fetchall()}

    if 'lat' in columns and 'lng' in columns:
        return 'lat', 'lng'
    if 'latitude' in columns and 'longitude' in columns:
        return 'latitude', 'longitude'
    return None, None


# NEW FEATURE ADDED
def calculate_distance(lat1, lng1, lat2, lng2):
    return ((lat1 - lat2) ** 2 + (lng1 - lng2) ** 2) ** 0.5


# NEW FEATURE ADDED
def find_best_available_ambulance(cur, emergency_lat=None, emergency_lng=None):
    if emergency_lat is not None and emergency_lng is not None:
        lat_column, lng_column = get_ambulance_coordinate_columns(cur)

        if lat_column and lng_column:
            cur.execute(f"""
                SELECT id, driver_name, vehicle_no, {lat_column}, {lng_column}
                FROM ambulances
                WHERE status = 'free'
                  AND {lat_column} IS NOT NULL
                  AND {lng_column} IS NOT NULL
            """)

            ambulances = []
            for row in cur.fetchall():
                ambulance_lat = get_float_value({'lat': row[3]}, 'lat')
                ambulance_lng = get_float_value({'lng': row[4]}, 'lng')
                if ambulance_lat is None or ambulance_lng is None:
                    continue
                ambulances.append((
                    calculate_distance(emergency_lat, emergency_lng, ambulance_lat, ambulance_lng),
                    row
                ))

            if ambulances:
                return min(ambulances, key=lambda item: item[0])[1]

    cur.execute("""
        SELECT id, driver_name, vehicle_no
        FROM ambulances
        WHERE status = 'free'
        LIMIT 1
    """)
    return cur.fetchone()


def get_hospital_recommendations(cur, severity='moderate', injury_type=''):
    if severity == 'critical':
        cur.execute("""
            SELECT id, name, location, available_beds, icu_available, doctors_available,
                   has_trauma, has_neurosurgeon, has_burn_unit, has_blood_bank
            FROM hospitals
            WHERE icu_available > 0
            ORDER BY has_trauma DESC, icu_available DESC, available_beds DESC
            LIMIT 5
        """)
    else:
        cur.execute("""
            SELECT id, name, location, available_beds, icu_available, doctors_available,
                   has_trauma, has_neurosurgeon, has_burn_unit, has_blood_bank
            FROM hospitals
            WHERE available_beds > 0
            ORDER BY available_beds DESC
            LIMIT 5
        """)

    rows = cur.fetchall()
    hospitals = []
    for row in rows:
        hospitals.append({
            'id': row[0],
            'name': row[1],
            'location': row[2],
            'available_beds': row[3],
            'icu_available': row[4],
            'doctors_available': row[5],
            'has_trauma': row[6],
            'has_neurosurgeon': row[7],
            'has_burn_unit': row[8],
            'has_blood_bank': row[9]
        })
    return hospitals


# NEW FEATURE ADDED
def get_scored_hospital_recommendations(cur, severity='moderate', injury_type=''):
    where_clause = "icu_available > 0" if severity == 'critical' else "available_beds > 0"

    cur.execute(f"""
        SELECT id, name, location, available_beds, icu_available, doctors_available,
               has_trauma, has_neurosurgeon, has_burn_unit, has_blood_bank
        FROM hospitals
        WHERE {where_clause}
        ORDER BY (
            (COALESCE(available_beds, 0) * 2) +
            (COALESCE(icu_available, 0) * 5) +
            (COALESCE(doctors_available, 0) * 3) +
            (CASE WHEN has_trauma THEN 10 ELSE 0 END)
        ) DESC
        LIMIT 5
    """)

    rows = cur.fetchall()
    hospitals = []
    for row in rows:
        hospitals.append({
            'id': row[0],
            'name': row[1],
            'location': row[2],
            'available_beds': row[3],
            'icu_available': row[4],
            'doctors_available': row[5],
            'has_trauma': row[6],
            'has_neurosurgeon': row[7],
            'has_burn_unit': row[8],
            'has_blood_bank': row[9]
        })
    return hospitals

#Load the unified SPA HTML 
@app.route('/')

def home():
    return render_template('index.html')
# API Routes talk to the database
@app.route('/api/emergency', methods=['POST'])
def submit_emergency():
    data = request.json
    conn = get_connection()
    cur = conn.cursor()
    ensure_workflow_schema(cur)

    # Save emergency to database
    cur.execute("""
        INSERT INTO emergencies (reporter_name, location_name, severity, injury_type, status)
        VALUES (%s, %s, %s, %s, 'pending')
        RETURNING id
    """, (
        data['reporter_name'],
        data['location_name'],
        data['severity'],
        data['injury_type']
    ))

    # Get inserted emergency ID
    emergency_id = cur.fetchone()[0]

    # NEW FEATURE ADDED
    # Find the nearest free ambulance when coordinates exist; otherwise use original fallback.
    emergency_lat, emergency_lng = get_emergency_coordinates(data)
    ambulance = find_best_available_ambulance(cur, emergency_lat, emergency_lng)

    if ambulance:
        ambulance_id = ambulance[0]

        # Assign ambulance
        cur.execute("""
            UPDATE emergencies
            SET ambulance_id = %s,
                status = 'ambulance_assigned'
            WHERE id = %s
        """, (ambulance_id, emergency_id))

        # Mark ambulance busy
        cur.execute("""
            UPDATE ambulances
            SET status = 'busy'
            WHERE id = %s
        """, (ambulance_id,))

        conn.commit()
        result = jsonify({
            'success': True,
            'emergency_id': emergency_id,
            'ambulance': {
                'id': ambulance[0],
                'driver_name': ambulance[1],
                'vehicle_no': ambulance[2]
            }
        })

        cur.close()
        conn.close()
        return result

    else:
        conn.commit()
        result = jsonify({
            'success': False,
            'message': 'No ambulance available right now'
        })

        cur.close()
        conn.close()
        return result
    

@app.route('/api/workflow/report', methods=['POST'])
def submit_workflow_report():
    data = request.json or {}
    analysis = analyze_emergency_report(data)
    severity = data.get('severity') or analysis['severity']
    injury_type = (
        data.get('injury_type')
        or data.get('description')
        or data.get('voice_text')
        or 'Unknown'
    )

    conn = get_connection()
    cur = conn.cursor()
    ensure_workflow_schema(cur)

    reporter_lat = get_optional_float(data, 'reporter_lat', 'user_lat')
    reporter_lng = get_optional_float(data, 'reporter_lng', 'user_lng')
    accident_lat = get_optional_float(data, 'accident_lat', 'lat', 'latitude')
    accident_lng = get_optional_float(data, 'accident_lng', 'lng', 'longitude')

    location_name = data.get('location_name') or data.get('location') or 'Unknown location'
    cctv_match = match_cctv_zone(location_name)
    initial_status = 'police_review' if cctv_match['cctv_available'] else 'admin_review'

    cur.execute("""
        INSERT INTO emergencies (
            reporter_name,
            location_name,
            severity,
            injury_type,
            status,
            ai_emergency_type,
            ai_confidence,
            ai_keywords,
            possible_medical_requirements,
            report_source,
            reporter_lat,
            reporter_lng,
            accident_lat,
            accident_lng,
            verification_status,
            tracking_status,
            patient_status
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'pending', 'reported', %s)
        RETURNING id
    """, (
        data.get('reporter_name') or 'Unknown reporter',
        location_name,
        severity,
        injury_type,
        initial_status,
        analysis['emergency_type'],
        analysis['confidence_score'],
        ', '.join(analysis['keywords']),
        ', '.join(analysis['medical_requirements']),
        data.get('report_source') or ('voice' if data.get('voice_text') else 'form'),
        reporter_lat,
        reporter_lng,
        accident_lat,
        accident_lng,
        data.get('patient_status') or injury_type,
    ))

    emergency_id = cur.fetchone()[0]
    create_initial_timeline(cur, emergency_id, analysis)
    police_alert_created = create_police_cctv_notification(cur, emergency_id, cctv_match, analysis)

    conn.commit()
    cur.close()
    conn.close()

    return jsonify({
        'success': True,
        'emergency_id': emergency_id,
        'status': initial_status,
        'message': 'Report sent to Police CCTV verification' if police_alert_created else 'Report sent to admin verification',
        'ai_analysis': analysis,
        'cctv_match': cctv_match,
        'police_alert_created': police_alert_created
    })


@app.route('/api/admin/reports', methods=['GET'])
def get_admin_reports():
    conn = get_connection()
    cur = conn.cursor()
    ensure_workflow_schema(cur)

    cur.execute("""
        SELECT id, reporter_name, location_name, severity, injury_type, status,
               ai_emergency_type, ai_confidence, ai_keywords,
               possible_medical_requirements, report_source,
               verification_status, verification_note, more_info_request,
               report_time
        FROM emergencies
        WHERE status IN ('admin_review', 'more_info_requested')
           OR verification_status = 'more_info_requested'
        ORDER BY report_time DESC, id DESC
        LIMIT 30
    """)

    rows = cur.fetchall()
    conn.commit()
    cur.close()
    conn.close()

    reports = []
    for row in rows:
        reports.append({
            'id': row[0],
            'reporter_name': row[1],
            'location_name': row[2],
            'severity': row[3],
            'injury_type': row[4],
            'status': row[5],
            'ai_emergency_type': row[6],
            'ai_confidence': row[7],
            'ai_keywords': row[8],
            'possible_medical_requirements': row[9],
            'report_source': row[10],
            'verification_status': row[11],
            'verification_note': row[12],
            'more_info_request': row[13],
            'report_time': row[14].isoformat() if row[14] else None
        })

    return jsonify(reports)


@app.route('/api/admin/all-reports', methods=['GET'])
def get_all_admin_reports():
    conn = get_connection()
    cur = conn.cursor()
    ensure_workflow_schema(cur)

    cur.execute("""
        SELECT e.id, e.reporter_name, e.location_name, e.severity, e.injury_type,
               e.status, e.verification_status, e.tracking_status,
               e.ai_emergency_type, e.ai_confidence, e.ai_keywords,
               e.report_time, e.created_at, e.eta_minutes,
               a.driver_name, a.vehicle_no,
               h.name AS hospital_name
        FROM emergencies e
        LEFT JOIN ambulances a ON e.ambulance_id = a.id
        LEFT JOIN hospitals h ON e.hospital_id = h.id
        ORDER BY COALESCE(e.report_time, e.created_at) DESC, e.id DESC
        LIMIT 100
    """)

    rows = cur.fetchall()
    conn.commit()
    cur.close()
    conn.close()

    reports = []
    for row in rows:
        report_time = row[11] or row[12]
        reports.append({
            'id': row[0],
            'reporter_name': row[1],
            'location_name': row[2],
            'severity': row[3],
            'injury_type': row[4],
            'status': row[5],
            'verification_status': row[6],
            'tracking_status': row[7],
            'ai_emergency_type': row[8],
            'ai_confidence': row[9],
            'ai_keywords': row[10],
            'report_time': report_time.isoformat() if report_time else None,
            'eta_minutes': row[13],
            'driver_name': row[14],
            'vehicle_no': row[15],
            'hospital_name': row[16]
        })

    return jsonify(reports)


@app.route('/api/admin/verify/<int:emergency_id>', methods=['POST'])
def verify_admin_report(emergency_id):
    data = request.json or {}
    action = data.get('action', 'verify')
    note = data.get('note', '')

    conn = get_connection()
    cur = conn.cursor()
    ensure_workflow_schema(cur)

    if action == 'reject':
        cur.execute("""
            UPDATE emergencies
            SET status = 'rejected',
                verification_status = 'rejected',
                verification_note = %s
            WHERE id = %s
        """, (note, emergency_id))
        add_timeline_event(cur, emergency_id, 'admin_rejected', 'Admin Rejected', note or 'Report rejected by admin.')
        response = {'success': True, 'status': 'rejected'}
    elif action == 'more_info':
        cur.execute("""
            UPDATE emergencies
            SET status = 'more_info_requested',
                verification_status = 'more_info_requested',
                more_info_request = %s
            WHERE id = %s
        """, (note or 'More information requested by admin.', emergency_id))
        add_timeline_event(cur, emergency_id, 'more_info_requested', 'More Information Requested', note)
        response = {'success': True, 'status': 'more_info_requested'}
    else:
        cur.execute("""
            UPDATE emergencies
            SET status = 'pending',
                verification_status = 'verified',
                verification_note = %s,
                verified_at = CURRENT_TIMESTAMP
            WHERE id = %s
        """, (note or 'Verified by admin.', emergency_id))
        add_timeline_event(cur, emergency_id, 'admin_verified', 'Admin Verified', note or 'Report verified by admin.')
        ambulance_ids = send_dispatch_requests(cur, emergency_id)
        response = {
            'success': True,
            'status': 'verified',
            'dispatch_request_count': len(ambulance_ids),
            'ambulance_ids': ambulance_ids
        }

    conn.commit()
    cur.close()
    conn.close()
    return jsonify(response)


@app.route('/api/emergency/<int:emergency_id>/timeline', methods=['GET'])
def get_emergency_timeline(emergency_id):
    conn = get_connection()
    cur = conn.cursor()
    ensure_workflow_schema(cur)

    cur.execute("""
        SELECT event_key, event_label, details, created_at
        FROM emergency_timeline
        WHERE emergency_id = %s
        ORDER BY created_at ASC, id ASC
    """, (emergency_id,))

    rows = cur.fetchall()
    conn.commit()
    cur.close()
    conn.close()

    return jsonify([{
        'event_key': row[0],
        'event_label': row[1],
        'details': row[2],
        'created_at': row[3].isoformat() if row[3] else None
    } for row in rows])


@app.route('/api/hospital/notifications', methods=['GET'])
def get_hospital_notifications():
    hospital_id = request.args.get('hospital_id')
    conn = get_connection()
    cur = conn.cursor()
    ensure_workflow_schema(cur)

    params = []
    hospital_filter = ''
    if hospital_id:
        hospital_filter = 'AND hn.hospital_id = %s'
        params.append(hospital_id)

    cur.execute(f"""
        SELECT hn.id, hn.status, hn.created_at,
               e.id, e.location_name, e.severity, e.injury_type,
               e.ai_emergency_type, e.patient_status, e.tracking_status,
               e.eta_minutes,
               a.driver_name, a.vehicle_no,
               h.name, h.location
        FROM hospital_notifications hn
        JOIN emergencies e ON hn.emergency_id = e.id
        LEFT JOIN ambulances a ON e.ambulance_id = a.id
        LEFT JOIN hospitals h ON hn.hospital_id = h.id
        WHERE 1 = 1 {hospital_filter}
        ORDER BY hn.created_at DESC
        LIMIT 20
    """, tuple(params))

    rows = cur.fetchall()
    conn.commit()
    cur.close()
    conn.close()

    return jsonify([{
        'notification_id': row[0],
        'notification_status': row[1],
        'created_at': row[2].isoformat() if row[2] else None,
        'emergency_id': row[3],
        'location_name': row[4],
        'severity': row[5],
        'injury_type': row[6],
        'emergency_type': row[7],
        'patient_status': row[8],
        'tracking_status': row[9],
        'eta_minutes': row[10],
        'driver_name': row[11],
        'vehicle_no': row[12],
        'hospital_name': row[13],
        'hospital_location': row[14]
    } for row in rows])


@app.route('/api/police/notifications', methods=['GET'])
def get_police_notifications():
    conn = get_connection()
    cur = conn.cursor()
    ensure_workflow_schema(cur)

    cur.execute("""
        SELECT pn.id, pn.status, pn.cctv_zone, pn.camera_id, pn.ai_summary,
               pn.verification_note, pn.created_at, pn.verified_at,
               e.id, e.reporter_name, e.location_name, e.severity, e.injury_type,
               e.ai_emergency_type, e.ai_confidence, e.tracking_status, e.eta_minutes
        FROM police_notifications pn
        JOIN emergencies e ON pn.emergency_id = e.id
        ORDER BY pn.created_at DESC
        LIMIT 30
    """)

    rows = cur.fetchall()
    conn.commit()
    cur.close()
    conn.close()

    return jsonify([{
        'notification_id': row[0],
        'status': row[1],
        'cctv_zone': row[2],
        'camera_id': row[3],
        'ai_summary': row[4],
        'verification_note': row[5],
        'created_at': row[6].isoformat() if row[6] else None,
        'verified_at': row[7].isoformat() if row[7] else None,
        'emergency_id': row[8],
        'reporter_name': row[9],
        'location_name': row[10],
        'severity': row[11],
        'injury_type': row[12],
        'emergency_type': row[13],
        'ai_confidence': row[14],
        'tracking_status': row[15],
        'eta_minutes': row[16]
    } for row in rows])


@app.route('/api/police/verify/<int:notification_id>', methods=['POST'])
def verify_police_notification(notification_id):
    data = request.json or {}
    action = data.get('action', 'confirm')
    note = data.get('note', '')

    conn = get_connection()
    cur = conn.cursor()
    ensure_workflow_schema(cur)

    cur.execute("""
        SELECT emergency_id
        FROM police_notifications
        WHERE id = %s
    """, (notification_id,))
    row = cur.fetchone()

    if not row:
        cur.close()
        conn.close()
        return jsonify({'success': False, 'message': 'Police notification not found'}), 404

    emergency_id = row[0]
    if action == 'no_accident':
        cur.execute("""
            UPDATE police_notifications
            SET status = 'no_accident',
                verification_note = %s,
                verified_at = CURRENT_TIMESTAMP
            WHERE id = %s
        """, (note or 'Police CCTV review found no visible accident.', notification_id))
        cur.execute("""
            UPDATE emergencies
            SET status = 'rejected',
                verification_status = 'rejected',
                verification_note = %s
            WHERE id = %s
        """, (note or 'No accident confirmed by mock CCTV review.', emergency_id))
        add_timeline_event(
            cur,
            emergency_id,
            'police_no_accident',
            'Police Marked No Accident',
            note or 'Mock CCTV review found no visible accident.'
        )
        response = {'success': True, 'status': 'no_accident'}
    else:
        cur.execute("""
            UPDATE police_notifications
            SET status = 'confirmed',
                verification_note = %s,
                verified_at = CURRENT_TIMESTAMP
            WHERE id = %s
        """, (note or 'Police CCTV review confirmed accident.', notification_id))
        cur.execute("""
            UPDATE emergencies
            SET status = 'pending',
                verification_status = 'verified',
                verification_note = %s,
                verified_at = CURRENT_TIMESTAMP
            WHERE id = %s
        """, (note or 'Confirmed by mock Police CCTV dashboard.', emergency_id))
        add_timeline_event(
            cur,
            emergency_id,
            'police_confirmed',
            'Police Confirmed Accident',
            note or 'Mock CCTV review confirmed accident.'
        )
        ambulance_ids = send_dispatch_requests(cur, emergency_id)
        response = {
            'success': True,
            'status': 'confirmed',
            'dispatch_request_count': len(ambulance_ids),
            'ambulance_ids': ambulance_ids
        }

    conn.commit()
    cur.close()
    conn.close()
    return jsonify(response)


@app.route('/api/tracking/<int:emergency_id>', methods=['GET', 'POST'])
def emergency_tracking(emergency_id):
    conn = get_connection()
    cur = conn.cursor()
    ensure_workflow_schema(cur)

    if request.method == 'POST':
        data = request.json or {}
        status = data.get('status') or 'en_route'
        eta_minutes = data.get('eta_minutes')
        if eta_minutes is None:
            eta_minutes = calculate_demo_eta(data.get('distance_km'), data.get('severity'))

        update_tracking_status(
            cur,
            emergency_id,
            status,
            data.get('ambulance_id'),
            get_optional_float(data, 'lat', 'latitude'),
            get_optional_float(data, 'lng', 'longitude'),
            eta_minutes
        )
        conn.commit()

    cur.execute("""
        SELECT e.id, e.tracking_status, e.eta_minutes,
               al.lat, al.lng, al.updated_at,
               a.driver_name, a.vehicle_no
        FROM emergencies e
        LEFT JOIN ambulances a ON e.ambulance_id = a.id
        LEFT JOIN LATERAL (
            SELECT lat, lng, updated_at
            FROM ambulance_locations
            WHERE emergency_id = e.id
            ORDER BY updated_at DESC, id DESC
            LIMIT 1
        ) al ON TRUE
        WHERE e.id = %s
    """, (emergency_id,))

    row = cur.fetchone()
    conn.commit()
    cur.close()
    conn.close()

    if not row:
        return jsonify({'error': 'Emergency not found'}), 404

    return jsonify({
        'emergency_id': row[0],
        'tracking_status': row[1],
        'eta_minutes': row[2],
        'lat': row[3],
        'lng': row[4],
        'updated_at': row[5].isoformat() if row[5] else None,
        'driver_name': row[6],
        'vehicle_no': row[7]
    })

    
    # USER: Check status of their emergency
@app.route('/api/emergency/<int:emergency_id>', methods=['GET'])
def get_emergency_status(emergency_id):
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT e.id, e.status, e.severity, e.injury_type,
               a.driver_name, a.vehicle_no,
               h.name as hospital_name
        FROM emergencies e
        LEFT JOIN ambulances a ON e.ambulance_id = a.id
        LEFT JOIN hospitals h ON e.hospital_id = h.id
        WHERE e.id = %s
    """, (emergency_id,))

    row = cur.fetchone()
    cur.close()
    conn.close()

    if row:
        return jsonify({
            'id': row[0],
            'status': row[1],
            'severity': row[2],
            'injury_type': row[3],
            'driver_name': row[4],
            'vehicle_no': row[5],
            'hospital_name': row[6]
        })
    return jsonify({'error': 'Emergency not found'})

# DRIVER: Get all pending emergencies (alerts)
@app.route('/api/alerts', methods=['GET'])
def get_alerts():
    conn = get_connection()
    cur = conn.cursor()
    ensure_workflow_schema(cur)

    cur.execute("""
        SELECT id, reporter_name, location_name, severity, injury_type, status
        FROM emergencies
        WHERE (status = 'pending' OR status = 'ambulance_assigned')
          AND verification_status = 'verified'
        ORDER BY created_at DESC
        LIMIT 10
    """)

    rows = cur.fetchall()
    conn.commit()
    cur.close()
    conn.close()

    alerts = []
    for row in rows:
        alerts.append({
            'id': row[0],
            'reporter_name': row[1],
            'location_name': row[2],
            'severity': row[3],
            'injury_type': row[4],
            'status': row[5]
        })

    return jsonify(alerts)

# DRIVER: Accept an emergency
@app.route('/api/accept/<int:emergency_id>', methods=['POST'])
def accept_emergency(emergency_id):
    data = request.json
    ambulance_id = data.get('ambulance_id') if isinstance(data, dict) else None

    conn = get_connection()
    cur = conn.cursor()
    ensure_workflow_schema(cur)

    cur.execute("""
        SELECT location_name, severity, injury_type
        FROM emergencies
        WHERE id = %s
    """, (emergency_id,))
    emergency_row = cur.fetchone()

    location_name = emergency_row[0] if emergency_row else ''
    severity = emergency_row[1] if emergency_row else 'moderate'
    injury_type = emergency_row[2] if emergency_row else ''

    # Update emergency status
    # If ambulance_id not provided by the client, auto-select a free ambulance
    if not ambulance_id:
        cur.execute("SELECT id FROM ambulances WHERE status = 'free' LIMIT 1")
        amb_row = cur.fetchone()
        if amb_row:
            ambulance_id = amb_row[0]
        else:
            cur.close()
            conn.close()
            return jsonify({'success': False, 'message': 'No ambulance available'})

    cur.execute("""
        UPDATE emergencies
        SET status = 'ambulance_assigned', ambulance_id = %s
        WHERE id = %s
    """, (ambulance_id, emergency_id))

    # Mark ambulance busy
    cur.execute("UPDATE ambulances SET status = 'busy' WHERE id = %s", (ambulance_id,))
    mark_dispatch_accepted(cur, emergency_id, ambulance_id)

    hospitals = get_hospital_recommendations(cur, severity, injury_type)
    assigned_hospital = hospitals[0] if hospitals else None

    if assigned_hospital:
        cur.execute("""
            UPDATE emergencies
            SET hospital_id = %s
            WHERE id = %s
        """, (assigned_hospital['id'], emergency_id))
        notify_hospital(cur, emergency_id, assigned_hospital['id'])

    update_tracking_status(cur, emergency_id, 'assigned', ambulance_id, eta_minutes=calculate_demo_eta(severity=severity))

    conn.commit()
    cur.close()
    conn.close()

    return jsonify({
        'success': True,
        'location_name': location_name,
        'assigned_hospital': assigned_hospital,
        'hospital_recommendations': hospitals
    })


@app.route('/api/reach-hospital/<int:emergency_id>', methods=['POST'])
def reach_hospital(emergency_id):
    conn = get_connection()
    cur = conn.cursor()
    ensure_workflow_schema(cur)

    cur.execute("""
        SELECT ambulance_id
        FROM emergencies
        WHERE id = %s
    """, (emergency_id,))
    row = cur.fetchone()

    ambulance_id = row[0] if row else None

    cur.execute("""
        UPDATE emergencies
        SET status = 'completed'
        WHERE id = %s
    """, (emergency_id,))

    if ambulance_id:
        cur.execute("""
            UPDATE ambulances
            SET status = 'free'
            WHERE id = %s
        """, (ambulance_id,))

    update_tracking_status(cur, emergency_id, 'completed', ambulance_id)

    conn.commit()
    cur.close()
    conn.close()

    return jsonify({'success': True, 'message': 'Case marked as completed and ambulance released'})

# DRIVER: Get best hospital for a patient
@app.route('/api/suggest-hospital', methods=['POST'])
def suggest_hospital():
    data = request.json
    injury_type = data.get('injury_type', '')
    severity = data.get('severity', 'moderate')

    conn = get_connection()
    cur = conn.cursor()

    # NEW FEATURE ADDED
    hospitals = get_scored_hospital_recommendations(cur, severity, injury_type)
    cur.close()
    conn.close()

    return jsonify(hospitals)


# NEW FEATURE ADDED
@app.route('/api/ai/emergency-insights', methods=['POST'])
def emergency_ai_insights():
    data = request.json or {}
    injury_text = data.get('injury_type') or data.get('description') or ''
    combined_text = f"{data.get('severity', '')} {injury_text}"
    detected_severity = detect_severity(combined_text)
    risk_score = calculate_emergency_risk_score({
        **data,
        'severity': detected_severity,
        'injury_type': injury_text,
    })
    distance_km = get_float_value(data, 'distance_km')

    return jsonify({
        'detected_severity': detected_severity,
        'injury_category': detect_injury_category(injury_text),
        'risk_score': risk_score,
        'priority_label': get_priority_label(risk_score),
        'triage_confidence': get_triage_confidence(combined_text, detected_severity),
        'severity_reason': explain_severity_detection(combined_text, detected_severity),
        'eta_minutes': estimate_ambulance_eta(distance_km) if distance_km is not None else None,
        'summary': generate_emergency_summary(data),
        'driver_alert': generate_driver_alert_message(data),
        'route_decision': suggest_route_decision(data),
        'first_aid_checklist': generate_first_aid_checklist(injury_text)
    })


# NEW FEATURE ADDED
@app.route('/api/ai/hospital-insights', methods=['POST'])
def hospital_ai_insights():
    data = request.json or {}
    hospitals = data.get('hospitals', [])

    enhanced_hospitals = []
    for hospital in hospitals:
        hospital_data = dict(hospital)
        hospital_data['ai_score'] = calculate_hospital_score(hospital_data)
        hospital_data['match_explanation'] = explain_hospital_match(hospital_data)
        hospital_data['capacity_status'] = get_hospital_capacity_status(hospital_data)
        enhanced_hospitals.append(hospital_data)

    return jsonify(enhanced_hospitals)

# HOSPITAL: Get all hospitals
@app.route('/api/hospitals', methods=['GET'])
def get_hospitals():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT id, name, location, available_beds, icu_available, doctors_available, 
               has_trauma, has_neurosurgeon, has_burn_unit, has_blood_bank 
        FROM hospitals
        ORDER BY name ASC
    """)
    rows = cur.fetchall()
    cur.close()
    conn.close()

    hospitals = []
    for row in rows:
        hospitals.append({
            'id': row[0],
            'name': row[1],
            'location': row[2],
            'available_beds': row[3],
            'icu_available': row[4],
            'doctors_available': row[5],
            'has_trauma': row[6],
            'has_neurosurgeon': row[7],
            'has_burn_unit': row[8],
            'has_blood_bank': row[9]
        })

    return jsonify(hospitals)

# HOSPITAL: Update hospital capacity
@app.route('/api/hospital/update', methods=['POST'])
def update_hospital():
    data = request.json

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        UPDATE hospitals
        SET available_beds = %s,
            icu_available = %s,
            doctors_available = %s,
            has_trauma = %s,
            has_neurosurgeon = %s,
            has_burn_unit = %s,
            has_blood_bank = %s
        WHERE id = %s
    """, (
        data['available_beds'],
        data['icu_available'],
        data['doctors_available'],
        data['has_trauma'],
        data['has_neurosurgeon'],
        data['has_burn_unit'],
        data['has_blood_bank'],
        data['hospital_id']
    ))

    conn.commit()
    cur.close()
    conn.close()

    return jsonify({'success': True, 'message': 'Hospital updated successfully'})

# Run the app
if __name__ == '__main__':
    app.run(debug=True)




    
