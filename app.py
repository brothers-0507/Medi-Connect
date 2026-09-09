import io
import base64
import math
from datetime import datetime, date, timedelta
import qrcode
from flask import Flask, render_template, redirect, url_for, request, flash, session, jsonify
from config import Config
from models import db, User, Prescription, PrescriptionItem, Broadcast, PharmacyOffer, MedicationSchedule, TrackerLog, InventoryItem

app = Flask(__name__)
app.config.from_object(Config)
db.init_app(app)

# Helper function to calculate great-circle distance (Haversine formula) in km
def calculate_distance(lat1, lon1, lat2, lon2):
    if None in (lat1, lon1, lat2, lon2):
        return None
    try:
        lat1, lon1, lat2, lon2 = map(math.radians, [float(lat1), float(lon1), float(lat2), float(lon2)])
        dlat = lat2 - lat1 
        dlon = lon2 - lon1 
        a = math.sin(dlat / 2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2)**2
        c = 2 * math.asin(math.sqrt(a)) 
        r = 6371.0 # Earth radius in kilometers
        return round(c * r, 2)
    except Exception:
        return None

# Helper function to generate QR Code as base64 string
def generate_qr_base64(data):
    qr = qrcode.QRCode(version=1, box_size=10, border=4)
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buffered = io.BytesIO()
    img.save(buffered, format="PNG")
    return base64.b64encode(buffered.getvalue()).decode('utf-8')

# Create database tables and dummy admin/users if database is empty
with app.app_context():
    db.create_all()
    # Pre-populate demo accounts for easy access and testing
    if not User.query.filter_by(username='doctor').first():
        doc = User(username='doctor', name='Dr. Rajesh Sharma', role='doctor', contact='+91 98450 12345', location='Bengaluru, Karnataka',
                   latitude=12.9716, longitude=77.5946, address='Fortis Hospital, Cunningham Road, Bengaluru, Karnataka 560052')
        doc.set_password('password')
        db.session.add(doc)
        
        pat = User(username='patient', name='Rahul Verma', role='patient', contact='+91 98765 43210', location='Bengaluru, Karnataka',
                   latitude=12.9784, longitude=77.6408, address='12th Main Road, HAL 2nd Stage, Indiranagar, Bengaluru, Karnataka 560038')
        pat.set_password('password')
        db.session.add(pat)
        
        ph = User(username='pharmacy', name='Apollo Pharmacy Indiranagar', role='pharmacy', contact='+91 99887 76655', location='Bengaluru, Karnataka',
                  latitude=12.9720, longitude=77.6380, address='100ft Road, Indiranagar, Bengaluru, Karnataka 560038')
        ph.set_password('password')
        db.session.add(ph)

        ph2 = User(username='st_mary_pharmacy', name='MedPlus Pharmacy Koramangala', role='pharmacy', contact='+91 99887 11223', location='Bengaluru, Karnataka',
                   latitude=12.9352, longitude=77.6245, address='80ft Road, 4th Block, Koramangala, Bengaluru, Karnataka 560034')
        ph2.set_password('password')
        db.session.add(ph2)
        
        db.session.commit()

        # Seed initial inventory with standard Indian pharmaceutical medicines and INR pricing
        today = date.today()
        db.session.add(InventoryItem(pharmacy_id=ph.id, medicine_name='Augmentin 625', stock_level=60, price=185.00, batch_number='AUG-401', expiry_date=today + timedelta(days=365)))
        db.session.add(InventoryItem(pharmacy_id=ph.id, medicine_name='Dolo 650', stock_level=150, price=32.50, batch_number='DOL-102', expiry_date=today + timedelta(days=400)))
        db.session.add(InventoryItem(pharmacy_id=ph.id, medicine_name='Pan-D', stock_level=45, price=145.00, batch_number='PAN-303', expiry_date=today + timedelta(days=300)))
        db.session.add(InventoryItem(pharmacy_id=ph.id, medicine_name='Azithral 500', stock_level=25, price=125.00, batch_number='AZI-501', expiry_date=today + timedelta(days=250)))
        db.session.add(InventoryItem(pharmacy_id=ph.id, medicine_name='Cetirizine 10mg', stock_level=90, price=38.00, batch_number='CET-201', expiry_date=today + timedelta(days=500)))
        db.session.add(InventoryItem(pharmacy_id=ph.id, medicine_name='Telma 40', stock_level=5, price=95.00, batch_number='TEL-105', expiry_date=today + timedelta(days=180)))
        
        db.session.add(InventoryItem(pharmacy_id=ph2.id, medicine_name='Augmentin 625', stock_level=30, price=178.00, batch_number='AUG-901', expiry_date=today + timedelta(days=280)))
        db.session.add(InventoryItem(pharmacy_id=ph2.id, medicine_name='Dolo 650', stock_level=120, price=30.00, batch_number='DOL-802', expiry_date=today + timedelta(days=450)))
        db.session.add(InventoryItem(pharmacy_id=ph2.id, medicine_name='Telma 40', stock_level=40, price=92.00, batch_number='TEL-701', expiry_date=today + timedelta(days=320)))
        db.session.add(InventoryItem(pharmacy_id=ph2.id, medicine_name='Montair-LC', stock_level=55, price=165.00, batch_number='MON-601', expiry_date=today + timedelta(days=365)))
        db.session.commit()

# Context processor to make current_user globally available in templates
@app.context_processor
def inject_user():
    user_id = session.get('user_id')
    if user_id:
        user = User.query.get(user_id)
        if user:
            return dict(current_user=user)
        else:
            session.clear()
    return dict(current_user=None)

