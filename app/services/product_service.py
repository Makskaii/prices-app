from app.database import db
from app.models.product import Product
from app.models.price_list import PriceList
from app.models.price_list_item import PriceListItem
from app.services.bitrix_api import bitrix_call_paginated


class ProductService:
    
    @staticmethod
    def fetch_products_from_bitrix():

        return bitrix_call_paginated("crm.product.list", {
            "select": ["ID", "NAME", "PRICE", "DESCRIPTION", "CURRENCY_ID"]
        })

    @staticmethod
    def sync_products_from_bitrix():
        
        bitrix_products = ProductService.fetch_products_from_bitrix()

        existing_products = {p.id: p for p in Product.query.all()}
        new_products = []

        for p in bitrix_products:
            pid = str(p["ID"])

            if pid in existing_products:
                prod = existing_products[pid]
                prod.name = p["NAME"]
                prod.price = p.get("PRICE") or 0
                prod.currency_id = p.get("CURRENCY_ID") or "RUB"
                prod.description = p.get("DESCRIPTION") or ""
            else:
                prod = Product(
                    id=pid,
                    name=p["NAME"],
                    price=p.get("PRICE") or 0,
                    currency_id=p.get("CURRENCY_ID") or "RUB",
                    description=p.get("DESCRIPTION") or ""
                )
                db.session.add(prod)
                new_products.append(prod)

        db.session.commit()

        if new_products:
            price_lists = PriceList.query.all()
            items_to_add = []

            for pl in price_lists:
                for p in new_products:
                    items_to_add.append(PriceListItem(
                        price_list_id=pl.id,
                        product_id=p.id,
                        price=p.price
                    ))

            db.session.add_all(items_to_add)
            db.session.commit()

        return {
            "total": len(bitrix_products),
            "new": len(new_products),
            "updated": len(bitrix_products) - len(new_products)
        }

    @staticmethod
    def get_all_products():
        return Product.query.order_by(Product.name.asc()).all()
