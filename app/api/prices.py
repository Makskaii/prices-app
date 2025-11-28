from flask import Blueprint, request, jsonify

from app.database import db
from app.models.price_list import PriceList
from app.models.price_list_item import PriceListItem
from app.services.price_service import PriceService

prices_bp = Blueprint("prices_bp", __name__)

@prices_bp.route("/", methods=["GET"])
def list_price_lists():
    price_lists = PriceService.get_all()

    data = []
    for pl in price_lists:
        data.append({
            "id": pl.id,
            "name": pl.name,
            "description": pl.description,
            "created_at": pl.created_at.isoformat() if pl.created_at else None,
            "updated_at": pl.updated_at.isoformat() if pl.updated_at else None,
            "items_count": len(pl.items) if hasattr(pl, "items") else None,
        })

    return jsonify(data)

@prices_bp.route("/", methods=["POST"])
def create_price_list():
    
    data = request.get_json() or {}
    name = data.get("name")
    description = data.get("description", "")

    if not name:
        return jsonify({"error": "name is required"}), 400

    pl = PriceService.create_price_list(name=name, description=description)

    return jsonify({
        "id": pl.id,
        "name": pl.name,
        "description": pl.description
    }), 201



@prices_bp.route("/<int:pl_id>", methods=["GET"])
def get_price_list(pl_id):
    
    pl = PriceService.get_by_id(pl_id)
    if not pl:
        return jsonify({"error": "not found"}), 404

    return jsonify({
        "id": pl.id,
        "name": pl.name,
        "description": pl.description,
        "created_at": pl.created_at.isoformat() if pl.created_at else None,
        "updated_at": pl.updated_at.isoformat() if pl.updated_at else None,
        "items": [
            {
                "product_id": item.product_id,
                "price": float(item.price) if item.price is not None else None
            }
            for item in pl.items
        ]
    })



@prices_bp.route("/<int:pl_id>", methods=["PUT"])
def update_price_list(pl_id):
    
    data = request.get_json() or {}
    name = data.get("name")
    description = data.get("description")

    pl = PriceService.update(
        price_list_id=pl_id,
        name=name,
        description=description
    )

    if not pl:
        return jsonify({"error": "not found"}), 404

    return jsonify({
        "id": pl.id,
        "name": pl.name,
        "description": pl.description
    })



@prices_bp.route("/<int:pl_id>", methods=["DELETE"])
def delete_price_list(pl_id):
    
    ok = PriceService.delete(pl_id)
    if not ok:
        return jsonify({"error": "not found"}), 404

    return jsonify({"status": "deleted"})



@prices_bp.route("/<int:pl_id>/copy", methods=["POST"])
def copy_price_list(pl_id):
    
    data = request.get_json() or {}
    new_name = data.get("name")

    new_pl = PriceService.copy(pl_id, new_name=new_name)
    if not new_pl:
        return jsonify({"error": "not found"}), 404

    return jsonify({
        "id": new_pl.id,
        "name": new_pl.name,
        "description": new_pl.description
    }), 201



@prices_bp.route("/<int:pl_id>/price", methods=["GET"])
def get_product_price(pl_id):
    
    product_id = request.args.get("product_id")
    if not product_id:
        return jsonify({"error": "product_id is required"}), 400

    price = PriceService.get_price(product_id=product_id, price_list_id=pl_id)

    return jsonify({
        "product_id": product_id,
        "price": float(price) if price is not None else None
    })



@prices_bp.route("/<int:pl_id>/items/<product_id>", methods=["PUT"])
def update_price_item(pl_id, product_id):
    
    data = request.get_json() or {}
    if "price" not in data:
        return jsonify({"error": "price is required"}), 400

    new_price = data["price"]

    item = PriceListItem.query.filter_by(
        price_list_id=pl_id,
        product_id=product_id
    ).first()

    if not item:
        item = PriceListItem(
            price_list_id=pl_id,
            product_id=product_id,
            price=new_price
        )
        db.session.add(item)
    else:
        item.price = new_price

    db.session.commit()

    return jsonify({
        "price_list_id": pl_id,
        "product_id": product_id,
        "price": float(item.price)
    })