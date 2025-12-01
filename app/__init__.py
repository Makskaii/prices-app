from flask import Flask, render_template
from .config import load_config
from .database import db, migrate

def create_app():
    app = Flask(__name__)
    
    load_config(app)

    db.init_app(app)
    migrate.init_app(app, db)

    from app.api.prices import prices_bp
    from app.api.products import products_bp

    app.register_blueprint(prices_bp, url_prefix="/api/prices")
    app.register_blueprint(products_bp, url_prefix="/api/products")

    @app.route("/", methods=["GET", "POST"])
    def index():
        return render_template("index.html")

    return app
