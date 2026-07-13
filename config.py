import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'mediconnect-secret-key-12345')
    
    # Use absolute path for SQLite to prevent directory shifting issues
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        'DATABASE_URL', 
        'sqlite:///' + os.path.join(BASE_DIR, 'mediconnect.db')
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
