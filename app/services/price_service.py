from datetime import datetime
from app.database import db
from app.models.price_list import PriceList
from app.models.price_list_item import PriceListItem
from app.models.product import Product


class PriceService:

    @staticmethod
    def create_price_list(name: str, description: str = "") -> PriceList:
        """Создание прайса + автоматическое добавление всех товаров."""
        new_pl = PriceList(name=name, description=description)
        db.session.add(new_pl)
        db.session.flush()  # получаем ID прайс-листа

        # Загружаем все товары из Product
        products = Product.query.all()

        items = [
            PriceListItem(
                price_list_id=new_pl.id,
                product_id=p.id,
                price=p.price or 0
            )
            for p in products
        ]

        db.session.add_all(items)
        db.session.commit()

        return new_pl

    @staticmethod
    def get_all() -> list:
        """Список всех прайсов."""
        return PriceList.query.order_by(PriceList.created_at.desc()).all()

    @staticmethod
    def get_by_id(price_list_id: int) -> PriceList:
        """Получить прайс по ID."""
        return PriceList.query.get(price_list_id)

    @staticmethod
    def update(price_list_id: int, name: str = None, description: str = None) -> PriceList:
        """Обновление названия / описания прайса."""
        pl = PriceList.query.get(price_list_id)
        if not pl:
            return None

        if name:
            pl.name = name
        if description is not None:
            pl.description = description

        pl.updated_at = datetime.utcnow()
        db.session.commit()
        return pl

    @staticmethod
    def delete(price_list_id: int) -> bool:
        """Удаление прайса."""
        pl = PriceList.query.get(price_list_id)
        if not pl:
            return False

        # Удаляем items
        PriceListItem.query.filter_by(price_list_id=price_list_id).delete()

        db.session.delete(pl)
        db.session.commit()
        return True

    @staticmethod
    def copy(price_list_id: int, new_name: str = None) -> PriceList:
        """Копировать прайс со всеми позициями."""
        original = PriceList.query.get(price_list_id)
        if not original:
            return None

        new_pl = PriceList(
            name=new_name or f"{original.name}_copy",
            description=original.description
        )

        db.session.add(new_pl)
        db.session.flush()  # нужен ID нового прайса

        # Копируем позиции
        original_items = PriceListItem.query.filter_by(price_list_id=price_list_id).all()

        items = [
            PriceListItem(
                price_list_id=new_pl.id,
                product_id=item.product_id,
                price=item.price
            )
            for item in original_items
        ]

        db.session.add_all(items)
        db.session.commit()

        return new_pl

    @staticmethod
    def get_price(product_id: str, price_list_id: int):
        """Получить цену из конкретного прайса для выбранного товара."""
        item = PriceListItem.query.filter_by(
            price_list_id=price_list_id,
            product_id=product_id
        ).first()
        return item.price if item else None
