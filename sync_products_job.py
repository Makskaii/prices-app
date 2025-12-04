import sys
import os

APP_DIR = "/root/geotek/Prices"
sys.path.append(APP_DIR)

from dotenv import load_dotenv
load_dotenv(os.path.join(APP_DIR, ".env"))

from app import create_app
from app.services.product_service import ProductService

flask_app = create_app()
with flask_app.app_context():
    result = ProductService.sync_products_from_bitrix()
    print("Sync result:", result)