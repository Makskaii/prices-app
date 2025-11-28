from flask import Blueprint, jsonify, request
from app.services.product_service import ProductService

products_bp = Blueprint("products_bp", __name__)


@products_bp.route("/", methods=["GET"])
def list_products():
    
    q = request.args.get("q", "").strip()
    products = ProductService.get_all_products()

    if q:
        q_lower = q.lower()
        products = [p for p in products if p.name and q_lower in p.name.lower()]

    return jsonify([
        {
            "id": p.id,
            "name": p.name,
            "price": float(p.price) if p.price is not None else None,
            "currency": p.currency_id,
            "description": getattr(p, "description", ""),
        }
        for p in products
    ])


@products_bp.route("/sync", methods=["POST"])
def sync_products():
    
    result = ProductService.sync_products_from_bitrix()
    return jsonify(result)
