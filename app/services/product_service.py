from app.models.product import Product
from app import db
from app.bitrix_api import bitrix_call

def fetch_products_from_bitrix():
    all_products = []
    start = 0

    while True:
        resp = bitrix_call("crm.product.list", {"start": start})

        result = resp.get("result", [])
        all_products.extend(result)

        if "next" not in resp:
            break

        start = resp["next"]

    return all_products

def sync_products_to_db():
    products = fetch_products_from_bitrix()

    for p in products:
        existing = Product.query.get(p["ID"])

        if existing:
            existing.name = p["NAME"]
            existing.price = p.get("PRICE")
            existing.currency_id = p.get("CURRENCY_ID")
        else:
            new_product = Product(
                id=p["ID"],
                name=p["NAME"],
                price=p.get("PRICE"),
                currency_id=p.get("CURRENCY_ID")
            )
            db.session.add(new_product)

    db.session.commit()

    return len(products)
