from __future__ import annotations

from datetime import datetime
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class Account(db.Model):
    __tablename__ = "account"
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(128), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(32), default="student")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Interaction(db.Model):
    __tablename__ = "interaction"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("account.id"), nullable=False)

    prompt_text = db.Column(db.Text)
    prompt_time = db.Column(db.DateTime)

    feedback_text = db.Column(db.Text)
    feedback_summary = db.Column(db.Text)
    feedback_time = db.Column(db.DateTime)

    scores_json = db.Column(db.Text)  # writing rubric scores per category

    rating = db.Column(db.Integer)
    student_feedback_text = db.Column(db.Text)

    status = db.Column(db.String(32), default="final")  # draft/final
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class RubricVersion(db.Model):
    __tablename__ = "rubric_version"
    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_by = db.Column(db.Integer, db.ForeignKey("account.id"))
    rubric_json = db.Column(db.Text, nullable=False)
