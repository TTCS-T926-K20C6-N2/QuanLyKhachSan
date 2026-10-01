"""Database models shared by Login and the future Register slice."""

from werkzeug.security import check_password_hash, generate_password_hash

from .extensions import db


def normalize_email(value: str | None) -> str:
    """Return the canonical account identifier defined by FR-AUTH-001."""

    return (value or "").strip().casefold()


class User(db.Model):
    """Minimal persistent user required for authentication."""

    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(254), nullable=False, unique=True)
    password_hash = db.Column(db.String(255), nullable=False)

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password, method="scrypt")

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)


class RoomType(db.Model):
    """A hotel room category shown in the room type catalog."""

    __tablename__ = "room_types"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False, unique=True)
    price = db.Column(db.String(40), nullable=False)
    capacity = db.Column(db.String(40), nullable=False)
    description = db.Column(db.String(255), nullable=False)


class Room(db.Model):
    """A room shown on the hotel floor map."""

    __tablename__ = "rooms"

    id = db.Column(db.Integer, primary_key=True)
    number = db.Column(db.String(10), nullable=False, unique=True)
    floor = db.Column(db.String(40), nullable=False)
    type = db.Column(db.String(80), nullable=False)
    status = db.Column(db.String(80), nullable=False)
    state = db.Column(db.String(20), nullable=False)

