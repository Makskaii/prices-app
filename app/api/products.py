from flask import Blueprint, jsonify

products_bp = Blueprint("products", __name__)

@products_bp.get("/")
def get_products():
    return jsonify({"products": []})
