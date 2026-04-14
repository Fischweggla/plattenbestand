import os
from dotenv import load_dotenv

load_dotenv()

basedir = os.path.abspath(os.path.dirname(__file__))

DB_URL = os.environ.get(
    'DATABASE_URL',
    'postgresql://plattenbestand:plattenbestand@localhost:5432/plattenbestand'
)


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'ibe-plattenbestand-change-in-production')
    SQLALCHEMY_DATABASE_URI = DB_URL
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    MAX_CONTENT_LENGTH = 50 * 1024 * 1024  # 50 MB

    # Pool-Optionen nur für PostgreSQL
    if DB_URL.startswith('postgresql'):
        SQLALCHEMY_ENGINE_OPTIONS = {
            'pool_size': 5,
            'pool_recycle': 300,
            'pool_pre_ping': True,
        }
