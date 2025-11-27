from datetime import datetime
from app.database import db

class PriceList(db.Model):
    __tablename__ = "price_lists"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False, unique=True)
    description = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    items = db.relationship("PriceListItem", back_populates="price_list", cascade="all, delete-orphan")