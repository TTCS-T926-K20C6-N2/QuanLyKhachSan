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
    """Persistent catalog entry for an editable room type."""

    __tablename__ = "room_types"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False, unique=True)
    price = db.Column(db.Integer, nullable=False)
    quantity = db.Column(db.Integer, nullable=False, default=0)
    capacity = db.Column(db.String(40), nullable=False, default="")
    description = db.Column(db.Text, nullable=False, default="")
    status = db.Column(db.String(16), nullable=False, default="active")


class RoomTypeSeedState(db.Model):
    """Persist whether the initial room type catalog has been seeded."""

    __tablename__ = "room_type_seed_state"

    id = db.Column(db.Integer, primary_key=True)
    initialized = db.Column(db.Boolean, nullable=False, default=False)


class Room(db.Model):
    """Persistent room record shared across authenticated sessions."""

    __tablename__ = "rooms"

    id = db.Column(db.Integer, primary_key=True)
    number = db.Column(db.String(20, collation="NOCASE"), nullable=False, unique=True)
    floor = db.Column(db.String(80), nullable=False)
    position = db.Column(db.Integer, nullable=False, default=0)
    type = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text, nullable=False, default="")
    price = db.Column(db.Integer, nullable=False, default=0)
    image = db.Column(db.String(255), nullable=True)
    status = db.Column(db.String(32), nullable=False, default="Phòng trống")
    state = db.Column(db.String(24), nullable=False, default="empty")
    check_in = db.Column(db.String(5), nullable=True)
    check_out = db.Column(db.String(5), nullable=True)
    is_demo = db.Column(db.Boolean, nullable=False, default=False)


class RoomSeedState(db.Model):
    """Records one-time room seeding so deleted demos do not return."""

    __tablename__ = "room_seed_state"

    id = db.Column(db.Integer, primary_key=True)
    initialized = db.Column(db.Boolean, nullable=False, default=False)


class LegacyRoomSessionMigration(db.Model):
    """Records the one-time import of a pre-database room session."""

    __tablename__ = "legacy_room_session_migration"

    id = db.Column(db.Integer, primary_key=True)
    completed = db.Column(db.Boolean, nullable=False, default=False)

