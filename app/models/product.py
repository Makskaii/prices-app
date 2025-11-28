from app.database import db

class Product(db.Model):
    __tablename__ = "products"

    id = db.Column(db.String(50), primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    price = db.Column(db.Numeric(12,2))
    currency_id = db.Column(db.String, nullable=True)
    description = db.Column(db.Text, nullable=True)

    def __repr__(self):
        return f"<Product {self.id} - {self.name}>"