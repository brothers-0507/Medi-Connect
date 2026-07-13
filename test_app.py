import unittest
from datetime import date, timedelta
from app import app, db, User, Prescription, PrescriptionItem, Broadcast, PharmacyOffer, MedicationSchedule, TrackerLog, InventoryItem

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
            
            self.pat = User(username='test_patient', name='Patient Test', role='patient', contact='555-9988')
            self.pat.set_password('password')
            
            self.ph = User(username='test_pharmacy', name='Pharmacy Test', role='pharmacy', contact='ph@test.com')
            self.ph.set_password('password')
            
            db.session.add(self.doc)
            db.session.add(self.pat)
            db.session.add(self.ph)
            db.session.commit()
            
            # Save IDs for reference
            self.doc_id = self.doc.id
            self.pat_id = self.pat.id
            self.ph_id = self.ph.id

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
            contact='111-2222'
        ), follow_redirects=True)
        
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Registration successful!', response.data)
        
        with app.app_context():
            user = User.query.filter_by(username='new_user').first()
            self.assertIsNotNone(user)
            self.assertEqual(user.name, 'New Person')
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

if __name__ == '__main__':
    unittest.main()
