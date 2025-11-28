# app/services/price_service.py
from datetime import datetime
from app.database import db
from app.models.price_list import PriceList
from app.models.price_item import PriceListItem  
from app.models.product import Product


class PriceService:
    @staticmethod
    def create_price_list(name: str, description: str = "") -> PriceList:
        
        new_pl = PriceList(name=name, description=description)
        db.session.add(new_pl)
        db.session.flush()  

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
    def get_all():
        return PriceList.query.order_by(PriceList.created_at.desc()).all()

    @staticmethod
    def get_by_id(price_list_id: int):
        return PriceList.query.get(price_list_id)

    @staticmethod
    def update(price_list_id: int, name: str = None, description: str = None):
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
        pl = PriceList.query.get(price_list_id)
        if not pl:
            return False

        PriceListItem.query.filter_by(price_list_id=price_list_id).delete()
        db.session.delete(pl)
        db.session.commit()
        return True

    @staticmethod
    def copy(price_list_id: int, new_name: str | None = None):
        original = PriceList.query.get(price_list_id)
        if not original:
            return None

        new_pl = PriceList(
            name=new_name or f"{original.name} (копия)",
            description=original.description,
        )
        db.session.add(new_pl)
        db.session.flush()

        original_items = PriceListItem.query.filter_by(price_list_id=price_list_id).all()
        items = [
            PriceListItem(
                price_list_id=new_pl.id,
                product_id=i.product_id,
                price=i.price
            )
            for i in original_items
        ]
        db.session.add_all(items)
        db.session.commit()
        return new_pl

    @staticmethod
    def get_price(product_id: str, price_list_id: int):
        item = PriceListItem.query.filter_by(
            price_list_id=price_list_id,
            product_id=product_id
        ).first()
        return item.price if item else None
