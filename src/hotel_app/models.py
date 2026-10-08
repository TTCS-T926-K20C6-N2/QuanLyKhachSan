"""Database models shared by Login and the future Register slice."""

from sqlalchemy import CheckConstraint, Index, text
from werkzeug.security import check_password_hash, generate_password_hash

from .extensions import db


def normalize_email(value: str | None) -> str:
    """Return the canonical account identifier defined by FR-AUTH-001."""

    return (value or "").strip().casefold()


class User(db.Model):
    """Persistent user account and personal profile."""

    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(254), nullable=False, unique=True)
    password_hash = db.Column(db.String(255), nullable=False)
    password_reset_version = db.Column(
        db.Integer, nullable=False, default=0, server_default="0"
    )
    full_name = db.Column(db.String(120), nullable=False, default="")
    birth_date = db.Column(db.Date, nullable=True)
    phone = db.Column(db.String(30), nullable=False, default="")
    avatar = db.Column(db.String(255), nullable=True)

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password, method="scrypt")

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)


class PasswordResetChallenge(db.Model):
    """One persisted OTP attempt and its one-use reset authorization."""

    __tablename__ = "password_reset_challenges"
    __table_args__ = (
        db.UniqueConstraint("user_id", "reset_version"),
        db.Index("ix_password_reset_user_created", "user_id", "created_at"),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    reset_version = db.Column(db.Integer, nullable=False)
    otp_digest = db.Column(db.String(64), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    failed_attempts = db.Column(db.Integer, nullable=False, default=0)
    delivery_status = db.Column(db.String(16), nullable=False, default="pending")
    verified_at = db.Column(db.DateTime, nullable=True)
    authorization_expires_at = db.Column(db.DateTime, nullable=True)
    consumed_at = db.Column(db.DateTime, nullable=True)


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


class RoomRental(db.Model):
    """A persisted rental transaction with its price and duration snapshot."""

    __tablename__ = "room_rentals"

    id = db.Column(db.Integer, primary_key=True)
    room_id = db.Column(
        db.Integer, db.ForeignKey("rooms.id", ondelete="SET NULL"), nullable=True
    )
    room_number = db.Column(db.String(20), nullable=False)
    rented_at = db.Column(db.DateTime, nullable=False)
    expected_checkout = db.Column(db.DateTime, nullable=False)
    duration_minutes = db.Column(db.Integer, nullable=False)
    nightly_rate = db.Column(db.Integer, nullable=False)
    total_price = db.Column(db.Integer, nullable=False)


class RoomReservation(db.Model):
    """A future room schedule with an immutable-at-booking price snapshot."""

    __tablename__ = "room_reservations"
    __table_args__ = (
        db.Index("ix_room_reservations_room_status_from", "room_id", "status", "reserved_from"),
        db.Index("ix_room_reservations_status_from", "status", "reserved_from"),
    )

    id = db.Column(db.Integer, primary_key=True)
    room_id = db.Column(
        db.Integer, db.ForeignKey("rooms.id", ondelete="SET NULL"), nullable=True
    )
    room_number = db.Column(db.String(20), nullable=False)
    guest_name = db.Column(db.String(120), nullable=False)
    guest_phone = db.Column(db.String(30), nullable=False)
    reserved_from = db.Column(db.DateTime, nullable=False)
    reserved_until = db.Column(db.DateTime, nullable=False)
    duration_minutes = db.Column(db.Integer, nullable=False)
    nightly_rate = db.Column(db.Integer, nullable=False)
    total_price = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(16), nullable=False, default="booked", server_default="booked")
    created_at = db.Column(db.DateTime, nullable=False)


class RoomServiceLog(db.Model):
    """An auditable cleaning or maintenance period for one room."""

    __tablename__ = "room_service_logs"
    __table_args__ = (
        CheckConstraint(
            "service_type IN ('cleaning', 'maintenance')",
            name="ck_room_service_logs_type",
        ),
        CheckConstraint(
            "ended_at IS NULL OR ended_at >= started_at",
            name="ck_room_service_logs_period",
        ),
        Index(
            "uq_room_service_logs_one_active_per_room",
            "room_id",
            unique=True,
            sqlite_where=text("ended_at IS NULL AND room_id IS NOT NULL"),
        ),
        Index("ix_room_service_logs_room_started", "room_id", "started_at"),
    )

    id = db.Column(db.Integer, primary_key=True)
    room_id = db.Column(
        db.Integer, db.ForeignKey("rooms.id", ondelete="SET NULL"), nullable=True
    )
    room_number = db.Column(db.String(20), nullable=False)
    service_type = db.Column(db.String(16), nullable=False)
    started_at = db.Column(db.DateTime, nullable=False)
    ended_at = db.Column(db.DateTime, nullable=True)
    note = db.Column(db.Text, nullable=True)


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
