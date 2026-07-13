from datetime import datetime, date
import uuid
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

class User(db.Model):
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False)  # 'doctor', 'patient', 'pharmacy'
    name = db.Column(db.String(120), nullable=False)
    contact = db.Column(db.String(50), nullable=True)
    
    # Relationships
    prescriptions_written = db.relationship('Prescription', back_populates='doctor', foreign_keys='Prescription.doctor_id')
    prescriptions_received = db.relationship('Prescription', back_populates='patient', foreign_keys='Prescription.patient_id')
    broadcasts = db.relationship('Broadcast', back_populates='patient')
    offers = db.relationship('PharmacyOffer', back_populates='pharmacy')
    schedules = db.relationship('MedicationSchedule', back_populates='patient')
    inventory = db.relationship('InventoryItem', back_populates='pharmacy')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Prescription(db.Model):
    __tablename__ = 'prescriptions'
    
    id = db.Column(db.Integer, primary_key=True)
    uuid = db.Column(db.String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()))
    doctor_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    patient_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True) # Optional if patient hasn't registered yet
    patient_name = db.Column(db.String(120), nullable=False)
    patient_age = db.Column(db.Integer, nullable=True)
    patient_contact = db.Column(db.String(50), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    instructions = db.Column(db.Text, nullable=True)
    
    # Relationships
    doctor = db.relationship('User', back_populates='prescriptions_written', foreign_keys=[doctor_id])
    patient = db.relationship('User', back_populates='prescriptions_received', foreign_keys=[patient_id])
    items = db.relationship('PrescriptionItem', back_populates='prescription', cascade='all, delete-orphan')
    broadcasts = db.relationship('Broadcast', back_populates='prescription', cascade='all, delete-orphan')

class PrescriptionItem(db.Model):
    __tablename__ = 'prescription_items'
    
    id = db.Column(db.Integer, primary_key=True)
    prescription_id = db.Column(db.Integer, db.ForeignKey('prescriptions.id'), nullable=False)
    medicine_name = db.Column(db.String(120), nullable=False)
    dosage = db.Column(db.String(50), nullable=False)       # e.g., "1 tablet", "5ml"
    frequency = db.Column(db.String(100), nullable=False)    # e.g., "three times daily", "every 8 hours"
    duration = db.Column(db.String(50), nullable=False)      # e.g., "7 days", "1 month"
    instructions = db.Column(db.String(255), nullable=True)  # e.g., "before food"
    
    # Relationships
    prescription = db.relationship('Prescription', back_populates='items')

class Broadcast(db.Model):
    __tablename__ = 'broadcasts'
    
    id = db.Column(db.Integer, primary_key=True)
    prescription_id = db.Column(db.Integer, db.ForeignKey('prescriptions.id'), nullable=False)
    patient_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    status = db.Column(db.String(20), default='active')      # 'active', 'completed'
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    prescription = db.relationship('Prescription', back_populates='broadcasts')
    patient = db.relationship('User', back_populates='broadcasts')
    offers = db.relationship('PharmacyOffer', back_populates='broadcast', cascade='all, delete-orphan')

class PharmacyOffer(db.Model):
    __tablename__ = 'pharmacy_offers'
    
    id = db.Column(db.Integer, primary_key=True)
    broadcast_id = db.Column(db.Integer, db.ForeignKey('broadcasts.id'), nullable=False)
    pharmacy_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    estimated_price = db.Column(db.Float, nullable=False)
    availability_status = db.Column(db.String(20), nullable=False)  # 'available', 'partial', 'unavailable'
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    broadcast = db.relationship('Broadcast', back_populates='offers')
    pharmacy = db.relationship('User', back_populates='offers')

class MedicationSchedule(db.Model):
    __tablename__ = 'medication_schedules'
    
    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    medicine_name = db.Column(db.String(120), nullable=False)
    dosage = db.Column(db.String(50), nullable=False)
    frequency = db.Column(db.String(100), nullable=True)
    time_of_day = db.Column(db.String(100), nullable=False)    # comma-separated times, e.g. "08:00, 14:00, 20:00"
    start_date = db.Column(db.Date, nullable=False, default=date.today)
    end_date = db.Column(db.Date, nullable=False)
    refill_alert_threshold = db.Column(db.Integer, default=5) # Alert when stock falls below this
    current_stock = db.Column(db.Integer, default=0)
    
    # Relationships
    patient = db.relationship('User', back_populates='schedules')
    logs = db.relationship('TrackerLog', back_populates='schedule', cascade='all, delete-orphan')

class TrackerLog(db.Model):
    __tablename__ = 'tracker_logs'
    
    id = db.Column(db.Integer, primary_key=True)
    schedule_id = db.Column(db.Integer, db.ForeignKey('medication_schedules.id'), nullable=False)
    taken_at = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(20), default='taken') # 'taken', 'skipped'
    
    # Relationships
    schedule = db.relationship('MedicationSchedule', back_populates='logs')

class InventoryItem(db.Model):
    __tablename__ = 'inventory_items'
    
    id = db.Column(db.Integer, primary_key=True)
    pharmacy_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    medicine_name = db.Column(db.String(120), nullable=False)
    stock_level = db.Column(db.Integer, nullable=False, default=0)
    price = db.Column(db.Float, nullable=False)
    batch_number = db.Column(db.String(50), nullable=False)
    expiry_date = db.Column(db.Date, nullable=False)
    
    # Relationships
    pharmacy = db.relationship('User', back_populates='inventory')
    
    @property
    def is_expiring_soon(self):
        # Flag if expiring within 30 days
        diff = self.expiry_date - date.today()
        return diff.days <= 30
