import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY = os.getenv("SECRET_KEY") or "dev-secret-key-123"
    MONGO_URI = os.getenv("MONGO_URI") or "mongodb://localhost:27017/"
    DB_NAME = os.getenv("SECRET_KEY")
    PEO_API_KEY = os.getenv("PEO_API_KEY")
    PEO_BASE_URL = os.getenv("PEO_BASE_URL")

    MAIL_SERVER = os.getenv("MAIL_SERVER")
    MAIL_PORT = os.getenv("MAIL_PORT")
    MAIL_USE_TLS = True
    MAIL_USERNAME = os.getenv("MAIL_USERNAME")
    MAIL_PASSWORD = os.getenv("MAIL_PASSWORD")
    MAIL_DEFAULT_SENDER = os.getenv("MAIL_DEFAULT_SENDER")

    SECURITY_PASSWORD_SALT = os.getenv("SECURITY_PASSWORD_SALT")
