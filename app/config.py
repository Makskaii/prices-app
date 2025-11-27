import os
from dotenv import load_dotenv

def load_config(app):
    load_dotenv()

    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY")
    app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL")
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["BITRIX_WEBHOOK_URL"] = os.getenv("BITRIX_WEBHOOK_URL")