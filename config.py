import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    SERVER_NAME = "umpteenth-nonconjugally-jina.ngrok-free.dev"
    SECRET_KEY = os.getenv("SECRET_KEY")
    MONGO_URI = os.getenv("MONGO_URI")
    DB_NAME = "interview_bridge"
    PEO_API_KEY = os.getenv("PEO_API_KEY")
    PEO_BASE_URL = os.getenv("PEO_BASE_URL")
    MAIL_SERVER = "smtp.gmail.com"
    MAIL_PORT = 587
    MAIL_USE_TLS = True
    MAIL_USERNAME = "sshourya948@gmail.com"
    MAIL_PASSWORD = "rckhpvxddzpzrdtk"
    MAIL_DEFAULT_SENDER = "Interview Bridge <sshourya948@gmail.com>"
    SECURITY_PASSWORD_SALT = "reset-salt-key"

