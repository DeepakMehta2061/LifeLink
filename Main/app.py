from flask import Flask, render_template, request, jsonify
from database import get_connection
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

    # Find the nearest free ambulance
    cur.execute("""
        SELECT id, driver_name, vehicle_no
        FROM ambulances
        WHERE status = 'free'
        LIMIT 1
    """)

    ambulance = cur.fetchone()

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

    cur.execute("""
        SELECT id, reporter_name, location_name, severity, injury_type, status
        FROM emergencies
        WHERE status = 'pending' OR status = 'ambulance_assigned'
        ORDER BY created_at DESC
        LIMIT 10
    """)

    rows = cur.fetchall()
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

    hospitals = get_hospital_recommendations(cur, severity, injury_type)
    assigned_hospital = hospitals[0] if hospitals else None

    if assigned_hospital:
        cur.execute("""
            UPDATE emergencies
            SET hospital_id = %s
            WHERE id = %s
        """, (assigned_hospital['id'], emergency_id))

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

    hospitals = get_hospital_recommendations(cur, severity, injury_type)
    cur.close()
    conn.close()

    return jsonify(hospitals)

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




    