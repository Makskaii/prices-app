from flask import Flask
from .config import load_config
from .database import db, migrate

def create_app():
    app = Flask(__name__)
    
    # Загружаем конфиг из .env
    load_config(app)

    # Инициализируем БД
    db.init_app(app)
    migrate.init_app(app, db)

    # Регистрируем blueprints (API-модули)
    from app.api.prices import prices_bp
    from app.api.products import products_bp

    app.register_blueprint(prices_bp, url_prefix="/api/prices")
    app.register_blueprint(products_bp, url_prefix="/api/products")

    return app
