from app import db

class Product(db.Model):
    __tablename__ = "products"

    id = db.Column(db.String(50), primary_key=True)  # ID из Bitrix24
    name = db.Column(db.String(255), nullable=False)
    price = db.Column(db.Numeric(12,2))  # базовая цена, если нужна
    currency_id = db.Column(db.String(10))

    def __repr__(self):
        return f"<Product {self.id} - {self.name}>"