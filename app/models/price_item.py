from datetime import datetime
from app.database import db

class PriceListItem(db.Model):
    __tablename__ = "price_list_items"

    id = db.Column(db.Integer, primary_key=True)
    price_list_id = db.Column(db.Integer, db.ForeignKey("price_lists.id"), nullable=False)
    product_id = db.Column(db.String(50), nullable=False)
    price = db.Column(db.Numeric(12, 2), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    price_list = db.relationship("PriceList", back_populates="items")

    __table_args__ = (
        db.UniqueConstraint('price_list_id', 'product_id', name='unique_product_in_price_list'),
    )