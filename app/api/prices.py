from flask import Blueprint, request, jsonify
from app.services.price_service import PriceService

prices_bp = Blueprint("prices", __name__)

@prices_bp.get("/")
def get_prices():
    prices = PriceService.get_all()
    return jsonify([
        {
            "id": p.id,
            "name": p.name,
            "description": p.description,
            "created_at": p.created_at.isoformat()
        }
        for p in prices
    ])

@prices_bp.post("/")
def create_price():
    data = request.json
    name = data.get("name")
    description = data.get("description")
    items = data.get("items", [])  # [{product_id, price}]

    price_list = PriceService.create_price_list(name, description, items)
    return jsonify({"id": price_list.id}), 201

@prices_bp.get("/<int:pl_id>")
def get_price(pl_id):
    price_list = PriceService.get_by_id(pl_id)
    if not price_list:
        return jsonify({"error": "Not found"}), 404

    return jsonify({
        "id": price_list.id,
        "name": price_list.name,
        "description": price_list.description,
        "items": [
            {"id": i.id, "product_id": i.product_id, "price": float(i.price)}
            for i in price_list.items
        ]
    })

@prices_bp.put("/<int:pl_id>")
def update_price(pl_id):
    data = request.json
    name = data.get("name")
    description = data.get("description")

    price_list = PriceService.update(pl_id, name, description)
    if not price_list:
        return jsonify({"error": "Not found"}), 404

    return jsonify({"status": "updated"})

@prices_bp.delete("/<int:pl_id>")
def delete_price(pl_id):
    ok = PriceService.delete(pl_id)
    if not ok:
        return jsonify({"error": "Not found"}), 404

    return jsonify({"status": "deleted"})
