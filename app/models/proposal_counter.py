# app/models/proposal_counter.py
from app.database import db


class ProposalCounter(db.Model):
    __tablename__ = "proposal_counters"

    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.String(32), unique=True, nullable=False)
    counter = db.Column(db.Integer, nullable=False, default=0)
