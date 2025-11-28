from flask import Blueprint, request, jsonify

from app.database import db
from app.models.price_list import PriceList
from app.models.price_list_item import PriceListItem
from app.services.price_service import PriceService

prices_bp = Blueprint("prices_bp", __name__)


# ----------------------------------------------------------------------
# 1. Список прайсов
# ----------------------------------------------------------------------
@prices_bp.route("/", methods=["GET"])
def list_price_lists():
    """
    Получить список всех прайс-листов.
    """
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


# ----------------------------------------------------------------------
# 2. Создание прайса
# ----------------------------------------------------------------------
@prices_bp.route("/", methods=["POST"])
def create_price_list():
    """
    Создать новый прайс-лист.

    JSON:
    {
      "name": "Прайс Апрель 2025",
      "description": "Спецусловия"
    }

    При создании:
    - Прайс создаётся
    - В него автоматически добавляются ВСЕ товары из каталога (PriceListItem)
    """
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


# ----------------------------------------------------------------------
# 3. Получение одного прайс-листа с позициями
# ----------------------------------------------------------------------
@prices_bp.route("/<int:pl_id>", methods=["GET"])
def get_price_list(pl_id):
    """
    Получить один прайс-лист + все его позиции.
    """
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


# ----------------------------------------------------------------------
# 4. Редактирование прайса (название/описание)
# ----------------------------------------------------------------------
@prices_bp.route("/<int:pl_id>", methods=["PUT"])
def update_price_list(pl_id):
    """
    Обновить название и/или описание прайс-листа.

    JSON:
    {
      "name": "Новое имя",
      "description": "Новое описание"
    }
    """
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


# ----------------------------------------------------------------------
# 5. Удаление прайс-листа
# ----------------------------------------------------------------------
@prices_bp.route("/<int:pl_id>", methods=["DELETE"])
def delete_price_list(pl_id):
    """
    Удалить прайс-лист и все его позиции.
    """
    ok = PriceService.delete(pl_id)
    if not ok:
        return jsonify({"error": "not found"}), 404

    return jsonify({"status": "deleted"})


# ----------------------------------------------------------------------
# 6. Копирование прайс-листа
# ----------------------------------------------------------------------
@prices_bp.route("/<int:pl_id>/copy", methods=["POST"])
def copy_price_list(pl_id):
    """
    Копировать прайс-лист со всеми позициями.

    JSON (необязательно):
    {
      "name": "Новое имя прайса"
    }
    """
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


# ----------------------------------------------------------------------
# 7. Получить цену товара по прайсу
# ----------------------------------------------------------------------
@prices_bp.route("/<int:pl_id>/price", methods=["GET"])
def get_product_price(pl_id):
    """
    Вернуть цену товара в рамках конкретного прайс-листа.

    /api/prices/<id>/price?product_id=123
    """
    product_id = request.args.get("product_id")
    if not product_id:
        return jsonify({"error": "product_id is required"}), 400

    price = PriceService.get_price(product_id=product_id, price_list_id=pl_id)

    return jsonify({
        "product_id": product_id,
        "price": float(price) if price is not None else None
    })


# ----------------------------------------------------------------------
# 8. Редактирование цены конкретного товара в прайсе
# ----------------------------------------------------------------------
@prices_bp.route("/<int:pl_id>/items/<product_id>", methods=["PUT"])
def update_price_item(pl_id, product_id):
    """
    Обновить цену конкретного товара в конкретном прайсе.

    JSON:
    {
      "price": 12345.67
    }
    """
    data = request.get_json() or {}
    if "price" not in data:
        return jsonify({"error": "price is required"}), 400

    new_price = data["price"]

    item = PriceListItem.query.filter_by(
        price_list_id=pl_id,
        product_id=product_id
    ).first()

    if not item:
        # Если записи нет — создадим (на случай, если расхождение с ТЗ/данными)
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