# Decorator to restrict access to authenticated users
def login_required(f):
    import functools
    @functools.wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in first.', 'danger')
            return redirect(url_for('login'))
        user = User.query.get(session['user_id'])
        if not user:
            session.clear()
            flash('Please log in first.', 'danger')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# Decorator to restrict access by role
def role_required(role):
    def decorator(f):
        import functools
        @functools.wraps(f)
        def decorated_function(*args, **kwargs):
            user_id = session.get('user_id')
            if not user_id:
                flash(f'Please log in to access the {role.title()} Portal.', 'danger')
                return redirect(url_for('login', portal=role))
            user = User.query.get(user_id)
            if not user:
                session.clear()
                flash('Session expired. Please log in again.', 'danger')
                return redirect(url_for('login', portal=role))
            if user.role != role:
                flash(f'Access Denied: Your account is registered as a {user.role.title()}. You cannot access the {role.title()} Portal.', 'danger')
                return redirect(url_for(user.role + '_dashboard'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/portal/<string:role_name>')
def portal_gateway(role_name):
    valid_roles = {'doctor', 'patient', 'pharmacy'}
    role_name = role_name.lower().strip()
    if role_name not in valid_roles:
        flash('Invalid portal specified.', 'warning')
        return redirect(url_for('index'))
        
    user_id = session.get('user_id')
    if user_id:
        user = User.query.get(user_id)
        if user:
            if user.role == role_name:
                return redirect(url_for(user.role + '_dashboard'))
            else:
                flash(f'Access Denied: You are currently logged in as a {user.role.title()}. You cannot access the {role_name.title()} Portal.', 'danger')
                return redirect(url_for(user.role + '_dashboard'))
        else:
            session.clear()
            
    return redirect(url_for('login', portal=role_name))

@app.route('/login', methods=['GET', 'POST'])
def login():
    portal = request.args.get('portal') or request.args.get('role') or request.form.get('portal') or request.form.get('role')
    if portal:
        portal = portal.strip().lower()
        if portal not in {'doctor', 'patient', 'pharmacy'}:
            portal = None

    if 'user_id' in session:
        user = User.query.get(session['user_id'])
        if user:
            if portal and user.role != portal:
                flash(f'Access Denied: You are currently logged in as a {user.role.title()}. You cannot access the {portal.title()} Portal.', 'danger')
            return redirect(url_for(user.role + '_dashboard'))
        else:
            session.clear()
        
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password']
        
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            # Check portal role match if a specific portal was requested
            if portal and user.role != portal:
                flash(f'Access Denied: Your account is registered as a {user.role.title()}. Please access via the {user.role.title()} Portal.', 'danger')
                return redirect(url_for('login', portal=portal))
                
            session['user_id'] = user.id
            session['role'] = user.role
            flash(f'Welcome back, {user.name}!', 'success')
            return redirect(url_for(user.role + '_dashboard'))
        else:
            flash('Invalid username or password.', 'danger')
            
    return render_template('login.html', portal=portal)

@app.route('/register', methods=['POST'])
def register():
    portal = request.form.get('portal', '').strip().lower()
    username = request.form['username'].strip()
    password = request.form['password']
    name = request.form['name'].strip()
    role = request.form['role'].strip().lower()
    contact = request.form['contact'].strip()
    location = request.form.get('location', '').strip()
    
    # If registered from a specific portal, lock role to that portal
    if portal in {'doctor', 'patient', 'pharmacy'}:
        role = portal
    elif role not in {'doctor', 'patient', 'pharmacy'}:
        role = 'patient'
    
    if User.query.filter_by(username=username).first():
        flash('Username already exists.', 'danger')
        return redirect(url_for('login', action='register', portal=portal if portal else None))
        
    user = User(username=username, name=name, role=role, contact=contact, location=location)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    
    flash(f'Registration successful! Please log in to your {role.title()} portal.', 'success')
    return redirect(url_for('login', portal=role))

@app.route('/logout')
def logout():
    session.clear()
    flash('Logged out successfully.', 'info')
    return redirect(url_for('login'))

@app.route('/settings')
@login_required
def settings():
    return render_template('settings.html')

@app.route('/settings/update', methods=['POST'])
@login_required
def update_settings():
    user_id = session['user_id']
    user = User.query.get(user_id)
    
    name = request.form['name'].strip()
    username = request.form['username'].strip()
    contact = request.form['contact'].strip()
    location = request.form.get('location', '').strip()
    
    if not username:
        flash('Username cannot be empty.', 'danger')
        return redirect(url_for('settings'))
        
    if username != user.username:
        exists = User.query.filter_by(username=username).first()
        if exists:
            flash('Username is already taken by another account.', 'danger')
            return redirect(url_for('settings'))
            
    user.name = name
    user.username = username
    user.contact = contact
    user.location = location
    
    if user.role == 'doctor':
        if 'doctor_badges_json' in request.form and request.form['doctor_badges_json'].strip():
            try:
                import json
                badges_data = json.loads(request.form['doctor_badges_json'])
                if isinstance(badges_data, list):
                    user.set_doctor_badges(badges_data)
            except Exception:
                if 'bio' in request.form:
                    user.bio = request.form['bio'].strip()
        elif 'bio' in request.form:
            user.bio = request.form['bio'].strip()
    elif 'bio' in request.form:
        user.bio = request.form['bio'].strip()

    db.session.commit()
    
    flash('Profile details updated successfully!', 'success')
    return redirect(url_for('settings'))

@app.route('/api/doctor/bio', methods=['POST'])
@login_required
@role_required('doctor')
def update_doctor_bio():
    doctor_id = session['user_id']
    user = User.query.get(doctor_id)
    if request.is_json:
        data = request.get_json() or {}
        if 'badges' in data and isinstance(data['badges'], list):
            user.set_doctor_badges(data['badges'])
        elif 'bio' in data:
            raw = data['bio']
            if isinstance(raw, list):
                user.set_doctor_badges(raw)
            else:
                user.bio = str(raw).strip()
        db.session.commit()
        return jsonify({'success': True, 'badges': user.get_doctor_badges(), 'bio': user.bio, 'message': 'Doctor credentials updated successfully'})

    if 'doctor_badges_json' in request.form and request.form['doctor_badges_json'].strip():
        try:
            import json
            badges_data = json.loads(request.form['doctor_badges_json'])
            if isinstance(badges_data, list):
                user.set_doctor_badges(badges_data)
        except Exception:
            pass
    elif 'bio' in request.form:
        user.bio = request.form['bio'].strip()
        
    db.session.commit()
    flash('Doctor professional credentials updated successfully!', 'success')
    return redirect(url_for('doctor_dashboard'))

@app.route('/settings/password', methods=['POST'])
@login_required
def update_password():
    user_id = session['user_id']
    user = User.query.get(user_id)
    
    current_password = request.form['current_password']
    new_password = request.form['new_password']
    confirm_password = request.form['confirm_password']
    
    if not user.check_password(current_password):
        flash('Current password is incorrect.', 'danger')
        return redirect(url_for('settings'))
        
    if new_password != confirm_password:
        flash('New passwords do not match.', 'danger')
        return redirect(url_for('settings'))
        
    user.set_password(new_password)
    db.session.commit()
    
    flash('Password updated successfully!', 'success')
    return redirect(url_for('settings'))

# ----------------- DOCTOR PORTAL -----------------

@app.route('/dashboard/doctor')
@login_required
@role_required('doctor')
def doctor_dashboard():
    doctor_id = session['user_id']
    prescriptions = Prescription.query.filter_by(doctor_id=doctor_id).order_by(Prescription.created_at.desc()).all()
    patients = User.query.filter_by(role='patient').order_by(User.name.asc()).all()
    
    # KPI Stats
    total_rx = len(prescriptions)
    active_rx = len([p for p in prescriptions if not p.is_claimed])
    dispensed_rx = len([p for p in prescriptions if p.is_claimed])
    total_patients = len(patients)
    
    return render_template(
        'doctor.html', 
        prescriptions=prescriptions, 
        patients=patients,
        total_rx=total_rx,
        active_rx=active_rx,
        dispensed_rx=dispensed_rx,
        total_patients=total_patients
    )

@app.route('/api/patient/lookup')
@login_required
@role_required('doctor')
def lookup_patient():
    username = request.args.get('username', '').strip()
    if not username:
        return jsonify({'found': False})
    pat = User.query.filter_by(username=username, role='patient').first()
    if not pat:
        return jsonify({'found': False})
    
    last_rx = Prescription.query.filter_by(patient_id=pat.id).order_by(Prescription.created_at.desc()).first()
    age = last_rx.patient_age if last_rx and last_rx.patient_age else ''
    prev_rx_count = Prescription.query.filter_by(patient_id=pat.id).count()
    
    return jsonify({
        'found': True,
        'name': pat.name,
        'contact': pat.contact or '',
        'age': age,
        'location': pat.location or 'Bengaluru, Karnataka',
        'prev_rx_count': prev_rx_count,
        'last_rx_date': last_rx.created_at.strftime('%d %b %Y') if last_rx else 'First Consultation'
    })

@app.route('/prescription/create', methods=['POST'])
@login_required
@role_required('doctor')
def create_prescription():
    doctor_id = session['user_id']
    patient_username = request.form.get('patient_username')
    patient_name = request.form['patient_name']
    patient_age = request.form.get('patient_age')
    patient_contact = request.form.get('patient_contact')
    instructions = request.form.get('instructions')
    
    # Find registered patient by username (required)
    pat_user = None
    if patient_username:
        pat_user = User.query.filter_by(username=patient_username.strip(), role='patient').first()
    
    if not pat_user:
        flash('Error: Patient username not found. Please verify the registered username with the patient.', 'danger')
        return redirect(url_for('doctor_dashboard'))
        
    patient_id = pat_user.id
    patient_name = pat_user.name
    patient_contact = pat_user.contact
            
    prescription = Prescription(
        doctor_id=doctor_id,
        patient_id=patient_id,
        patient_name=patient_name,
        patient_age=int(patient_age) if patient_age else None,
        patient_contact=patient_contact,
        instructions=instructions,
        is_claimed=False
    )
    
    db.session.add(prescription)
    db.session.flush() # get ID
    
    # Retrieve medicine details
    med_names = request.form.getlist('med_name[]')
    dosages = request.form.getlist('med_dosage[]')
    frequencies = request.form.getlist('med_frequency[]')
    durations = request.form.getlist('med_duration[]')
    med_instructions = request.form.getlist('med_instructions[]')
    
    for i in range(len(med_names)):
        if med_names[i].strip():
            item = PrescriptionItem(
                prescription_id=prescription.id,
                medicine_name=med_names[i],
                dosage=dosages[i],
                frequency=frequencies[i],
                duration=durations[i],
                instructions=med_instructions[i]
            )
            db.session.add(item)
            
    db.session.commit()
    flash('Digital prescription created successfully!', 'success')
    return redirect(url_for('doctor_dashboard'))

@app.route('/doctor/prescription/new', methods=['GET', 'POST'])
@app.route('/prescription/new', methods=['GET', 'POST'])
@login_required
@role_required('doctor')
def new_prescription():
    if request.method == 'POST':
        return create_prescription()
    patients = User.query.filter_by(role='patient').order_by(User.name.asc()).all()
    return render_template('prescription_new.html', patients=patients)

@app.route('/prescription/<int:rx_id>/delete', methods=['POST'])
@login_required
@role_required('doctor')
def delete_prescription(rx_id):
    doctor_id = session['user_id']
    rx = Prescription.query.get_or_404(rx_id)
    if rx.doctor_id != doctor_id:
        if request.is_json:
            return jsonify({'success': False, 'message': 'Unauthorized to delete this prescription'}), 403
        flash('Unauthorized: You can only delete prescriptions you created.', 'danger')
        return redirect(url_for('doctor_dashboard'))
    
    patient_name = rx.patient_name
    db.session.delete(rx)
    db.session.commit()
    
    if request.is_json:
        return jsonify({'success': True, 'message': f'Prescription for {patient_name} deleted successfully.'})
    flash(f'Prescription for {patient_name} deleted successfully.', 'success')
    return redirect(url_for('doctor_dashboard'))

# ----------------- PATIENT PORTAL -----------------

@app.route('/dashboard/patient')
@login_required
@role_required('patient')
def patient_dashboard():
    patient_id = session['user_id']
    
    # Get claimed prescriptions
    prescriptions = Prescription.query.filter_by(
        patient_id=patient_id, 
        is_claimed=True
    ).order_by(Prescription.created_at.desc()).all()
    
    # Get pending (unclaimed) prescriptions for pop-up alert
    pending_prescriptions = Prescription.query.filter_by(
        patient_id=patient_id,
        is_claimed=False
    ).order_by(Prescription.created_at.desc()).all()

    # Medi-Tracker: Active medication schedules
    schedules = MedicationSchedule.query.filter_by(patient_id=patient_id).all()
    
    # Refill Alerts: items running low in stock
    refill_alerts = [s for s in schedules if s.current_stock <= s.refill_alert_threshold]
    
    # Active Broadcasts and corresponding pharmacy offers
    broadcasts = Broadcast.query.filter_by(patient_id=patient_id).order_by(Broadcast.created_at.desc()).all()
    
    # Tracker Checklist for today
    today_date = date.today()
    today_logs = TrackerLog.query.join(MedicationSchedule).filter(
        MedicationSchedule.patient_id == patient_id,
        db.func.date(TrackerLog.taken_at) == today_date
    ).all()
    
    # Map tracker schedules to logs for UI checkboxes
    checklist = []
    for sched in schedules:
        if sched.start_date <= today_date <= sched.end_date:
            # Check how many times today we logged this schedule
            times = [t.strip() for t in sched.time_of_day.split(',') if t.strip()]
            sched_logs = [l for l in today_logs if l.schedule_id == sched.id]
            
            checklist.append({
                'schedule': sched,
                'times': times,
                'logged_count': len(sched_logs),
                'total_needed': len(times)
            })

    # Calculate KPI Stats & upcoming dose
    total_doses_today = sum(c['total_needed'] for c in checklist)
    doses_taken_today = sum(c['logged_count'] for c in checklist)
    adherence_pct = round((doses_taken_today / total_doses_today * 100) if total_doses_today > 0 else 100)
    
    next_dose_info = "All doses completed today" if total_doses_today > 0 and doses_taken_today >= total_doses_today else None
    if not next_dose_info and checklist:
        for c in checklist:
            if c['logged_count'] < c['total_needed']:
                next_idx = c['logged_count']
                time_str = c['times'][next_idx] if next_idx < len(c['times']) else "Soon"
                next_dose_info = f"{c['schedule'].medicine_name} at {time_str}"
                break
    if not next_dose_info:
        next_dose_info = "No pending doses"

    return render_template(
        'patient.html', 
        prescriptions=prescriptions,
        pending_prescriptions=pending_prescriptions,
        schedules=schedules,
        refill_alerts=refill_alerts,
        broadcasts=broadcasts,
        checklist=checklist,
        total_doses_today=total_doses_today,
        doses_taken_today=doses_taken_today,
        adherence_pct=adherence_pct,
        next_dose_info=next_dose_info,
        total_prescriptions=len(prescriptions),
        active_schedules_count=len(schedules),
        low_stock_count=len(refill_alerts),
        broadcasts_count=len(broadcasts)
    )

@app.route('/prescription/claim', methods=['POST'])
@login_required
@role_required('patient')
def claim_prescription():
    patient_id = session['user_id']
    rx_code = request.form.get('prescription_code', '').strip()
    
    rx = Prescription.query.filter_by(uuid=rx_code).first()
    if not rx:
        flash('Prescription not found. Please verify the code/link.', 'danger')
        return redirect(url_for('patient_dashboard'))
        
    if rx.patient_id and rx.patient_id != patient_id:
        flash('This prescription is already linked to another patient profile.', 'danger')
    else:
        rx.patient_id = patient_id
        rx.is_claimed = True
        db.session.commit()
        flash('Prescription successfully claimed and linked to your profile!', 'success')
        
    return redirect(url_for('patient_dashboard'))

@app.route('/prescription/accept/<int:rx_id>', methods=['POST'])
@login_required
@role_required('patient')
def accept_prescription(rx_id):
    patient_id = session['user_id']
    rx = Prescription.query.filter_by(id=rx_id, patient_id=patient_id).first()
    if not rx:
        flash('Prescription not found or unauthorized.', 'danger')
        return redirect(url_for('patient_dashboard'))
        
    # Mark as claimed/accepted
    rx.is_claimed = True
    
    # Automatically import medications to tracker
    duration_days = 7
    for item in rx.items:
        dur_str = item.duration.lower()
        if 'day' in dur_str:
            try:
                duration_days = int(''.join(filter(str.isdigit, dur_str)))
            except ValueError:
                pass
        elif 'week' in dur_str:
            try:
                duration_days = int(''.join(filter(str.isdigit, dur_str))) * 7
            except ValueError:
                pass
        elif 'month' in dur_str:
            try:
                duration_days = int(''.join(filter(str.isdigit, dur_str))) * 30
            except ValueError:
                pass
                
        freq_str = item.frequency.lower()
        times = "09:00"
        doses_per_day = 1
        if 'twice' in freq_str or '2 times' in freq_str or 'bid' in freq_str:
            times = "09:00, 21:00"
            doses_per_day = 2
        elif 'three' in freq_str or '3 times' in freq_str or 'tid' in freq_str:
            times = "08:00, 14:00, 20:00"
            doses_per_day = 3
        elif 'four' in freq_str or '4 times' in freq_str or 'qid' in freq_str:
            times = "08:00, 12:00, 16:00, 20:00"
            doses_per_day = 4
            
        total_doses = doses_per_day * duration_days
        
        exists = MedicationSchedule.query.filter_by(
            patient_id=patient_id, 
            medicine_name=item.medicine_name
        ).first()
        
        if not exists:
            sched = MedicationSchedule(
                patient_id=patient_id,
                medicine_name=item.medicine_name,
                dosage=item.dosage,
                frequency=item.frequency,
                time_of_day=times,
                start_date=date.today(),
                end_date=date.today() + timedelta(days=duration_days),
                current_stock=total_doses,
                refill_alert_threshold=doses_per_day * 3
            )
            db.session.add(sched)
            
    db.session.commit()
    flash('Prescription accepted and imported to your Medi-Tracker!', 'success')
    return redirect(url_for('patient_dashboard'))

@app.route('/tracker/import/<int:rx_id>', methods=['POST'])
@login_required
@role_required('patient')
def import_prescription_to_tracker(rx_id):
    patient_id = session['user_id']
    rx = Prescription.query.filter_by(id=rx_id, patient_id=patient_id).first()
    if not rx:
        flash('Prescription not found or unauthorized.', 'danger')
        return redirect(url_for('patient_dashboard'))
        
    duration_days = 7  # default mapping
    for item in rx.items:
        # Simple duration parser
        dur_str = item.duration.lower()
        if 'day' in dur_str:
            try:
                duration_days = int(''.join(filter(str.isdigit, dur_str)))
            except ValueError:
                pass
        elif 'week' in dur_str:
            try:
                duration_days = int(''.join(filter(str.isdigit, dur_str))) * 7
            except ValueError:
                pass
        elif 'month' in dur_str:
            try:
                duration_days = int(''.join(filter(str.isdigit, dur_str))) * 30
            except ValueError:
                pass
                
        # Simple frequency to time mapper
        freq_str = item.frequency.lower()
        times = "09:00"
        doses_per_day = 1
        if 'twice' in freq_str or '2 times' in freq_str or 'bid' in freq_str:
            times = "09:00, 21:00"
            doses_per_day = 2
        elif 'three' in freq_str or '3 times' in freq_str or 'tid' in freq_str:
            times = "08:00, 14:00, 20:00"
            doses_per_day = 3
        elif 'four' in freq_str or '4 times' in freq_str or 'qid' in freq_str:
            times = "08:00, 12:00, 16:00, 20:00"
            doses_per_day = 4
            
        total_doses = doses_per_day * duration_days
        
        # Check if already added
        exists = MedicationSchedule.query.filter_by(
            patient_id=patient_id, 
            medicine_name=item.medicine_name
        ).first()
        
        if not exists:
            sched = MedicationSchedule(
                patient_id=patient_id,
                medicine_name=item.medicine_name,
                dosage=item.dosage,
                frequency=item.frequency,
                time_of_day=times,
                start_date=date.today(),
                end_date=date.today() + timedelta(days=duration_days),
                current_stock=total_doses,
                refill_alert_threshold=doses_per_day * 3 # alert 3 days before empty
            )
            db.session.add(sched)
            
    db.session.commit()
    flash('Prescription medications imported to Medi-Tracker successfully!', 'success')
    return redirect(url_for('patient_dashboard'))

@app.route('/tracker/add', methods=['POST'])
@login_required
@role_required('patient')
def add_custom_tracker():
    patient_id = session['user_id']
    med_name = request.form['medicine_name']
    dosage = request.form['dosage']
    times = request.form['time_of_day']  # raw list of times, e.g. "08:00, 20:00"
    current_stock = int(request.form.get('current_stock', 10))
    
    # Sensible defaults for simplified form
    frequency = "Daily"
    end_date = date.today() + timedelta(days=30)
    refill_alert = 5
    
    sched = MedicationSchedule(
        patient_id=patient_id,
        medicine_name=med_name,
        dosage=dosage,
        frequency=frequency,
        time_of_day=times,
        start_date=date.today(),
        end_date=end_date,
        current_stock=current_stock,
        refill_alert_threshold=refill_alert
    )
    db.session.add(sched)
    db.session.commit()
    
    flash('Medication added to Medi-Tracker!', 'success')
    return redirect(url_for('patient_dashboard'))

@app.route('/tracker/log/<int:schedule_id>', methods=['POST'])
@login_required
@role_required('patient')
def log_dose(schedule_id):
    patient_id = session['user_id']
    sched = MedicationSchedule.query.filter_by(id=schedule_id, patient_id=patient_id).first()
    if not sched:
        return jsonify({'success': False, 'message': 'Schedule not found'}), 404
        
    action = request.form.get('action', 'taken') # 'taken' or 'skipped'
    
    # Deduct stock if taken and stock > 0
    if action == 'taken':
        if sched.current_stock > 0:
            sched.current_stock -= 1
            
    log = TrackerLog(schedule_id=sched.id, status=action)
    db.session.add(log)
    db.session.commit()
    
    # Determine alert status
    running_low = sched.current_stock <= sched.refill_alert_threshold
    
    return jsonify({
        'success': True,
        'current_stock': sched.current_stock,
        'running_low': running_low,
        'alert_message': f"Stock warning! Only {sched.current_stock} doses of {sched.medicine_name} left." if running_low else ""
    })

@app.route('/tracker/refill/<int:schedule_id>', methods=['POST'])
@login_required
@role_required('patient')
def refill_stock(schedule_id):
    patient_id = session['user_id']
    sched = MedicationSchedule.query.filter_by(id=schedule_id, patient_id=patient_id).first()
    if not sched:
        flash('Schedule not found.', 'danger')
        return redirect(url_for('patient_dashboard'))
        
    amount = int(request.form.get('amount', 0))
    if amount > 0:
        sched.current_stock += amount
        db.session.commit()
        flash(f'Stock of {sched.medicine_name} replenished by {amount} doses!', 'success')
    else:
        flash('Invalid refill amount.', 'warning')
        
    return redirect(url_for('patient_dashboard'))

@app.route('/broadcast/create', methods=['POST'])
@login_required
@role_required('patient')
def create_broadcast():
    patient_id = session['user_id']
    rx_id = request.form['prescription_id']
    target_pharmacy_id = request.form.get('target_pharmacy_id')
    patient_lat = request.form.get('latitude')
    patient_lng = request.form.get('longitude')
    
    # Verify owner
    rx = Prescription.query.filter_by(id=rx_id, patient_id=patient_id).first()
    if not rx:
        flash('Prescription not found or unauthorized.', 'danger')
        return redirect(url_for('patient_dashboard'))
        
    # Check if active broadcast already exists
    existing = Broadcast.query.filter_by(prescription_id=rx_id, patient_id=patient_id, status='active').first()
    if existing:
        flash('This prescription is already actively broadcasted.', 'info')
        return redirect(url_for('patient_dashboard'))
        
    bc = Broadcast(
        prescription_id=rx_id, 
        patient_id=patient_id,
        target_pharmacy_id=int(target_pharmacy_id) if target_pharmacy_id else None,
        patient_lat=float(patient_lat) if patient_lat else None,
        patient_lng=float(patient_lng) if patient_lng else None
    )
    db.session.add(bc)
    db.session.commit()
    
    flash('Prescription broadcasted to verified local pharmacies! Awaiting estimates.', 'success')
    return redirect(url_for('patient_dashboard'))

@app.route('/api/prescription/<int:rx_id>/find-pharmacies', methods=['POST'])
@login_required
@role_required('patient')
def find_nearest_pharmacies(rx_id):
    patient_id = session['user_id']
    patient = User.query.get(patient_id)
    rx = Prescription.query.filter_by(id=rx_id, patient_id=patient_id).first()
    if not rx:
        return jsonify({'success': False, 'message': 'Prescription not found or unauthorized'}), 404
        
    data = request.get_json(silent=True) or {}
    patient_lat = data.get('latitude')
    patient_lng = data.get('longitude')
    
    if patient_lat is None or patient_lng is None:
        patient_lat = patient.latitude or 12.9784
        patient_lng = patient.longitude or 77.6408
    else:
        patient_lat = float(patient_lat)
        patient_lng = float(patient_lng)
        
    pharmacies = User.query.filter_by(role='pharmacy').all()
    results = []
    today = date.today()
    
    for ph in pharmacies:
        dist = calculate_distance(patient_lat, patient_lng, ph.latitude, ph.longitude)
        
        matching_items = []
        missing_items = []
        total_estimated_price = 0.0
        
        for rx_item in rx.items:
            med_name_clean = rx_item.medicine_name.strip().lower()
            
            inv_matches = InventoryItem.query.filter(
                InventoryItem.pharmacy_id == ph.id,
                db.func.lower(InventoryItem.medicine_name) == med_name_clean,
                InventoryItem.stock_level > 0,
                InventoryItem.expiry_date >= today
            ).all()
            
            if inv_matches:
                best_match = inv_matches[0]
                matching_items.append({
                    'medicine_name': rx_item.medicine_name,
                    'dosage': rx_item.dosage,
                    'stock_level': best_match.stock_level,
                    'price': best_match.price
                })
                total_estimated_price += best_match.price
            else:
                missing_items.append(rx_item.medicine_name)
                
        total_items_count = len(rx.items)
        if len(matching_items) == total_items_count and total_items_count > 0:
            stock_status = 'available'
            status_text = 'All Medicines in Stock'
            status_rank = 1
        elif len(matching_items) > 0:
            stock_status = 'partial'
            status_text = f'{len(matching_items)} of {total_items_count} in Stock'
            status_rank = 2
        else:
            stock_status = 'unavailable'
            status_text = 'Currently Out of Stock'
            status_rank = 3
            
        results.append({
            'pharmacy_id': ph.id,
            'name': ph.name,
            'contact': ph.contact or 'Available upon order',
            'address': ph.address or ph.location or 'Local Pharmacy',
            'location': ph.location or 'Local',
            'distance_km': dist if dist is not None else 999.0,
            'distance_text': f"{dist} km away" if dist is not None else "Nearby",
            'stock_status': stock_status,
            'status_text': status_text,
            'status_rank': status_rank,
            'matching_items': matching_items,
            'missing_items': missing_items,
            'estimated_price': round(total_estimated_price, 2)
        })
        
    results.sort(key=lambda x: (x['status_rank'], x['distance_km']))
    
    return jsonify({
        'success': True,
        'prescription_id': rx.id,
        'prescription_uuid': rx.uuid,
        'patient_coords': {'latitude': patient_lat, 'longitude': patient_lng},
        'pharmacies': results
    })

@app.route('/api/broadcast/target-nearest', methods=['POST'])
@login_required
@role_required('patient')
def broadcast_target_nearest():
    patient_id = session['user_id']
    data = request.get_json(silent=True) or request.form
    rx_id = data.get('prescription_id')
    target_pharmacy_id = data.get('pharmacy_id')
    patient_lat = data.get('latitude')
    patient_lng = data.get('longitude')
    
    rx = Prescription.query.filter_by(id=rx_id, patient_id=patient_id).first()
    if not rx:
        return jsonify({'success': False, 'message': 'Prescription not found'}), 404
        
    target_id_val = int(target_pharmacy_id) if target_pharmacy_id else None
    
    existing = Broadcast.query.filter_by(prescription_id=rx_id, patient_id=patient_id, status='active').first()
    if existing:
        if target_id_val and existing.target_pharmacy_id != target_id_val:
            existing.target_pharmacy_id = target_id_val
            db.session.commit()
            return jsonify({'success': True, 'message': 'Broadcast target updated to selected pharmacy!'})
        return jsonify({'success': True, 'message': 'This prescription is already actively broadcasted.'})
        
    bc = Broadcast(
        prescription_id=rx_id,
        patient_id=patient_id,
        target_pharmacy_id=target_id_val,
        patient_lat=float(patient_lat) if patient_lat else None,
        patient_lng=float(patient_lng) if patient_lng else None,
        status='active'
    )
    db.session.add(bc)
    db.session.commit()
    
    msg = "Broadcast sent to selected in-stock pharmacy!" if target_id_val else "Broadcast sent to nearest in-stock pharmacies!"
    return jsonify({'success': True, 'message': msg, 'broadcast_id': bc.id})

# ----------------- PHARMACY PORTAL -----------------

@app.route('/dashboard/pharmacy')
@login_required
@role_required('pharmacy')
def pharmacy_dashboard():
    pharmacy_id = session['user_id']
    
    # Inventory
    inventory = InventoryItem.query.filter_by(pharmacy_id=pharmacy_id).order_by(InventoryItem.medicine_name).all()
    
    # Active broadcasts from patients
    pharmacy_user = User.query.get(pharmacy_id)
    pharmacy_loc = (pharmacy_user.location or "").strip().lower()
    
    all_broadcasts = Broadcast.query.filter_by(status='active').order_by(Broadcast.created_at.desc()).all()
    
    # Filter by matching location or target pharmacy
    broadcasts = []
    for bc in all_broadcasts:
        if bc.target_pharmacy_id and bc.target_pharmacy_id != pharmacy_id:
            continue
        patient_user = bc.patient
        patient_loc = (patient_user.location or "").strip().lower() if patient_user else ""
        if not pharmacy_loc or not patient_loc or pharmacy_loc == patient_loc:
            broadcasts.append(bc)
    
    # Map broadcasts to whether this pharmacy has already responded
    active_broadcasts_info = []
    for bc in broadcasts:
        already_offered = PharmacyOffer.query.filter_by(broadcast_id=bc.id, pharmacy_id=pharmacy_id).first()
        
        # Check stock overlap
        missing_meds = []
        matching_meds = []
        total_matched_cost = 0.0
        for item in bc.prescription.items:
            # Search matches in inventory
            inv_match = InventoryItem.query.filter_by(
                pharmacy_id=pharmacy_id, 
                medicine_name=item.medicine_name
            ).first()
            if inv_match and inv_match.stock_level > 0:
                matching_meds.append(item)
                total_matched_cost += inv_match.price
            else:
                missing_meds.append(item.medicine_name)
                
        status_calc = 'available' if not missing_meds else ('partial' if matching_meds else 'unavailable')
        
        active_broadcasts_info.append({
            'broadcast': bc,
            'offered': already_offered,
            'status_calc': status_calc,
            'estimated_price': total_matched_cost,
            'missing_meds': missing_meds
        })
        
    # KPI Stats
    low_stock_count = len([i for i in inventory if 0 < i.stock_level <= 10])
    out_of_stock_count = len([i for i in inventory if i.stock_level == 0])
    expiring_soon_count = len([i for i in inventory if i.is_expiring_soon])
    total_broadcasts = len(active_broadcasts_info)
    total_skus = len(inventory)
        
    return render_template(
        'pharmacy.html', 
        inventory=inventory, 
        broadcasts_info=active_broadcasts_info,
        low_stock_count=low_stock_count,
        out_of_stock_count=out_of_stock_count,
        expiring_soon_count=expiring_soon_count,
        total_broadcasts=total_broadcasts,
        total_skus=total_skus
    )

@app.route('/inventory/add', methods=['POST'])
@login_required
@role_required('pharmacy')
def add_inventory():
    pharmacy_id = session['user_id']
    medicine_name = request.form['medicine_name']
    stock_level = int(request.form['stock_level'])
    price = float(request.form['price'])
    batch = request.form['batch_number']
    expiry_str = request.form['expiry_date']
    
    expiry_date = datetime.strptime(expiry_str, '%Y-%m-%d').date()
    
    item = InventoryItem(
        pharmacy_id=pharmacy_id,
        medicine_name=medicine_name,
        stock_level=stock_level,
        price=price,
        batch_number=batch,
        expiry_date=expiry_date
    )
    
    db.session.add(item)
    db.session.commit()
    flash(f'{medicine_name} added to inventory!', 'success')
    return redirect(url_for('pharmacy_dashboard'))

@app.route('/inventory/update/<int:item_id>', methods=['POST'])
@login_required
@role_required('pharmacy')
def update_inventory(item_id):
    pharmacy_id = session['user_id']
    item = InventoryItem.query.filter_by(id=item_id, pharmacy_id=pharmacy_id).first()
    if not item:
        flash('Inventory item not found.', 'danger')
        return redirect(url_for('pharmacy_dashboard'))
        
    item.stock_level = int(request.form['stock_level'])
    item.price = float(request.form['price'])
    item.batch_number = request.form['batch_number']
    
    expiry_str = request.form.get('expiry_date')
    if expiry_str:
        item.expiry_date = datetime.strptime(expiry_str, '%Y-%m-%d').date()
        
    db.session.commit()
    flash(f'{item.medicine_name} updated successfully!', 'success')
    return redirect(url_for('pharmacy_dashboard'))

@app.route('/inventory/delete/<int:item_id>', methods=['POST'])
@login_required
@role_required('pharmacy')
def delete_inventory(item_id):
    pharmacy_id = session['user_id']
    item = InventoryItem.query.filter_by(id=item_id, pharmacy_id=pharmacy_id).first()
    if not item:
        return jsonify({'success': False, 'message': 'Item not found'}), 404
        
    db.session.delete(item)
    db.session.commit()
    return jsonify({'success': True})

@app.route('/broadcast/offer', methods=['POST'])
@login_required
@role_required('pharmacy')
def submit_offer():
    pharmacy_id = session['user_id']
    broadcast_id = request.form['broadcast_id']
    price = float(request.form['price'])
    status = request.form['availability_status']
    notes = request.form.get('notes', '')
    
    # Check if offer exists
    existing = PharmacyOffer.query.filter_by(broadcast_id=broadcast_id, pharmacy_id=pharmacy_id).first()
    if existing:
        existing.estimated_price = price
        existing.availability_status = status
        existing.notes = notes
        existing.created_at = datetime.utcnow()
    else:
        offer = PharmacyOffer(
            broadcast_id=broadcast_id,
            pharmacy_id=pharmacy_id,
            estimated_price=price,
            availability_status=status,
            notes=notes
        )
        db.session.add(offer)
        
    db.session.commit()
    flash('Price estimate and availability submitted successfully!', 'success')
    return redirect(url_for('pharmacy_dashboard'))

@app.route('/checkout', methods=['POST'])
@login_required
@role_required('pharmacy')
def checkout_sale():
    pharmacy_id = session['user_id']
    med_name = request.form['medicine_name']
    qty = int(request.form['quantity'])
    
    # Find active batches
    items = InventoryItem.query.filter_by(
        pharmacy_id=pharmacy_id, 
        medicine_name=med_name
    ).order_by(InventoryItem.expiry_date).all()
    
    if not items:
        return jsonify({'success': False, 'message': 'Medicine not found in inventory.'})
        
    total_stock = sum(i.stock_level for i in items)
    if total_stock < qty:
        return jsonify({'success': False, 'message': f'Insufficient stock. Only {total_stock} available.'})
        
    # Deduct stock across batches (FIFO/Expiry order)
    remaining_to_deduct = qty
    deducted_details = []
    expiring_warnings = []
    
    for item in items:
        if remaining_to_deduct <= 0:
            break
            
        if item.stock_level > 0:
            deduct_qty = min(item.stock_level, remaining_to_deduct)
            item.stock_level -= deduct_qty
            remaining_to_deduct -= deduct_qty
            deducted_details.append(f"{deduct_qty} from batch {item.batch_number}")
            
            # Check for expiring warning
            if item.is_expiring_soon:
                expiring_warnings.append(f"Batch {item.batch_number} (expiring {item.expiry_date})")
                
    db.session.commit()
    
    warn_msg = ""
    if expiring_warnings:
        warn_msg = f" Note: Sold stock contains batches near expiration: {', '.join(expiring_warnings)}"
        
    return jsonify({
        'success': True,
        'message': f"Checkout completed successfully: Deducted {', '.join(deducted_details)}.{warn_msg}"
    })

# ----------------- PUBLIC VIEWING & SECURE ACCESS -----------------

@app.route('/prescription/view/<string:rx_uuid>')
def view_prescription(rx_uuid):
    prescription = Prescription.query.filter_by(uuid=rx_uuid).first_or_404()
    
    # Secure link for this prescription
    secure_url = request.url_root.rstrip('/') + url_for('view_prescription', rx_uuid=rx_uuid)
    
    # Generate Base64 QR Code string
    qr_base64 = generate_qr_base64(secure_url)
    
    return render_template('view_prescription.html', prescription=prescription, qr_base64=qr_base64, secure_url=secure_url)

@app.route('/prescription/api/<string:rx_uuid>')
@login_required
def prescription_api(rx_uuid):
    rx = Prescription.query.filter_by(uuid=rx_uuid).first()
    if not rx:
        return jsonify({'success': False, 'message': 'Prescription not found'}), 404
        
    items = [{'medicine_name': item.medicine_name, 'dosage': item.dosage} for item in rx.items]
    return jsonify({
        'success': True,
        'patient_name': rx.patient_name,
        'items': items
    })

import click

@app.cli.command('list-users')
def list_users():
    """Lists all registered users in the database."""
    users = User.query.all()
    if not users:
        print("No users found in the database.")
        return
    print("\n--- Registered Users ---")
    for u in users:
        print(f"ID: {u.id} | Username: {u.username} | Name: {u.name} | Role: {u.role} | Location: {u.location or 'N/A'}")
    print("------------------------\n")

@app.cli.command('delete-user')
@click.argument('username')
def delete_user(username):
    """Deletes a user by username."""
    user = User.query.filter_by(username=username).first()
    if not user:
        print(f"User '{username}' not found.")
        return
    db.session.delete(user)
    db.session.commit()
    print(f"User '{username}' successfully deleted.")

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
