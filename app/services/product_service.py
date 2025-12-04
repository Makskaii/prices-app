from app.database import db
from app.models.product import Product
from app.models.price_list import PriceList
from app.models.price_item import PriceListItem
from app.services.bitrix_api import bitrix_call_paginated


class ProductService:

    @staticmethod
    def fetch_products_from_bitrix():
        
        return bitrix_call_paginated("crm.product.list", {
            "select": ["ID", "NAME", "PRICE", "DESCRIPTION", "CURRENCY_ID"]
        })

    @staticmethod
    def sync_products_from_bitrix():
        
        bitrix_products = ProductService.fetch_products_from_bitrix() or []

        
        existing_products = {p.id: p for p in Product.query.all()}

        bitrix_ids = set()
        created_for_response = []
        updated_count = 0

        for bp in bitrix_products:
            product_id = str(bp.get("ID"))
            bitrix_ids.add(product_id)

            name = (bp.get("NAME") or "").strip()
            price = bp.get("PRICE") or 0
            description = bp.get("DESCRIPTION") or ""
            currency_id = bp.get("CURRENCY_ID")

            if product_id in existing_products:
                
                p = existing_products[product_id]
                changed = False

                if p.name != name:
                    p.name = name
                    changed = True
                if p.price != price:
                    p.price = price
                    changed = True
                if p.description != description:
                    p.description = description
                    changed = True
                if p.currency_id != currency_id:
                    p.currency_id = currency_id
                    changed = True

                if changed:
                    updated_count += 1
            else:
                
                p = Product(
                    id=product_id,
                    name=name or f"Товар {product_id}",
                    price=price,
                    description=description,
                    currency_id=currency_id,
                )
                db.session.add(p)
                created_for_response.append({
                    "id": product_id,
                    "price": float(price) if price is not None else 0,
                })

        
        ids_to_delete = [pid for pid in existing_products.keys() if pid not in bitrix_ids]

        deleted_count = 0
        if ids_to_delete:
            
            PriceListItem.query.filter(
                PriceListItem.product_id.in_(ids_to_delete)
            ).delete(synchronize_session=False)

            
            Product.query.filter(
                Product.id.in_(ids_to_delete)
            ).delete(synchronize_session=False)

            deleted_count = len(ids_to_delete)

        db.session.commit()

        return {
            "total": len(bitrix_products),
            "new": len(created_for_response),
            "updated": updated_count,
            "deleted": deleted_count,
            
            "created": created_for_response,
        }

    @staticmethod
    def get_all_products():
        return Product.query.order_by(Product.name.asc()).all()
