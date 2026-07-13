import io
import base64
from datetime import datetime, date, timedelta
import qrcode
from flask import Flask, render_template, redirect, url_for, request, flash, session, jsonify
from config import Config
from models import db, User, Prescription, PrescriptionItem, Broadcast, PharmacyOffer, MedicationSchedule, TrackerLog, InventoryItem

app = Flask(__name__)
app.config.from_object(Config)
db.init_app(app)

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
    # Check if we need to pre-populate roles or dummy users
    if not User.query.filter_by(username='doctor').first():
        doc = User(username='doctor', name='Dr. Sarah Jenkins', role='doctor', contact='doctor@mediconnect.com')
        doc.set_password('password')
        db.session.add(doc)
        
        pat = User(username='patient', name='John Doe', role='patient', contact='555-0199')
        pat.set_password('password')
        db.session.add(pat)
        
        ph = User(username='pharmacy', name='City Central Pharmacy', role='pharmacy', contact='info@citycentral.com')
        ph.set_password('password')
        db.session.add(ph)
        
        db.session.commit()

# Context processor to make current_user globally available in templates
@app.context_processor
def inject_user():
    user_id = session.get('user_id')
    if user_id:
        user = User.query.get(user_id)
        return dict(current_user=user)
    return dict(current_user=None)

# Decorator to restrict access to authenticated users
def login_required(f):
    import functools
    @functools.wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
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
                return redirect(url_for('login'))
            user = User.query.get(user_id)
            if user.role != role:
                flash('Unauthorized access.', 'danger')
                return redirect(url_for('index'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator

@app.route('/')
def index():
    if 'user_id' in session:
        user = User.query.get(session['user_id'])
        if user.role == 'doctor':
            return redirect(url_for('doctor_dashboard'))
        elif user.role == 'patient':
            return redirect(url_for('patient_dashboard'))
        elif user.role == 'pharmacy':
            return redirect(url_for('pharmacy_dashboard'))
    return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'user_id' in session:
        return redirect(url_for('index'))
        
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            session['user_id'] = user.id
            session['role'] = user.role
            flash(f'Welcome back, {user.name}!', 'success')
            return redirect(url_for('index'))
        else:
            flash('Invalid username or password.', 'danger')
            
    return render_template('login.html')

@app.route('/register', methods=['POST'])
def register():
    username = request.form['username']
    password = request.form['password']
    name = request.form['name']
    role = request.form['role']
    contact = request.form['contact']
    location = request.form.get('location', '').strip()
    
    if User.query.filter_by(username=username).first():
        flash('Username already exists.', 'danger')
        return redirect(url_for('login'))
        
    user = User(username=username, name=name, role=role, contact=contact, location=location)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    
    flash('Registration successful! Please log in.', 'success')
    return redirect(url_for('login'))

@app.route('/logout')
def logout():
    session.clear()
    flash('Logged out successfully.', 'info')
    return redirect(url_for('login'))

# ----------------- DOCTOR PORTAL -----------------

@app.route('/dashboard/doctor')
@login_required
@role_required('doctor')
def doctor_dashboard():
    doctor_id = session['user_id']
    prescriptions = Prescription.query.filter_by(doctor_id=doctor_id).order_by(Prescription.created_at.desc()).all()
    return render_template('doctor.html', prescriptions=prescriptions)

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

    return render_template(
        'patient.html', 
        prescriptions=prescriptions,
        pending_prescriptions=pending_prescriptions,
        schedules=schedules,
        refill_alerts=refill_alerts,
        broadcasts=broadcasts,
        checklist=checklist
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
    frequency = request.form.get('frequency', '')
    times = request.form['time_of_day']  # raw list of times, e.g. "08:00, 20:00"
    end_date_str = request.form['end_date']
    current_stock = int(request.form.get('current_stock', 0))
    refill_alert = int(request.form.get('refill_alert_threshold', 5))
    
    end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
    
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
        
    bc = Broadcast(prescription_id=rx_id, patient_id=patient_id)
    db.session.add(bc)
    db.session.commit()
    
    flash('Prescription broadcasted to verified local pharmacies! Awaiting estimates.', 'success')
    return redirect(url_for('patient_dashboard'))

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
    
    # Filter by matching location (city name match)
    broadcasts = []
    for bc in all_broadcasts:
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
        
    return render_template(
        'pharmacy.html', 
        inventory=inventory, 
        broadcasts_info=active_broadcasts_info
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

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
