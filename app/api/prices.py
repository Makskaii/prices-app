from flask import Blueprint, request, jsonify

from app.database import db
from app.models.price_item import PriceListItem
from app.models.price_list import PriceList
from app.models.product import Product
from app.services.price_service import PriceService
from sqlalchemy import and_

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
            
            "items_count": getattr(pl, "items_count", len(pl.items) if hasattr(pl, "items") else None),
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
        "description": pl.description,
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
                "price": float(item.price) if item.price is not None else None,
            }
            for item in pl.items
        ]
    })


@prices_bp.route("/<int:pl_id>", methods=["PUT"])
def update_price_list(pl_id):
    data = request.get_json() or {}
    name = data.get("name")
    description = data.get("description")

    pl = PriceService.update(price_list_id=pl_id, name=name, description=description)
    if not pl:
        return jsonify({"error": "not found"}), 404

    return jsonify({
        "id": pl.id,
        "name": pl.name,
        "description": pl.description,
    })


@prices_bp.route("/<int:pl_id>", methods=["DELETE"])
def delete_price_list(pl_id):
    ok = PriceService.delete(pl_id)
    if not ok:
        return jsonify({"error": "not found"}), 404

    return jsonify({"status": "deleted"})


@prices_bp.route("/<int:pl_id>/copy", methods=["POST"])
def copy_price_list(pl_id):
    data = request.get_json(silent=True) or {}
    new_name = data.get("name")

    new_pl = PriceService.copy(pl_id, new_name=new_name)
    if not new_pl:
        return jsonify({"error": "not found"}), 404

    return jsonify({
        "id": new_pl.id,
        "name": new_pl.name,
        "description": new_pl.description,
    }), 201


@prices_bp.route("/<int:pl_id>/price", methods=["GET"])
def get_product_price(pl_id):
    product_id = request.args.get("product_id")
    if not product_id:
        return jsonify({"error": "product_id is required"}), 400

    price = PriceService.get_price(product_id=product_id, price_list_id=pl_id)

    return jsonify({
        "product_id": product_id,
        "price": float(price) if price is not None else None,
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
        "price": float(item.price),
    })


@prices_bp.route("/<int:pl_id>/items", methods=["GET"])
def get_price_list_items(pl_id):
    pl = PriceList.query.get(pl_id)
    if not pl:
        return jsonify({"error": "not found"}), 404

    rows = (
        db.session.query(
            Product.id.label("product_id"),
            Product.name.label("product_name"),
            Product.description.label("product_description"),
            PriceListItem.price,
        )
        .outerjoin(
            PriceListItem,
            and_(
                PriceListItem.product_id == Product.id,
                PriceListItem.price_list_id == pl_id,
            ),
        )
        .order_by(Product.name.asc())
        .all()
    )

    result = []
    for r in rows:
        result.append({
            "product_id": r.product_id,
            "product_name": r.product_name,
            "product_description": r.product_description,
            "price": float(r.price) if r.price is not None else None,
        })

    return jsonify(result)


@prices_bp.route("/<int:pl_id>/items", methods=["PUT"])
def bulk_update_price_list_items(pl_id):
    pl = PriceList.query.get(pl_id)
    if not pl:
        return jsonify({"error": "not found"}), 404

    payload = request.get_json() or {}
    items = payload.get("items", [])

    
    PriceListItem.query.filter_by(price_list_id=pl_id).delete()

    new_items = []
    for item in items:
        product_id = item.get("product_id")
        if not product_id:
            continue

        try:
            product_id_int = int(product_id)
        except (TypeError, ValueError):
            continue

        price = item.get("price", 0)

        new_items.append(
            PriceListItem(
                price_list_id=pl_id,
                product_id=product_id_int,
                price=price,
            )
        )

    if new_items:
        db.session.add_all(new_items)

    
    pl.items_count = len(new_items)

    db.session.commit()

    return jsonify({
        "status": "ok",
        "items_count": len(new_items),
    })


@prices_bp.route("/sync-product/<int:product_id>", methods=["POST"])
def sync_product_to_all_price_lists(product_id):
    
    product = Product.query.get(product_id)
    if not product:
        return jsonify({"error": "product not found"}), 404

    PriceService.add_product_to_all_price_lists(
        product_id=product.id,
        default_price=product.price or 0
    )

    return jsonify({"status": "ok", "product_id": product.id})
