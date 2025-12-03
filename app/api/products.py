import os
from flask import Blueprint, jsonify, request, abort, current_app
from app.services.product_service import ProductService
from app.services.price_service import PriceService

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

    created = result.get("created", []) or []
    for item in created:
        PriceService.add_product_to_all_price_lists(
            item["id"],
            default_price=item.get("price", 0) or 0,
        )

    return jsonify(result)
