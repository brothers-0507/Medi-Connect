import unittest
from datetime import date, timedelta
from app import app, db, User, Prescription, PrescriptionItem, Broadcast, PharmacyOffer, MedicationSchedule, TrackerLog, InventoryItem, DoctorPreset, PatientNotification

class MediConnectTestCase(unittest.TestCase):
    def setUp(self):
        # Configure app for testing
        app.config['TESTING'] = True
        app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:' # Use in-memory SQLite for speed and isolation
        app.config['WTF_CSRF_ENABLED'] = False
        
        self.app = app.test_client()
        
        with app.app_context():
            db.create_all()
            
            # Setup base users for testing
            self.doc = User(username='test_doctor', name='Dr. Test', role='doctor', contact='doc@test.com')
            self.doc.set_password('password')
            
            self.pat = User(username='test_patient', name='Patient Test', role='patient', contact='555-9988', location='London')
            self.pat.set_password('password')
            
            self.ph = User(username='test_pharmacy', name='Pharmacy Test', role='pharmacy', contact='ph@test.com', location='London')
            self.ph.set_password('password')

            self.ph_2 = User(username='test_pharmacy_2', name='Pharmacy Test 2', role='pharmacy', contact='ph2@test.com', location='Paris')
            self.ph_2.set_password('password')
            
            db.session.add(self.doc)
            db.session.add(self.pat)
            db.session.add(self.ph)
            db.session.add(self.ph_2)
            db.session.commit()
            
            # Save IDs for reference
            self.doc_id = self.doc.id
            self.pat_id = self.pat.id
            self.ph_id = self.ph.id
            self.ph_2_id = self.ph_2.id

    def tearDown(self):
        with app.app_context():
            db.session.remove()
            db.drop_all()

    def login_as(self, username, password='password'):
        self.app.get('/logout')
        return self.app.post('/login', data=dict(username=username, password=password), follow_redirects=True)

    # --- Authentication Tests ---
    
    def test_login_logout(self):
        # Test incorrect password first (no user logged in yet)
        response = self.app.post('/login', data=dict(
            username='test_doctor',
            password='wrongpassword'
        ), follow_redirects=True)
        self.assertIn(b'Invalid username or password.', response.data)

        # Test successful login
        response = self.app.post('/login', data=dict(
            username='test_doctor',
            password='password'
        ), follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Dr. Test', response.data)

        # Test logout
        response = self.app.get('/logout', follow_redirects=True)
        self.assertIn(b'Logged out successfully.', response.data)

    def test_register_user(self):
        response = self.app.post('/register', data=dict(
            username='new_user',
            password='newpassword',
            name='New Person',
            role='patient',
            contact='111-2222',
            location='London'
        ), follow_redirects=True)
        
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Registration successful!', response.data)
        
        with app.app_context():
            user = User.query.filter_by(username='new_user').first()
            self.assertIsNotNone(user)
            self.assertEqual(user.name, 'New Person')
            self.assertEqual(user.location, 'London')
            self.assertTrue(user.check_password('newpassword'))

    # --- Doctor Prescription Tests ---

    def test_create_prescription(self):
        # Log in as doctor
        self.login_as('test_doctor')
        
        # Submit new prescription
        response = self.app.post('/prescription/create', data={
            'patient_username': 'test_patient',
            'patient_name': 'Patient Test',
            'patient_age': '28',
            'patient_contact': '555-9988',
            'instructions': 'Take after meals',
            'med_name[]': ['Amoxicillin', 'Ibuprofen'],
            'med_dosage[]': ['500mg', '400mg'],
            'med_frequency[]': ['twice daily', 'three times daily'],
            'med_duration[]': ['7 days', '3 days'],
            'med_instructions[]': ['before food', 'after food']
        }, follow_redirects=True)
        
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Digital prescription created successfully!', response.data)
        
        with app.app_context():
            rx = Prescription.query.filter_by(doctor_id=self.doc_id).first()
            self.assertIsNotNone(rx)
            self.assertEqual(rx.patient_id, self.pat_id)
            self.assertEqual(len(rx.items), 2)
            self.assertEqual(rx.items[0].medicine_name, 'Amoxicillin')
            self.assertEqual(rx.items[1].duration, '3 days')
            self.assertIsNotNone(rx.uuid)

    # --- Patient Portal Tests (Claim, Tracker, Broadcast) ---

    def test_claim_prescription(self):
        # Create prescription first
        with app.app_context():
            rx = Prescription(doctor_id=self.doc_id, patient_name='Anon', patient_contact='none')
            db.session.add(rx)
            db.session.commit()
            rx_uuid = rx.uuid
            
        # Log in as patient
        self.login_as('test_patient')
        
        # Claim it
        response = self.app.post('/prescription/claim', data=dict(
            prescription_code=rx_uuid
        ), follow_redirects=True)
        
        self.assertIn(b'Prescription successfully claimed', response.data)
        
        with app.app_context():
            rx_updated = Prescription.query.filter_by(uuid=rx_uuid).first()
            self.assertEqual(rx_updated.patient_id, self.pat_id)

    def test_medi_tracker_log(self):
        # Log in as patient
        self.login_as('test_patient')
        
        # Create schedule
        with app.app_context():
            sched = MedicationSchedule(
                patient_id=self.pat_id,
                medicine_name='Vitamin C',
                dosage='1 pill',
                time_of_day='08:00',
                start_date=date.today(),
                end_date=date.today() + timedelta(days=5),
                current_stock=10,
                refill_alert_threshold=3
            )
            db.session.add(sched)
            db.session.commit()
            sched_id = sched.id
            
        # Log dose taken
        response = self.app.post(f'/tracker/log/{sched_id}', data=dict(action='taken'))
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data['success'])
        self.assertEqual(data['current_stock'], 9)
        self.assertFalse(data['running_low'])
        
        with app.app_context():
            logs = TrackerLog.query.filter_by(schedule_id=sched_id).all()
            self.assertEqual(len(logs), 1)
            self.assertEqual(logs[0].status, 'taken')

    def test_add_custom_tracker(self):
        self.login_as('test_patient')
        
        # Submit simplified custom tracker parameters
        response = self.app.post('/tracker/add', data=dict(
            medicine_name='Vitamin D3',
            dosage='1 capsule',
            time_of_day='09:00',
            current_stock='30'
        ), follow_redirects=True)
        
        self.assertIn(b'Medication added to Medi-Tracker!', response.data)
        
        with app.app_context():
            sched = MedicationSchedule.query.filter_by(patient_id=self.pat_id, medicine_name='Vitamin D3').first()
            self.assertIsNotNone(sched)
            self.assertEqual(sched.dosage, '1 capsule')
            self.assertEqual(sched.time_of_day, '09:00')
            self.assertEqual(sched.current_stock, 30)
            self.assertEqual(sched.frequency, 'Daily') # Default applied
            self.assertEqual(sched.refill_alert_threshold, 5) # Default applied
            self.assertEqual(sched.end_date, date.today() + timedelta(days=30)) # Default applied

    def test_prescription_broadcast_and_offer(self):
        # Create prescription
        with app.app_context():
            rx = Prescription(doctor_id=self.doc_id, patient_id=self.pat_id, patient_name='Patient Test')
            item = PrescriptionItem(prescription=rx, medicine_name='Paracetamol', dosage='1 tab', frequency='daily', duration='5 days')
            db.session.add(rx)
            db.session.add(item)
            db.session.commit()
            rx_id = rx.id
            
        # Log in as patient & Broadcast
        self.login_as('test_patient')
        response = self.app.post('/broadcast/create', data=dict(prescription_id=rx_id), follow_redirects=True)
        self.assertIn(b'Prescription broadcasted to verified local pharmacies!', response.data)
        
        with app.app_context():
            bc = Broadcast.query.filter_by(prescription_id=rx_id, patient_id=self.pat_id).first()
            self.assertIsNotNone(bc)
            bc_id = bc.id
            
        # Log in as pharmacy & Bid
        self.login_as('test_pharmacy')
        response = self.app.post('/broadcast/offer', data=dict(
            broadcast_id=bc_id,
            price='12.50',
            availability_status='available',
            notes='Ready in 10 minutes'
        ), follow_redirects=True)
        
        self.assertIn(b'Price estimate and availability submitted successfully!', response.data)
        
        with app.app_context():
            offer = PharmacyOffer.query.filter_by(broadcast_id=bc_id, pharmacy_id=self.ph_id).first()
            self.assertIsNotNone(offer)
            self.assertEqual(offer.estimated_price, 12.50)
            self.assertEqual(offer.availability_status, 'available')

    # --- Pharmacy Stock Management & Checkout Tests ---

    def test_pharmacy_checkout(self):
        # Log in as pharmacy
        self.login_as('test_pharmacy')
        
        # Add stock item
        response = self.app.post('/inventory/add', data=dict(
            medicine_name='Aspirin',
            stock_level='50',
            price='5.99',
            batch_number='B-1234',
            expiry_date=(date.today() + timedelta(days=365)).strftime('%Y-%m-%d')
        ), follow_redirects=True)
        self.assertIn(b'Aspirin added to inventory!', response.data)
        
        # Checkout sale
        response = self.app.post('/checkout', data=dict(
            medicine_name='Aspirin',
            quantity='15'
        ))
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data['success'])
        self.assertIn('Deducted 15 from batch B-1234', data['message'])
        
        # Verify inventory stock deducted
        with app.app_context():
            item = InventoryItem.query.filter_by(pharmacy_id=self.ph_id, medicine_name='Aspirin').first()
            self.assertEqual(item.stock_level, 35)

    def test_pharmacy_checkout_expiring_soon_warning(self):
        # Log in as pharmacy
        self.login_as('test_pharmacy')
        
        # Add stock item expiring in 10 days
        self.app.post('/inventory/add', data=dict(
            medicine_name='ExpiringMed',
            stock_level='50',
            price='10.00',
            batch_number='EXP-999',
            expiry_date=(date.today() + timedelta(days=10)).strftime('%Y-%m-%d')
        ))
        
        # Checkout sale
        response = self.app.post('/checkout', data=dict(
            medicine_name='ExpiringMed',
            quantity='5'
        ))
        data = response.get_json()
        self.assertTrue(data['success'])
        self.assertIn('Sold stock contains batches near expiration: Batch EXP-999', data['message'])

    def test_accept_prescription(self):
        # Create prescription first
        with app.app_context():
            rx = Prescription(
                doctor_id=self.doc_id, 
                patient_id=self.pat_id, 
                patient_name='Patient Test', 
                patient_contact='555-9988',
                is_claimed=False
            )
            # Add item
            item = PrescriptionItem(medicine_name='Amoxicillin', dosage='500mg', frequency='twice daily', duration='7 days')
            rx.items.append(item)
            db.session.add(rx)
            db.session.commit()
            rx_id = rx.id

        # Log in as patient
        self.login_as('test_patient')
        
        # Verify it appears in pending
        response = self.app.get('/dashboard/patient')
        self.assertIn(b'New Prescription Alert!', response.data)
        
        # Accept it
        response = self.app.post(f'/prescription/accept/{rx_id}', follow_redirects=True)
        self.assertIn(b'Prescription accepted and imported', response.data)
        
        # Verify is_claimed is True and schedule exists
        with app.app_context():
            rx_updated = Prescription.query.get(rx_id)
            self.assertTrue(rx_updated.is_claimed)
            
            sched = MedicationSchedule.query.filter_by(patient_id=self.pat_id, medicine_name='Amoxicillin').first()
            self.assertIsNotNone(sched)
            self.assertEqual(sched.current_stock, 14) # 2 doses/day * 7 days

    def test_location_broadcast_filtering(self):
        # Create prescription and broadcast it
        with app.app_context():
            rx = Prescription(
                doctor_id=self.doc_id,
                patient_id=self.pat_id,
                patient_name='Patient Test',
                patient_contact='555-9988',
                is_claimed=True
            )
            # Add item
            item = PrescriptionItem(medicine_name='Amoxicillin', dosage='500mg', frequency='twice daily', duration='7 days')
            rx.items.append(item)
            db.session.add(rx)
            db.session.commit()
            
            bc = Broadcast(prescription_id=rx.id, patient_id=self.pat_id)
            db.session.add(bc)
            db.session.commit()
            rx_uuid = rx.uuid

        # Log in as test_pharmacy (location = London, matches patient)
        self.login_as('test_pharmacy')
        response = self.app.get('/dashboard/pharmacy')
        self.assertIn(rx_uuid[:8].encode(), response.data) # London pharmacy sees the broadcast!

        # Log in as test_pharmacy_2 (location = Paris, does NOT match patient)
        self.login_as('test_pharmacy_2')
        response = self.app.get('/dashboard/pharmacy')
        self.assertNotIn(rx_uuid[:8].encode(), response.data) # Paris pharmacy does NOT see the broadcast!

    def test_settings_page_requires_auth(self):
        # Accessing settings without login should redirect
        response = self.app.get('/settings')
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login', response.location)

    def test_update_profile_settings(self):
        self.login_as('test_doctor')
        
        # Update details
        response = self.app.post('/settings/update', data=dict(
            name='Dr. New Name',
            username='doctor_new',
            contact='newcontact@test.com',
            location='Edinburgh'
        ), follow_redirects=True)
        
        self.assertIn(b'Profile details updated successfully!', response.data)
        
        with app.app_context():
            user = User.query.get(self.doc_id)
            self.assertEqual(user.name, 'Dr. New Name')
            self.assertEqual(user.username, 'doctor_new')
            self.assertEqual(user.contact, 'newcontact@test.com')
            self.assertEqual(user.location, 'Edinburgh')

    def test_update_profile_username_collision(self):
        self.login_as('test_doctor')
        
        # Try to take 'test_patient' username
        response = self.app.post('/settings/update', data=dict(
            name='Dr. New Name',
            username='test_patient',
            contact='doc@test.com',
            location='Edinburgh'
        ), follow_redirects=True)
        
        self.assertIn(b'Username is already taken by another account.', response.data)
        
        with app.app_context():
            user = User.query.get(self.doc_id)
            self.assertEqual(user.username, 'test_doctor') # Remained unchanged

    def test_update_password_success(self):
        self.login_as('test_doctor')
        
        # Change password
        response = self.app.post('/settings/password', data=dict(
            current_password='password',
            new_password='newsecurepassword',
            confirm_password='newsecurepassword'
        ), follow_redirects=True)
        
        self.assertIn(b'Password updated successfully!', response.data)
        
        # Log out and log back in with new password
        self.login_as('test_doctor', password='newsecurepassword')
        response = self.app.get('/dashboard/doctor')
        self.assertIn(b'Dr. Test', response.data)

    def test_update_password_wrong_current(self):
        self.login_as('test_doctor')
        
        # Change password with wrong current password
        response = self.app.post('/settings/password', data=dict(
            current_password='wrongpassword',
            new_password='newsecurepassword',
            confirm_password='newsecurepassword'
        ), follow_redirects=True)
        
        self.assertIn(b'Current password is incorrect.', response.data)

    # --- Role-Based Portal Access Control Tests ---

    def test_cross_portal_dashboard_access_denied_and_safe_redirect(self):
        # Patient logs in
        self.login_as('test_patient')
        
        # Attempt to access doctor dashboard
        response = self.app.get('/dashboard/doctor', follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Access Denied', response.data)
        self.assertIn(b'Doctor', response.data)
        # Verify session is preserved and user redirected to patient dashboard
        self.assertIn(b'Patient Test', response.data)

        # Attempt to access pharmacy dashboard
        response = self.app.get('/dashboard/pharmacy', follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Access Denied', response.data)
        self.assertIn(b'Pharmacy', response.data)
        self.assertIn(b'Patient Test', response.data)

    def test_portal_login_role_rejection(self):
        self.app.get('/logout')
        
        # Attempt to log in through Doctor Portal using Patient account
        response = self.app.post('/login', data=dict(
            portal='doctor',
            username='test_patient',
            password='password'
        ), follow_redirects=True)
        
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Access Denied', response.data)
        self.assertIn(b'registered as a Patient', response.data)
        
        # Verify no dashboard was accessed
        self.assertNotIn(b'My Dashboard', response.data)

    def test_portal_login_role_success(self):
        self.app.get('/logout')
        
        # Log in through Doctor Portal using Doctor account
        response = self.app.post('/login', data=dict(
            portal='doctor',
            username='test_doctor',
            password='password'
        ), follow_redirects=True)
        
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Welcome back, Dr. Test!', response.data)
        self.assertIn(b'New Prescription', response.data)

    def test_portal_gateway_routes(self):
        # Unauthenticated access redirects to portal login
        self.app.get('/logout')
        response = self.app.get('/portal/doctor', follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login?portal=doctor', response.headers['Location'])

        # Doctor accesses doctor portal gateway
        self.login_as('test_doctor')
        response = self.app.get('/portal/doctor', follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'New Prescription', response.data)

        # Doctor attempts to access patient portal gateway
        response = self.app.get('/portal/patient', follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Access Denied', response.data)
        self.assertIn(b'Dr. Test', response.data)

    def test_patient_lookup_autofill(self):
        # Doctor looking up existing patient
        self.login_as('test_doctor')
        response = self.app.get('/api/patient/lookup?username=test_patient')
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data['found'])
        self.assertEqual(data['name'], 'Patient Test')
        self.assertEqual(data['contact'], '555-9988')

        # Looking up non-existent username
        response = self.app.get('/api/patient/lookup?username=nonexistent_user')
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertFalse(data['found'])

    def test_find_nearest_pharmacies_and_stock(self):
        # Create a prescription with Amoxicillin for test_patient
        with app.app_context():
            rx = Prescription(
                doctor_id=self.doc_id,
                patient_id=self.pat_id,
                patient_name='Patient Test',
                patient_contact='555-9988'
            )
            db.session.add(rx)
            db.session.commit()
            
            rx_item = PrescriptionItem(
                prescription_id=rx.id,
                medicine_name='Amoxicillin',
                dosage='500mg',
                frequency='3x daily',
                duration='7 days'
            )
            db.session.add(rx_item)
            
            # Seed pharmacy inventory
            # Pharmacy 1 has Amoxicillin in stock
            inv1 = InventoryItem(
                pharmacy_id=self.ph_id,
                medicine_name='Amoxicillin',
                stock_level=50,
                price=15.00,
                batch_number='TEST-AMX',
                expiry_date=date.today() + timedelta(days=100)
            )
            db.session.add(inv1)
            
            # Set coordinates for pharmacy 1
            ph1_user = User.query.get(self.ph_id)
            ph1_user.latitude = 51.5074
            ph1_user.longitude = -0.1278
            ph1_user.address = 'Central Pharmacy, London'
            
            # Set coordinates for pharmacy 2 (further away and out of stock)
            ph2_user = User.query.get(self.ph_2_id)
            ph2_user.latitude = 51.5500
            ph2_user.longitude = -0.1500
            ph2_user.address = 'North Pharmacy, London'
            
            db.session.commit()
            rx_id = rx.id

        self.login_as('test_patient')
        # Query nearest pharmacies passing patient coordinates near London center
        response = self.app.post(f'/api/prescription/{rx_id}/find-pharmacies', json=dict(
            latitude=51.5050,
            longitude=-0.1250
        ))
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data['success'])
        self.assertEqual(len(data['pharmacies']), 2)
        
        # First pharmacy should be in stock and closer
        first_ph = data['pharmacies'][0]
        self.assertEqual(first_ph['pharmacy_id'], self.ph_id)
        self.assertEqual(first_ph['stock_status'], 'available')
        self.assertEqual(first_ph['estimated_price'], 15.00)
        self.assertLess(first_ph['distance_km'], 2.0)

    def test_broadcast_target_nearest(self):
        with app.app_context():
            rx = Prescription(
                doctor_id=self.doc_id,
                patient_id=self.pat_id,
                patient_name='Patient Test'
            )
            db.session.add(rx)
            db.session.commit()
            rx_id = rx.id

        self.login_as('test_patient')
        # Target broadcast to pharmacy 1
        response = self.app.post('/api/broadcast/target-nearest', json=dict(
            prescription_id=rx_id,
            pharmacy_id=self.ph_id,
            latitude=51.5050,
            longitude=-0.1250
        ))
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data['success'])
        
        # Verify broadcast in DB
        with app.app_context():
            bc = Broadcast.query.filter_by(prescription_id=rx_id).first()
            self.assertIsNotNone(bc)
            self.assertEqual(bc.target_pharmacy_id, self.ph_id)
            self.assertAlmostEqual(bc.patient_lat, 51.5050)

    def test_doctor_bio_update_and_dashboard(self):
        # 1. Update via POST /api/doctor/bio
        self.login_as('test_doctor')
        res = self.app.post('/api/doctor/bio', json=dict(bio='MD General Medicine, AIIMS New Delhi'))
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data['success'])
        self.assertEqual(data['bio'], 'MD General Medicine, AIIMS New Delhi')

        # Verify bio shows up on doctor dashboard
        dash_res = self.app.get('/dashboard/doctor')
        self.assertEqual(dash_res.status_code, 200)
        self.assertIn(b'MD General Medicine, AIIMS New Delhi', dash_res.data)
        # Ensure "Lookup Patient" button is removed
        self.assertNotIn(b'Lookup Patient', dash_res.data)
        # Ensure KPI grid cards were removed
        self.assertNotIn(b'kpi-grid', dash_res.data)

        # 2. Update via /settings/update form
        settings_res = self.app.post('/settings/update', data=dict(
            name='Dr. Test',
            username='test_doctor',
            contact='doc@test.com',
            bio='Senior Consultant Physician, Apollo Hospitals Bangalore'
        ), follow_redirects=True)
        self.assertEqual(settings_res.status_code, 200)
        with app.app_context():
            user = db.session.get(User, self.doc_id)
            self.assertEqual(user.bio, 'Senior Consultant Physician, Apollo Hospitals Bangalore')

        # 3. Update badges with add/remove via doctor_badges_json in /settings/update
        import json
        custom_badges = [
            {"icon": "ph-identification-badge", "text": "Reg No: DEL-99881"},
            {"icon": "ph-stethoscope", "text": "Cardiology Specialist"}
        ]
        settings_res2 = self.app.post('/settings/update', data=dict(
            name='Dr. Test',
            username='test_doctor',
            contact='doc@test.com',
            doctor_badges_json=json.dumps(custom_badges)
        ), follow_redirects=True)
        self.assertEqual(settings_res2.status_code, 200)
        
        # Verify custom badges on doctor dashboard
        dash_res2 = self.app.get('/dashboard/doctor')
        self.assertEqual(dash_res2.status_code, 200)
        self.assertIn(b'Reg No: DEL-99881', dash_res2.data)
        self.assertIn(b'Cardiology Specialist', dash_res2.data)
        # Workplace was removed in custom_badges, so ensure it does not appear
        self.assertNotIn(b'Fortis Care, Bengaluru', dash_res2.data)

    def test_patient_dashboard_clean_ui(self):
        self.login_as('test_patient')
        res = self.app.get('/dashboard/patient')
        self.assertEqual(res.status_code, 200)
        # Verify clinical banner and KPIs are removed
        self.assertNotIn(b'clinical-banner', res.data)
        self.assertNotIn(b'Adherence Rate', res.data)
        self.assertNotIn(b'Refill Alerts', res.data)
        # Verify 4 daypart schedule cards are removed
        self.assertNotIn(b'daypart-grid', res.data)
        self.assertNotIn(b'08:00 AM &bull; With breakfast', res.data)
        # Verify core patient features remain intact
        self.assertIn(b"Daily Medication Routine", res.data)
        self.assertIn(b'My Prescriptions', res.data)

    def test_doctor_new_prescription_and_delete(self):
        self.login_as('test_doctor')
        
        # 1. GET new prescription page
        get_res = self.app.get('/doctor/prescription/new')
        self.assertEqual(get_res.status_code, 200)
        self.assertIn(b'Create Digital Prescription', get_res.data)
        self.assertIn(b'Prescribed Medicines', get_res.data)
        
        # 2. POST to new prescription page
        post_res = self.app.post('/doctor/prescription/new', data={
            'patient_username': 'test_patient',
            'patient_name': 'Patient Test',
            'patient_age': '30',
            'patient_contact': '9876543210',
            'instructions': 'Drink plenty of water',
            'med_name[]': ['Azithromycin 500mg'],
            'med_dosage[]': ['1 Tab'],
            'med_frequency[]': ['Once daily (OD)'],
            'med_duration[]': ['3 days'],
            'med_instructions[]': ['After dinner']
        }, follow_redirects=True)
        self.assertEqual(post_res.status_code, 200)
        self.assertIn(b'Digital prescription created successfully!', post_res.data)

        # Retrieve newly created prescription
        with app.app_context():
            rx = Prescription.query.filter_by(doctor_id=self.doc_id).order_by(Prescription.id.desc()).first()
            self.assertIsNotNone(rx)
            rx_id = rx.id
            self.assertEqual(len(rx.items), 1)
            self.assertEqual(rx.items[0].medicine_name, 'Azithromycin 500mg')

        # 3. Doctor deletes own prescription
        del_res = self.app.post(f'/prescription/{rx_id}/delete', follow_redirects=True)
        self.assertEqual(del_res.status_code, 200)
        self.assertIn(b'deleted successfully.', del_res.data)

        with app.app_context():
            deleted_rx = db.session.get(Prescription, rx_id)
            self.assertIsNone(deleted_rx)
            # Ensure items cascaded
            items = PrescriptionItem.query.filter_by(prescription_id=rx_id).all()
            self.assertEqual(len(items), 0)

    def test_pharmacy_dashboard_clean_ui_and_modal(self):
        self.login_as('test_pharmacy')
        res = self.app.get('/dashboard/pharmacy')
        self.assertEqual(res.status_code, 200)
        # Verify clinical banner and KPI grid are removed
        self.assertNotIn(b'clinical-banner', res.data)
        self.assertNotIn(b'kpi-grid', res.data)
        self.assertNotIn(b'Stock SKUs', res.data)
        # Verify Scan Rx QR and Add Stock Item buttons exist
        self.assertIn(b'Scan Rx QR', res.data)
        self.assertIn(b'Add Stock Item', res.data)
        # Verify modal overlay exists
        self.assertIn(b'id="add-stock-modal"', res.data)
        self.assertIn(b'modal_medicine_name', res.data)
        # Verify inline form is removed and table card exists
        self.assertNotIn(b'grid-container', res.data)
        self.assertIn(b'Current Inventory', res.data)

    def test_pharmacy_multi_item_checkout(self):
        self.login_as('test_pharmacy')
        # Add stock for 2 items
        with app.app_context():
            i1 = InventoryItem(
                pharmacy_id=self.ph_id,
                medicine_name='MultiMed Alpha',
                stock_level=50,
                price=15.00,
                batch_number='BT-A1',
                expiry_date=date.today() + timedelta(days=200)
            )
            i2 = InventoryItem(
                pharmacy_id=self.ph_id,
                medicine_name='MultiMed Beta',
                stock_level=30,
                price=25.00,
                batch_number='BT-B1',
                expiry_date=date.today() + timedelta(days=300)
            )
            db.session.add_all([i1, i2])
            db.session.commit()

        # Multi-item checkout via JSON
        res = self.app.post('/checkout', json={
            'items': [
                {'medicine_name': 'MultiMed Alpha', 'quantity': 10},
                {'medicine_name': 'MultiMed Beta', 'quantity': 5}
            ]
        })
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data['success'])
        self.assertIn('Checkout completed successfully for 2 medicine(s)', data['message'])
        self.assertEqual(len(data['results']), 2)

        # Verify DB stock deducted
        with app.app_context():
            item1 = InventoryItem.query.filter_by(pharmacy_id=self.ph_id, medicine_name='MultiMed Alpha').first()
            item2 = InventoryItem.query.filter_by(pharmacy_id=self.ph_id, medicine_name='MultiMed Beta').first()
            self.assertEqual(item1.stock_level, 40)
            self.assertEqual(item2.stock_level, 25)

    def test_prescription_api_full_item_details_and_inventory_match(self):
        # Create multi-item prescription
        with app.app_context():
            rx = Prescription(
                doctor_id=self.doc_id,
                patient_id=self.pat_id,
                patient_name='Jane Doe',
                patient_age=35,
                patient_contact='9876543210',
                instructions='Take after breakfast and dinner'
            )
            it1 = PrescriptionItem(
                prescription=rx,
                medicine_name='Amoxicillin 500mg',
                dosage='1 Capsule',
                frequency='TID (Three times daily)',
                duration='5 days',
                instructions='After meals'
            )
            it2 = PrescriptionItem(
                prescription=rx,
                medicine_name='Paracetamol 650mg',
                dosage='1 Tablet',
                frequency='SOS / As needed',
                duration='3 days',
                instructions='During fever'
            )
            db.session.add_all([rx, it1, it2])
            db.session.commit()
            rx_uuid = rx.uuid

            # Add matching stock for Amoxicillin in pharmacy inventory
            inv = InventoryItem(
                pharmacy_id=self.ph_id,
                medicine_name='Amoxicillin 500mg',
                stock_level=80,
                price=12.50,
                batch_number='AMX-01',
                expiry_date=date.today() + timedelta(days=180)
            )
            db.session.add(inv)
            db.session.commit()

        # Call prescription API as pharmacy
        self.login_as('test_pharmacy')
        res = self.app.get(f'/prescription/api/{rx_uuid}')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data['success'])
        self.assertEqual(data['patient_name'], 'Jane Doe')
        self.assertEqual(len(data['items']), 2)
        
        # Verify complete details and inventory match
        amx_item = next(i for i in data['items'] if 'Amoxicillin' in i['medicine_name'])
        self.assertEqual(amx_item['dosage'], '1 Capsule')
        self.assertEqual(amx_item['frequency'], 'TID (Three times daily)')
        self.assertTrue(amx_item['in_stock'])
        self.assertEqual(amx_item['available_stock'], 80)
        self.assertEqual(amx_item['unit_price'], 12.50)

        pcm_item = next(i for i in data['items'] if 'Paracetamol' in i['medicine_name'])
        self.assertFalse(pcm_item['in_stock'])
        self.assertEqual(pcm_item['available_stock'], 0)

    def test_pharmacy_dashboard_navigation_and_slots(self):
        self.login_as('test_pharmacy')
        res = self.app.get('/dashboard/pharmacy')
        self.assertEqual(res.status_code, 200)
        # Verify fixed pharmacy navigation toolbar (no slidebars)
        self.assertIn(b'class="pharmacy-nav-toolbar no-print"', res.data)
        self.assertIn(b'id="tab-btn-inventory"', res.data)
        self.assertIn(b'id="tab-btn-broadcasts"', res.data)
        self.assertIn(b'id="tab-btn-checkout"', res.data)
        self.assertIn(b'switchPharmacyTab(\'inventory-tab\')', res.data)
        self.assertIn(b'switchPharmacyTab(\'broadcasts-tab\')', res.data)
        self.assertIn(b'switchPharmacyTab(\'checkout-tab\')', res.data)
        # Verify multi-medicine dispensing counter & slots container
        self.assertIn(b'Multi-Medicine Dispensing Counter', res.data)
        self.assertIn(b'id="checkout-slots-container"', res.data)
        self.assertIn(b'id="scanned-rx-card"', res.data)
        self.assertIn(b'Add Another Medicine Slot', res.data)
        self.assertIn(b'Complete Sale & Deduct All Medicines', res.data)

    def test_doctor_preset_creation_and_deletion(self):
        self.login_as('test_doctor')
        # Create custom preset via POST
        res = self.app.post('/api/doctor/presets', json={
            'name': 'Diabetes Routine',
            'icon': '🩸',
            'medications': [
                {'medicine_name': 'Metformin 500mg', 'dosage': '500mg', 'frequency': 'Twice daily', 'duration': '30 days', 'instructions': 'After food'},
                {'medicine_name': 'Glimepiride 1mg', 'dosage': '1mg', 'frequency': 'Once daily', 'duration': '30 days', 'instructions': 'Before breakfast'}
            ]
        })
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data['success'])
        preset_id = data['preset']['id']
        self.assertEqual(data['preset']['name'], 'Diabetes Routine')

        # Verify custom preset appears in GET /api/doctor/presets
        get_res = self.app.get('/api/doctor/presets')
        self.assertEqual(get_res.status_code, 200)
        get_data = get_res.get_json()
        self.assertTrue(any(p['name'] == 'Diabetes Routine' for p in get_data['presets']))

        # Delete preset
        del_res = self.app.delete(f'/api/doctor/presets/{preset_id}')
        self.assertEqual(del_res.status_code, 200)
        self.assertTrue(del_res.get_json()['success'])

    def test_pharmacy_registration_geolocation(self):
        # Register a pharmacy with explicit address and coordinates
        res = self.app.post('/register', data={
            'username': 'indiranagar_pharma',
            'password': 'password123',
            'name': 'Indiranagar Care Meds',
            'role': 'pharmacy',
            'contact': '+91 98450 11223',
            'location': 'Bengaluru, Karnataka',
            'address': '100ft Road, HAL 2nd Stage, Indiranagar',
            'latitude': '12.9784',
            'longitude': '77.6408'
        }, follow_redirects=True)
        self.assertEqual(res.status_code, 200)

        with app.app_context():
            user = User.query.filter_by(username='indiranagar_pharma').first()
            self.assertIsNotNone(user)
            self.assertEqual(user.role, 'pharmacy')
            self.assertAlmostEqual(user.latitude, 12.9784, places=4)
            self.assertAlmostEqual(user.longitude, 77.6408, places=4)
            self.assertIn('Indiranagar', user.address)

    def test_patient_live_notifications_api(self):
        # 1. Issue prescription as doctor for test_patient
        self.login_as('test_doctor')
        rx_res = self.app.post('/prescription/create', data={
            'patient_username': 'test_patient',
            'patient_name': 'Patient Test',
            'patient_age': '29',
            'patient_contact': '555-9988',
            'instructions': 'Drink plenty of water',
            'med_name[]': ['Dolo 650'],
            'med_dosage[]': ['650mg'],
            'med_frequency[]': ['TDS'],
            'med_duration[]': ['3 days'],
            'med_instructions[]': ['After meals']
        }, headers={'X-Requested-With': 'XMLHttpRequest'})
        self.assertEqual(rx_res.status_code, 200)
        rx_data = rx_res.get_json()
        self.assertTrue(rx_data['success'])

        # 2. Login as patient and check live notifications endpoint
        self.login_as('test_patient')
        notif_res = self.app.get('/api/patient/notifications/live')
        self.assertEqual(notif_res.status_code, 200)
        notif_data = notif_res.get_json()
        self.assertTrue(notif_data['success'])
        self.assertGreaterEqual(notif_data['unread_count'], 1)
        self.assertTrue(any('Prescription' in n['title'] for n in notif_data['notifications']))
        self.assertGreaterEqual(len(notif_data['pending_prescriptions']), 1)

        # 3. Mark all notifications as read
        read_all_res = self.app.post('/api/patient/notifications/read-all')
        self.assertEqual(read_all_res.status_code, 200)
        self.assertTrue(read_all_res.get_json()['success'])

        check_res = self.app.get('/api/patient/notifications/live')
        self.assertEqual(check_res.get_json()['unread_count'], 0)

    def test_doctor_workspace_and_custom_prescriptions_page(self):
        self.login_as('test_doctor')
        # Check doctor workspace has prescription form directly on display
        dash_res = self.app.get('/dashboard/doctor')
        self.assertEqual(dash_res.status_code, 200)
        self.assertIn(b'Digital Prescription Creator', dash_res.data)
        self.assertIn(b'1-Click Medication Presets', dash_res.data)
        self.assertIn(b'Recent Prescriptions', dash_res.data)
        self.assertIn(b'Issued Prescriptions Archive', dash_res.data)

        # Check dedicated custom prescriptions archive page
        archive_res = self.app.get('/doctor/prescriptions')
        self.assertEqual(archive_res.status_code, 200)
        self.assertIn(b'Issued Prescriptions Archive', archive_res.data)
        self.assertIn(b'All Prescriptions', archive_res.data)

    def test_dedicated_registration_page_and_purified_login(self):
        # 1. Test GET /login contains only sign-in, no registration tabs or forms
        login_res = self.app.get('/login')
        self.assertEqual(login_res.status_code, 200)
        self.assertIn(b'Sign In to MediConnect', login_res.data)
        self.assertNotIn(b'id="register-tab"', login_res.data)
        self.assertNotIn(b'id="register-form"', login_res.data)
        self.assertNotIn(b"Don't have an account?", login_res.data)

        # 2. Test navbar contains Register dropdown with roles
        self.assertIn(b'Register', login_res.data)
        self.assertIn(b'/register?role=doctor', login_res.data)
        self.assertIn(b'/register?role=patient', login_res.data)
        self.assertIn(b'/register?role=pharmacy', login_res.data)

        # 3. Test GET /register renders dedicated registration page
        reg_res = self.app.get('/register?role=doctor')
        self.assertEqual(reg_res.status_code, 200)
        self.assertIn(b'Create Your Account', reg_res.data)
        self.assertIn(b'Medical Registration Number', reg_res.data)
        self.assertIn(b'id="role-btn-doctor"', reg_res.data)

        # 4. Test doctor registration with credentials
        post_reg_res = self.app.post('/register', data={
            'username': 'dr_newuser',
            'password': 'password',
            'name': 'Dr. New Clinician',
            'role': 'doctor',
            'contact': '9876543210',
            'reg_no': 'KMC-99999',
            'department': 'Pediatrics',
            'workplace': 'Manipal Hospital, Bengaluru'
        }, follow_redirects=True)
        self.assertEqual(post_reg_res.status_code, 200)

        with app.app_context():
            doc = User.query.filter_by(username='dr_newuser').first()
            self.assertIsNotNone(doc)
            self.assertEqual(doc.role, 'doctor')
            badges = doc.get_doctor_badges()
            self.assertTrue(any('KMC-99999' in b['text'] for b in badges))
            self.assertTrue(any('Pediatrics' in b['text'] for b in badges))

    def test_patient_method_1_and_4_routine_tracker(self):
        # 1. Test categorization of times into slots
        from app import categorize_time_slot
        self.assertEqual(categorize_time_slot('08:00'), 'morning')
        self.assertEqual(categorize_time_slot('morning'), 'morning')
        self.assertEqual(categorize_time_slot('breakfast'), 'morning')
        self.assertEqual(categorize_time_slot('13:30'), 'afternoon')
        self.assertEqual(categorize_time_slot('lunch'), 'afternoon')
        self.assertEqual(categorize_time_slot('19:00'), 'evening')
        self.assertEqual(categorize_time_slot('dinner'), 'evening')
        self.assertEqual(categorize_time_slot('22:00'), 'night')
        self.assertEqual(categorize_time_slot('bedtime'), 'night')

        # 2. Setup patient with medication schedules covering slots
        with app.app_context():
            s1 = MedicationSchedule(
                patient_id=self.pat_id,
                medicine_name='Dolo 650',
                dosage='1 tab',
                frequency='Twice daily',
                time_of_day='09:00, 21:00',
                start_date=date.today(),
                end_date=date.today() + timedelta(days=5),
                current_stock=10,
                refill_alert_threshold=3
            )
            s2 = MedicationSchedule(
                patient_id=self.pat_id,
                medicine_name='Pan-D',
                dosage='1 cap',
                frequency='Daily',
                time_of_day='08:00',
                start_date=date.today(),
                end_date=date.today() + timedelta(days=5),
                current_stock=2, # low stock to trigger watchdog
                refill_alert_threshold=3
            )
            db.session.add(s1)
            db.session.add(s2)
            db.session.commit()
            s1_id = s1.id
            s2_id = s2.id

        # 3. Log in as patient and verify Method 1 + 4 UI components
        self.login_as('test_patient')
        res = self.app.get('/dashboard/patient')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'Daily Medication Routine', res.data)
        self.assertIn(b'Morning Routine', res.data)
        self.assertIn(b'Afternoon Routine', res.data)
        self.assertIn(b'Evening Routine', res.data)
        self.assertIn(b'Night / Bedtime', res.data)
        self.assertIn(b"Today's Adherence", res.data)
        self.assertIn(b'Stock & Refill Watchdog', res.data)
        self.assertIn(b'Add Custom Medication', res.data)
        self.assertIn(b'Dolo 650', res.data)
        self.assertIn(b'Pan-D', res.data)

        # 4. Test individual dose log with taken_time and stock decrement
        log_res = self.app.post(f'/tracker/log/{s1_id}', data={'action': 'taken'})
        self.assertEqual(log_res.status_code, 200)
        log_data = log_res.get_json()
        self.assertTrue(log_data['success'])
        self.assertEqual(log_data['current_stock'], 9)
        self.assertIn('taken_time', log_data)

        # 5. Test take slot API endpoint (/api/tracker/take-slot/morning)
        slot_res = self.app.post('/api/tracker/take-slot/morning')
        self.assertEqual(slot_res.status_code, 200)
        slot_data = slot_res.get_json()
        self.assertTrue(slot_data['success'])
        self.assertGreaterEqual(slot_data['logged_count'], 1)
        self.assertIn('taken_time', slot_data)

        # Verify s2 stock was decremented by take-slot
        with app.app_context():
            s2_check = db.session.get(MedicationSchedule, s2_id)
            self.assertEqual(s2_check.current_stock, 1)

    def test_landing_page_uploaded_design(self):
        # Test GET / renders the uploaded hero dashboard design
        res = self.app.get('/')
        self.assertEqual(res.status_code, 200)

        # Hero content
        self.assertIn(b'Bridging the Gap in', res.data)
        self.assertIn(b'Healthcare Adherence', res.data)
        self.assertIn(b'SELECT YOUR PORTAL TO GET STARTED', res.data)

        # 3 Portal Cards
        self.assertIn(b'Practitioner Portal', res.data)
        self.assertIn(b'Doctor Log In', res.data)
        self.assertIn(b'/login?portal=doctor', res.data)
        self.assertIn(b'/register?role=doctor', res.data)

        self.assertIn(b'Personal Health Space', res.data)
        self.assertIn(b'Patient Log In', res.data)
        self.assertIn(b'/login?portal=patient', res.data)
        self.assertIn(b'/register?role=patient', res.data)

        self.assertIn(b'Pharmacy Network', res.data)
        self.assertIn(b'Pharmacy Log In', res.data)
        self.assertIn(b'/login?portal=pharmacy', res.data)
        self.assertIn(b'/register?role=pharmacy', res.data)

        # 3 Features with uploaded images
        self.assertIn(b'How MediConnect Protects &amp; Empowers You', res.data)
        self.assertIn(b'Private Relations', res.data)
        self.assertIn(b'private-relations.png', res.data)
        self.assertIn(b'Popup Automation', res.data)
        self.assertIn(b'popup-automation.png', res.data)
        self.assertIn(b'FIFO Expiry Alarms', res.data)
        self.assertIn(b'fifo-expiry-alarms.png', res.data)

        # Why Medi-Connect Section & Contact Info
        self.assertIn(b'Why Medi-Connect?', res.data)
        self.assertIn(b'mediconnectat@gmail.com', res.data)
        self.assertIn(b'mailto:mediconnectat@gmail.com', res.data)

        # Footer
        self.assertIn(b'Secure Healthcare Connectivity', res.data)

        # Ambient 4-Quadrant Blended Backgrounds
        self.assertIn(b'ambient-bg-canvas', res.data)
        self.assertIn(b'bg-panel-eprescription', res.data)
        self.assertIn(b'bg-panel-adherence', res.data)
        self.assertIn(b'bg-panel-pharmacy', res.data)
        self.assertIn(b'bg-panel-connectivity', res.data)

    def test_ambient_background_static_assets(self):
        # Verify all 4 background images are servable
        for img in ['bg-e-prescription.jpg', 'bg-patient-adherence.jpg', 'bg-pharmacy-stock.jpg', 'bg-medical-connectivity.jpg']:
            res = self.app.get(f'/static/img/{img}')
            self.assertEqual(res.status_code, 200, f"Failed to serve {img}")
            res.close()

if __name__ == '__main__':
    unittest.main()


