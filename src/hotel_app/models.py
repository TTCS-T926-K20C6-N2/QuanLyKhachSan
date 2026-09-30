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


# Model lưu thông tin phòng cho SCRUM-23
class Room(db.Model):
    __tablename__ = 'rooms'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)   # Tên hoặc số phòng (ví dụ: Phòng 101)
    price = db.Column(db.Float, nullable=False)        # Giá thuê (VNĐ)
    area = db.Column(db.Float, nullable=True)           # Diện tích (m²)
    description = db.Column(db.Text, nullable=True)    # Mô tả phòng

    def __repr__(self):
        return f'<Room {self.name}>'