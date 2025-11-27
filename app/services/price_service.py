from datetime import datetime
from app.models.price_list import PriceList
from app.models.price_item import PriceListItem
from app.models.product import Product
from app.database import db

class PriceService:

    @staticmethod
    def create_price_list(name, description, items):
        price_list = PriceList(
            name=name, 
            description=description,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        db.session.add(price_list)
        db.session.flush()  

        for product in items:
            db.session.add(PriceListItem(
                price_list_id=price_list.id,
                product_id=str(product["product_id"]), 
                price=product["price"],
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            ))

        db.session.commit()
        return price_list

    @staticmethod
    def get_all():
        return PriceList.query.all()

    @staticmethod
    def get_by_id(pl_id):
        return PriceList.query.filter_by(id=pl_id).first()

    @staticmethod
    def update(pl_id, name=None, description=None):
        price_list = PriceList.query.filter_by(id=pl_id).first()
        if not price_list:
            return None

        if name:
            price_list.name = name
        if description is not None:  
            price_list.description = description
        
        price_list.updated_at = datetime.utcnow() 

        db.session.commit()
        return price_list

    @staticmethod
    def delete(pl_id):
        price_list = PriceList.query.filter_by(id=pl_id).first()
        if not price_list:
            return None

        db.session.delete(price_list)
        db.session.commit()
        return True