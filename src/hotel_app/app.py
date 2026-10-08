"""Minimal Flask application for SCRUM-21 / PB-01 Login."""

from __future__ import annotations

import os
import re
import secrets
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any

from flask import Flask, flash, redirect, render_template, request, send_from_directory, session, url_for
from flask_wtf.csrf import CSRFError
from sqlalchemy import inspect, text, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from werkzeug.utils import secure_filename

from .auth_recovery import (
    generate_otp,
    otp_digest,
    otp_matches,
    send_password_reset_otp,
)
from .extensions import csrf, db
from .models import (
    LegacyRoomSessionMigration,
    Room,
    RoomRental,
    RoomReservation,
    RoomServiceLog,
    RoomSeedState,
    RoomType,
    RoomTypeSeedState,
    PasswordResetChallenge,
    User,
    normalize_email,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CLEANING_BUFFER_MINUTES = 60
CHECKOUT_CLEANING_LOG_NOTE = "__checkout__"
INSTANCE_PATH = PROJECT_ROOT / "instance"
INVALID_CREDENTIAL_MESSAGE = "Email hoặc mật khẩu không đúng"
REGISTER_SUCCESS_MESSAGE = "Tạo tài khoản thành công. Vui lòng đăng nhập."
DEVELOPMENT_DEMO_EMAIL = "demo@example.test"
DEVELOPMENT_DEMO_PASSWORD = "Demo1@Hotel2026"
FORGOT_PASSWORD_MESSAGE = (
    "Nếu email tồn tại trong hệ thống, mã xác nhận sẽ được gửi."
)
RESET_PASSWORD_SUCCESS_MESSAGE = "Mật khẩu đã được đặt lại. Vui lòng đăng nhập."
INVALID_RESET_CODE_MESSAGE = "Mã xác nhận không hợp lệ hoặc đã hết hạn."
RECOVERY_SERVICE_ERROR = "Hệ thống tạm thời không thể xử lý yêu cầu. Vui lòng thử lại."
RECOVERY_SESSION_KEY = "password_reset_challenge_id"
TRUE_VALUES = {"1", "true", "yes", "on"}
ALLOWED_ROOM_IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}
PROFILE_IMAGE_SIGNATURES = {
    "jpg": (b"\xff\xd8\xff",),
    "jpeg": (b"\xff\xd8\xff",),
    "png": (b"\x89PNG\r\n\x1a\n",),
    "webp": (b"RIFF",),
}
ROOM_IMAGE_SIGNATURES = {
    "jpg": (b"\xff\xd8\xff",),
    "jpeg": (b"\xff\xd8\xff",),
    "png": (b"\x89PNG\r\n\x1a\n",),
    "webp": (b"RIFF",),
}
ROOM_FLOORS = (
    {
        "name": "Tầng 1",
        "rooms": (
            {
                "number": "101", "type": "Phòng đơn",
                "status": "Phòng trống", "state": "empty",
                "check_in": None, "check_out": None,
            },
            {
                "number": "102", "type": "Phòng đôi",
                "status": "Phòng trống", "state": "empty",
                "check_in": None, "check_out": None,
            },
            {
                "number": "103", "type": "Phòng đơn",
                "status": "Phòng trống", "state": "empty",
                "check_in": None, "check_out": None,
            },
            {
                "number": "104", "type": "Phòng VIP",
                "status": "Phòng trống", "state": "empty",
                "check_in": None, "check_out": None,
            },
        ),
    },
    {
        "name": "Tầng 2",
        "rooms": (
            {
                "number": "201", "type": "Phòng đôi",
                "status": "Phòng trống", "state": "empty",
                "check_in": None, "check_out": None,
            },
            {
                "number": "202", "type": "Phòng đơn",
                "status": "Phòng trống", "state": "empty",
                "check_in": None, "check_out": None,
            },
            {
                "number": "203", "type": "Phòng VIP",
                "status": "Phòng trống", "state": "empty",
                "check_in": None, "check_out": None,
            },
            {
                "number": "204", "type": "Phòng đôi",
                "status": "Phòng trống", "state": "empty",
                "check_in": None, "check_out": None,
            },
        ),
    },
    {
        "name": "Tầng 3",
        "rooms": (
            {
                "number": "301", "type": "Phòng đơn",
                "status": "Phòng trống", "state": "empty",
                "check_in": None, "check_out": None,
            },
            {
                "number": "302", "type": "Phòng VIP",
                "status": "Phòng trống", "state": "empty",
                "check_in": None, "check_out": None,
            },
            {
                "number": "303", "type": "Phòng đôi",
                "status": "Phòng trống", "state": "empty",
                "check_in": None, "check_out": None,
            },
            {
                "number": "304", "type": "Phòng đơn",
                "status": "Phòng trống", "state": "empty",
                "check_in": None, "check_out": None,
            },
        ),
    },
)
ROOM_TYPE_CATALOG = (
    {
        "name": "Phòng đơn",
        "price": 500000,
        "quantity": 0,
        "capacity": "2 người",
        "description": "Phòng cơ bản đầy đủ tiện nghi",
        "status": "active",
    },
    {
        "name": "Phòng đôi",
        "price": 750000,
        "quantity": 0,
        "capacity": "2 người",
        "description": "Phòng có giường đôi",
        "status": "active",
    },
    {
        "name": "Phòng VIP",
        "price": 1200000,
        "quantity": 0,
        "capacity": "4 người",
        "description": "Phòng rộng, view biển, có bồn tắm",
        "status": "active",
    },
)


def _room_type_defaults(room_type: str) -> dict[str, Any] | None:
    canonical_name = (room_type or "").strip().casefold()
    return next(
        (
            defaults
            for defaults in ROOM_TYPE_CATALOG
            if defaults["name"].casefold() == canonical_name
        ),
        None,
    )


def _room_display_values(room: Room) -> dict[str, Any]:
    defaults = _room_type_defaults(room.type)
    return {
        "description": room.description
        or (defaults["description"] if defaults is not None else ""),
        "price": room.price
        if room.price > 0
        else (defaults["price"] if defaults is not None else 0),
    }


def _environment(test_config: dict[str, Any] | None) -> str:
    if test_config and "APP_ENV" in test_config:
        return str(test_config["APP_ENV"])
    return os.environ.get("APP_ENV", "production")


def _secret_key(environment: str, test_config: dict[str, Any] | None) -> str:
    if test_config and test_config.get("SECRET_KEY"):
        return str(test_config["SECRET_KEY"])

    configured_key = os.environ.get("SECRET_KEY")
    if configured_key:
        return configured_key

    if environment in {"development", "testing"}:
        return secrets.token_hex(32)

    raise RuntimeError("SECRET_KEY must be configured outside Development.")


def _environment_flag(name: str, default: bool) -> bool:
    """Read a small boolean environment flag without extra dependencies."""

    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().casefold() in TRUE_VALUES


def _valid_room_time(value: str) -> bool:
    if not value:
        return True
    try:
        parsed_time = datetime.strptime(value, "%H:%M")
    except ValueError:
        return False
    return parsed_time.strftime("%H:%M") == value


def _intervals_overlap(start_a: datetime, end_a: datetime, start_b: datetime, end_b: datetime) -> bool:
    """Return whether two half-open room schedule intervals overlap."""

    return start_a < end_b and end_a > start_b


def intervals_conflict_with_cleaning_buffer(
    start_a: datetime,
    end_a: datetime,
    start_b: datetime,
    end_b: datetime,
    buffer_minutes: int = CLEANING_BUFFER_MINUTES,
) -> bool:
    """Return whether two stays overlap or leave less than the required gap."""

    buffer = timedelta(minutes=buffer_minutes)
    compatible_a_before_b = end_a + buffer <= start_b
    compatible_b_before_a = end_b + buffer <= start_a
    return not (compatible_a_before_b or compatible_b_before_a)


def _valid_vietnamese_phone(value: str) -> bool:
    digits_only = re.sub(r"\D", "", value)
    return bool(re.fullmatch(r"(?:0(?:3|5|7|8|9)\d{8}|84\d{9})", digits_only))


def _rental_amount(price_per_night: int, duration_minutes: int) -> int:
    amount = Decimal(price_per_night) * Decimal(duration_minutes) / Decimal(1440)
    return int(amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _utc_now() -> datetime:
    """Return naive UTC for consistent storage in SQLite DateTime columns."""

    return datetime.now(timezone.utc).replace(tzinfo=None)


def _seed_demo_user(app: Flask) -> None:
    if (
        app.config["APP_ENV"] != "development"
        or not app.config["SEED_DEMO_USER"]
    ):
        return

    demo_email = normalize_email(app.config.get("DEMO_USER_EMAIL"))
    demo_password = app.config.get("DEMO_USER_PASSWORD") or ""
    if not demo_email or not demo_password:
        return

    existing_user = db.session.execute(
        db.select(User).where(User.email == demo_email)
    ).scalar_one_or_none()
    if existing_user is not None:
        return

    demo_user = User(email=demo_email)
    demo_user.set_password(demo_password)
    db.session.add(demo_user)
    db.session.commit()


def _seed_room_types() -> None:
    seed_state = db.session.get(RoomTypeSeedState, 1)
    legacy_single = db.session.execute(
        db.select(RoomType).where(RoomType.name == "Phòng tiêu chuẩn")
    ).scalar_one_or_none()
    if (
        seed_state is not None
        and seed_state.initialized
        and legacy_single is None
    ):
        return

    existing_room_types = db.session.execute(db.select(RoomType)).scalars().all()
    existing_names = {room_type.name.casefold() for room_type in existing_room_types}
    if legacy_single is not None and "phòng đơn" not in existing_names:
        legacy_single.name = "Phòng đơn"
        existing_names.remove("phòng tiêu chuẩn")
        existing_names.add("phòng đơn")

    seed_state = seed_state or RoomTypeSeedState(id=1)
    seed_state.initialized = True
    db.session.add_all(
        RoomType(**room_type)
        for room_type in ROOM_TYPE_CATALOG
        if room_type["name"].casefold() not in existing_names
    )
    db.session.add(seed_state)
    db.session.commit()


def _room_values(
    room_data: dict[str, Any], floor: str, position: int, *, is_demo: bool
) -> dict[str, Any]:
    room_type = room_data.get("type", "")
    if room_type == "Phòng tiêu chuẩn":
        room_type = "Phòng đơn"
    elif room_type in {"Phòng 1 giường đôi", "Phòng 2 giường đơn"}:
        room_type = "Phòng đôi"
    return {
        "number": str(room_data.get("number", "")),
        "floor": floor,
        "position": position,
        "type": room_type,
        "description": str(room_data.get("description") or ""),
        "price": int(room_data.get("price") or 0),
        "image": room_data.get("image"),
        "status": str(room_data.get("status") or "Phòng trống"),
        "state": str(room_data.get("state") or "empty"),
        "check_in": room_data.get("check_in"),
        "check_out": room_data.get("check_out"),
        "is_demo": is_demo,
    }


def _seed_rooms() -> None:
    seed_state = db.session.get(RoomSeedState, 1)
    if seed_state is not None and seed_state.initialized:
        return

    has_rooms = db.session.execute(db.select(Room.id).limit(1)).first() is not None
    seed_state = seed_state or RoomSeedState(id=1)
    seed_state.initialized = True
    db.session.add(seed_state)
    if not has_rooms:
        db.session.add_all(
            Room(**_room_values(room, floor["name"], position, is_demo=True))
            for floor in ROOM_FLOORS
            for position, room in enumerate(floor["rooms"])
        )
    db.session.commit()


def _migrate_legacy_room_session() -> None:
    legacy_floors = session.get("room_floors")
    if legacy_floors is None:
        return

    migration = db.session.get(LegacyRoomSessionMigration, 1)
    if migration is not None and migration.completed:
        demo_numbers = {
            str(room["number"]).casefold()
            for floor in ROOM_FLOORS
            for room in floor["rooms"]
        }
        existing_numbers = {
            number.casefold()
            for number in db.session.execute(db.select(Room.number)).scalars()
        }
        for floor in legacy_floors:
            for position, room_data in enumerate(floor.get("rooms", ())):
                values = _room_values(
                    room_data,
                    floor["name"],
                    position,
                    is_demo=str(room_data.get("number", "")).casefold()
                    in demo_numbers,
                )
                if (
                    values["number"].casefold() not in existing_numbers
                    and values["number"].casefold() not in demo_numbers
                ):
                    db.session.add(Room(**values))
                    existing_numbers.add(values["number"].casefold())
        try:
            db.session.commit()
        except SQLAlchemyError:
            db.session.rollback()
            raise
        session.pop("room_floors", None)
        return

    demo_numbers = {
        str(room["number"]).casefold()
        for floor in ROOM_FLOORS
        for room in floor["rooms"]
    }
    legacy_rooms = [
        (floor["name"], position, room)
        for floor in legacy_floors
        for position, room in enumerate(floor.get("rooms", ()))
    ]
    legacy_numbers = {str(room.get("number", "")).casefold() for _, _, room in legacy_rooms}
    existing_rooms = db.session.execute(db.select(Room)).scalars().all()
    existing_by_number = {room.number.casefold(): room for room in existing_rooms}

    for existing in existing_rooms:
        if existing.is_demo and existing.number.casefold() not in legacy_numbers:
            db.session.delete(existing)

    for floor_name, position, room_data in legacy_rooms:
        values = _room_values(
            room_data,
            floor_name,
            position,
            is_demo=str(room_data.get("number", "")).casefold() in demo_numbers,
        )
        existing = existing_by_number.get(values["number"].casefold())
        if existing is None:
            db.session.add(Room(**values))
        elif existing.is_demo:
            for key, value in values.items():
                setattr(existing, key, value)

    migration = migration or LegacyRoomSessionMigration(id=1)
    migration.completed = True
    db.session.add(migration)
    db.session.commit()
    session.pop("room_floors", None)


ROOM_STATUS_TO_STATE = {
    "Phòng trống": "empty",
    "Đang thuê": "occupied",
    "Dọn dẹp": "cleaning",
    "Bảo trì": "maintenance",
}
ROOM_STATE_TO_STATUS = {state: status for status, state in ROOM_STATUS_TO_STATE.items()}
ROOM_STATUS_ORDER = tuple(ROOM_STATUS_TO_STATE)
ROOM_FILTER_TO_STATE = {"empty": "empty", "occupied": "occupied", "cleaning": "cleaning", "maintenance": "maintenance"}


def _room_status_counts(rooms: list[Room]) -> dict[str, int]:
    counts = {status: 0 for status in ROOM_STATUS_ORDER}
    for room in rooms:
        if ROOM_STATUS_TO_STATE.get(room.status) == room.state:
            counts[room.status] += 1
    return counts


def active_room_service_logs(room_id: int) -> list[RoomServiceLog]:
    return db.session.execute(
        db.select(RoomServiceLog)
        .where(RoomServiceLog.room_id == room_id, RoomServiceLog.ended_at.is_(None))
        .order_by(RoomServiceLog.started_at, RoomServiceLog.id)
        .limit(2)
    ).scalars().all()


def room_service_state_is_valid(room: Room) -> bool:
    active = active_room_service_logs(room.id)
    expected_type = {"cleaning": "cleaning", "maintenance": "maintenance"}.get(room.state)
    if expected_type is None:
        return not active
    return len(active) == 1 and active[0].service_type == expected_type


def start_room_service(
    room: Room,
    service_type: str,
    *,
    note: str | None = None,
    started_at: datetime | None = None,
) -> RoomServiceLog:
    if service_type not in {"cleaning", "maintenance"}:
        raise ValueError("Invalid room service type")
    if active_room_service_logs(room.id):
        raise ValueError("A room service period is already active")
    log = RoomServiceLog(
        room_id=room.id,
        room_number=room.number,
        service_type=service_type,
        started_at=started_at or datetime.now().replace(second=0, microsecond=0),
        ended_at=None,
        note=(note or "").strip() or None,
    )
    db.session.add(log)
    return log


def close_active_room_service(
    room: Room,
    expected_type: str,
    *,
    ended_at: datetime | None = None,
) -> RoomServiceLog:
    active = active_room_service_logs(room.id)
    if len(active) != 1 or active[0].service_type != expected_type:
        raise ValueError("The active room service period is missing or inconsistent")
    active[0].ended_at = ended_at or datetime.now().replace(second=0, microsecond=0)
    return active[0]


def _rooms_for_management() -> list[Room]:
    _migrate_legacy_room_session()
    return db.session.execute(
        db.select(Room).order_by(Room.number.asc(), Room.id.asc())
    ).scalars().all()


def create_app(test_config: dict[str, Any] | None = None) -> Flask:
    """Create the small Login application with optional isolated test config."""

    environment = _environment(test_config)
    INSTANCE_PATH.mkdir(parents=True, exist_ok=True)

    app = Flask(__name__, instance_path=str(INSTANCE_PATH))
    app.config.from_mapping(
        APP_ENV=environment,
        SECRET_KEY=_secret_key(environment, test_config),
        SQLALCHEMY_DATABASE_URI=os.environ.get(
            "DATABASE_URL", "sqlite:///hotel.db"
        ),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        MAX_CONTENT_LENGTH=5 * 1024 * 1024 + 64 * 1024,
        ROOM_UPLOAD_FOLDER=str(INSTANCE_PATH / "uploads"),
        SESSION_COOKIE_NAME="hotel_session",
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=environment not in {"development", "testing"},
        PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
        SESSION_REFRESH_EACH_REQUEST=False,
        SEED_DEMO_USER=_environment_flag(
            "SEED_DEMO_USER", environment == "development"
        ),
        DEMO_USER_EMAIL=(
            os.environ.get("DEMO_USER_EMAIL") or DEVELOPMENT_DEMO_EMAIL
        ),
        DEMO_USER_PASSWORD=(
            os.environ.get("DEMO_USER_PASSWORD") or DEVELOPMENT_DEMO_PASSWORD
        ),
        EMAIL_PROVIDER=os.environ.get("EMAIL_PROVIDER", "brevo"),
        BREVO_API_KEY=os.environ.get("BREVO_API_KEY", ""),
        MAIL_FROM=os.environ.get("MAIL_FROM", ""),
        MAIL_FROM_NAME=os.environ.get("MAIL_FROM_NAME", "Hotel Management"),
    )
    if test_config:
        app.config.update(test_config)

    db.init_app(app)
    csrf.init_app(app)

    def current_user() -> User | None:
        user_id = session.get("user_id")
        if user_id is None:
            return None

        user = db.session.get(User, user_id)
        if user is None:
            session.clear()
        return user

    def latest_room_rental(room: Room) -> RoomRental | None:
        return db.session.execute(
            db.select(RoomRental).where(
                RoomRental.room_id == room.id, RoomRental.room_number == room.number
            ).order_by(RoomRental.rented_at.desc(), RoomRental.id.desc()).limit(1)
        ).scalar_one_or_none()

    def booked_reservations_for_room(room_id: int) -> list[RoomReservation]:
        return db.session.execute(
            db.select(RoomReservation).where(
                RoomReservation.room_id == room_id, RoomReservation.status == "booked"
            ).order_by(RoomReservation.reserved_from, RoomReservation.id)
        ).scalars().all()

    def booked_reservations_conflicting_with_cleaning_buffer(
        room_id: int, start: datetime, end: datetime, *, exclude_id: int | None = None
    ) -> list[RoomReservation]:
        statement = db.select(RoomReservation).where(
            RoomReservation.room_id == room_id,
            RoomReservation.status == "booked",
        )
        if exclude_id is not None:
            statement = statement.where(RoomReservation.id != exclude_id)
        candidates = db.session.execute(
            statement.order_by(RoomReservation.reserved_from, RoomReservation.id)
        ).scalars().all()
        return [
            reservation
            for reservation in candidates
            if intervals_conflict_with_cleaning_buffer(
                start, end, reservation.reserved_from, reservation.reserved_until
            )
        ]

    def next_effective_booked_reservation(
        room_id: int, after_at: datetime
    ) -> RoomReservation | None:
        return db.session.execute(
            db.select(RoomReservation)
            .where(
                RoomReservation.room_id == room_id,
                RoomReservation.status == "booked",
                RoomReservation.reserved_until > after_at,
            )
            .order_by(RoomReservation.reserved_from, RoomReservation.id)
            .limit(1)
        ).scalar_one_or_none()

    def ready_after_recent_checkout(room: Room) -> datetime | None:
        checkout_log = db.session.execute(
            db.select(RoomServiceLog)
            .where(
                RoomServiceLog.room_id == room.id,
                RoomServiceLog.service_type == "cleaning",
                RoomServiceLog.note == CHECKOUT_CLEANING_LOG_NOTE,
            )
            .order_by(RoomServiceLog.started_at.desc(), RoomServiceLog.id.desc())
            .limit(1)
        ).scalar_one_or_none()
        if checkout_log is None:
            latest_rental = db.session.execute(
                db.select(RoomRental)
                .where(RoomRental.room_id == room.id)
                .order_by(RoomRental.rented_at.desc(), RoomRental.id.desc())
                .limit(1)
            ).scalar_one_or_none()
            if latest_rental is None:
                return None
            checkout_log = db.session.execute(
                db.select(RoomServiceLog)
                .where(
                    RoomServiceLog.room_id == room.id,
                    RoomServiceLog.service_type == "cleaning",
                    RoomServiceLog.started_at >= latest_rental.rented_at,
                )
                .order_by(RoomServiceLog.started_at.desc(), RoomServiceLog.id.desc())
                .limit(1)
            ).scalar_one_or_none()
            if checkout_log is None:
                if latest_rental.expected_checkout <= datetime.now().replace(second=0, microsecond=0):
                    return latest_rental.expected_checkout + timedelta(minutes=CLEANING_BUFFER_MINUTES)
                return None
        buffer_ready_at = checkout_log.started_at + timedelta(minutes=CLEANING_BUFFER_MINUTES)
        latest_service_end = db.session.execute(
            db.select(RoomServiceLog.ended_at)
            .where(
                RoomServiceLog.room_id == room.id,
                RoomServiceLog.started_at >= checkout_log.started_at,
                RoomServiceLog.ended_at.is_not(None),
            )
            .order_by(RoomServiceLog.ended_at.desc(), RoomServiceLog.id.desc())
            .limit(1)
        ).scalar_one_or_none()
        return max(buffer_ready_at, latest_service_end or checkout_log.started_at)

    def validate_reservation_form(
        room: Room, *, exclude_reservation_id: int | None = None
    ) -> tuple[dict[str, str], dict[str, str], str | None, tuple[datetime, datetime, int, int, int] | None]:
        form = {
            "guest_name": request.form.get("guest_name", "").strip(),
            "guest_phone": request.form.get("guest_phone", "").strip(),
            "reserved_from": request.form.get("reserved_from", "").strip(),
            "reserved_until": request.form.get("reserved_until", "").strip(),
        }
        errors: dict[str, str] = {}
        service_error = None
        if not form["guest_name"]:
            errors["guest_name"] = "Vui lòng nhập tên khách hàng."
        elif len(form["guest_name"]) > 120:
            errors["guest_name"] = "Tên khách hàng không được vượt quá 120 ký tự."
        if not form["guest_phone"]:
            errors["guest_phone"] = "Vui lòng nhập số điện thoại."
        elif len(form["guest_phone"]) > 30 or not _valid_vietnamese_phone(form["guest_phone"]):
            errors["guest_phone"] = "Số điện thoại không hợp lệ."

        parsed: dict[str, datetime | None] = {"reserved_from": None, "reserved_until": None}
        for field, label in (("reserved_from", "nhận phòng"), ("reserved_until", "trả phòng")):
            value = form[field]
            try:
                candidate = datetime.strptime(value, "%Y-%m-%dT%H:%M")
                if candidate.strftime("%Y-%m-%dT%H:%M") != value:
                    raise ValueError
                parsed[field] = candidate
            except ValueError:
                errors[field] = f"Vui lòng chọn thời gian {label} hợp lệ."
        reserved_from = parsed["reserved_from"]
        reserved_until = parsed["reserved_until"]
        now = datetime.now().replace(second=0, microsecond=0)
        if reserved_from is not None and reserved_from <= now:
            errors["reserved_from"] = "Thời gian nhận phòng phải ở trong tương lai."
        if reserved_from is not None and reserved_until is not None:
            if reserved_from >= reserved_until:
                errors["reserved_until"] = "Thời gian trả phòng phải sau thời gian nhận phòng."
            elif not errors:
                if room.status == "Đang thuê" and room.state == "occupied":
                    active_rental = latest_room_rental(room)
                    if active_rental is None:
                        service_error = "Không thể xác định lượt thuê hiện tại của phòng."
                    elif intervals_conflict_with_cleaning_buffer(
                        reserved_from, reserved_until,
                        active_rental.rented_at, active_rental.expected_checkout,
                    ):
                        errors["reserved_from"] = f"Phải chừa tối thiểu {CLEANING_BUFFER_MINUTES} phút để dọn dẹp giữa hai lượt khách."
                elif room.status == "Phòng trống" and room.state == "empty":
                    pass
                elif exclude_reservation_id is not None and (
                    (room.status == "Dọn dẹp" and room.state == "cleaning")
                    or (room.status == "Bảo trì" and room.state == "maintenance")
                ):
                    # Existing bookings may still be edited or cancelled while the room is serviced.
                    pass
                elif room.status == "Dọn dẹp" and room.state == "cleaning":
                    service_error = "Không thể đặt trước khi phòng đang dọn dẹp."
                elif room.status == "Bảo trì" and room.state == "maintenance":
                    service_error = "Không thể đặt trước khi phòng đang bảo trì."
                else:
                    service_error = "Trạng thái phòng không hợp lệ để đặt trước."
                if not errors and service_error is None and room.state == "empty":
                    ready_at = ready_after_recent_checkout(room)
                    if ready_at is not None and reserved_from < ready_at:
                        errors["reserved_from"] = f"Phải chừa tối thiểu {CLEANING_BUFFER_MINUTES} phút để dọn dẹp giữa hai lượt khách."
                if not errors and service_error is None and booked_reservations_conflicting_with_cleaning_buffer(
                    room.id, reserved_from, reserved_until, exclude_id=exclude_reservation_id
                ):
                    errors["reserved_from"] = f"Phải chừa tối thiểu {CLEANING_BUFFER_MINUTES} phút để dọn dẹp giữa hai lượt khách."

        price = _room_display_values(room)["price"]
        if price <= 0:
            service_error = "Phòng chưa có giá hợp lệ, không thể đặt trước."
        if errors or service_error:
            return form, errors, service_error, None
        if reserved_from is None or reserved_until is None:
            return form, errors, service_error, None
        duration = int((reserved_until - reserved_from).total_seconds() // 60)
        return form, errors, service_error, (reserved_from, reserved_until, duration, price, _rental_amount(price, duration))

    def reservation_form_values(reservation: RoomReservation) -> dict[str, str]:
        return {
            "guest_name": reservation.guest_name,
            "guest_phone": reservation.guest_phone,
            "reserved_from": reservation.reserved_from.strftime("%Y-%m-%dT%H:%M"),
            "reserved_until": reservation.reserved_until.strftime("%Y-%m-%dT%H:%M"),
        }

    def room_type_options() -> dict[str, str]:
        room_types = db.session.execute(
            db.select(RoomType).order_by(RoomType.id)
        ).scalars()
        return {str(room_type.id): room_type.name for room_type in room_types}

    def rooms_using_room_type(name: str) -> list[Room]:
        canonical_name = name.strip().casefold()
        return [
            room
            for room in db.session.execute(db.select(Room)).scalars()
            if (room.type or "").strip().casefold() == canonical_name
        ]

    def validate_selected_room_ids(
        source: RoomType, submitted_values: list[str]
    ) -> tuple[list[Room], list[Room], list[Room], str | None]:
        source_rooms = rooms_using_room_type(source.name)
        source_by_id = {room.id: room for room in source_rooms}
        selected_ids: set[int] = set()
        for submitted_value in submitted_values:
            try:
                room_id = int(submitted_value)
            except (TypeError, ValueError):
                return source_rooms, [], source_rooms, "Danh sách phòng được chọn không hợp lệ. Vui lòng thử lại."
            if room_id <= 0:
                return source_rooms, [], source_rooms, "Danh sách phòng được chọn không hợp lệ. Vui lòng thử lại."
            selected_ids.add(room_id)

        if selected_ids:
            existing_rooms = {
                room.id: room
                for room in db.session.execute(
                    db.select(Room).where(Room.id.in_(selected_ids))
                ).scalars()
            }
            if any(
                room_id not in existing_rooms or room_id not in source_by_id
                for room_id in selected_ids
            ):
                return source_rooms, [], source_rooms, "Một hoặc nhiều phòng không còn thuộc thể loại nguồn. Vui lòng tải lại và thử lại."

        selected_rooms = [room for room in source_rooms if room.id in selected_ids]
        remaining_rooms = [room for room in source_rooms if room.id not in selected_ids]
        return source_rooms, selected_rooms, remaining_rooms, None

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if current_user() is not None:
            return redirect(url_for("home"))

        email_input = request.form.get("email", "")
        errors: dict[str, str] = {}
        credential_error: str | None = None

        if request.method == "POST":
            password = request.form.get("password", "")
            canonical_email = normalize_email(email_input)

            if not canonical_email:
                errors["email"] = "Vui lòng nhập Email."
            if not password:
                errors["password"] = "Vui lòng nhập Mật khẩu."

            if not errors:
                user = db.session.execute(
                    db.select(User).where(User.email == canonical_email)
                ).scalar_one_or_none()

                password_is_valid = False
                if user is not None:
                    try:
                        password_is_valid = user.check_password(password)
                    except ValueError:
                        app.logger.error("A User record has an invalid password hash.")

                if password_is_valid:
                    session.clear()
                    session["user_id"] = user.id
                    session.permanent = True
                    flash("Đăng nhập thành công", "login_success")
                    return redirect(url_for("home"))

                session.pop("user_id", None)
                credential_error = INVALID_CREDENTIAL_MESSAGE

        return render_template(
            "login.html",
            email=email_input,
            errors=errors,
            credential_error=credential_error,
            service_error=None,
        )

    def issue_recovery_challenge(user: User) -> bool:
        """Persist an attempt before provider I/O, then record its outcome."""

        now = _utc_now()
        cutoff = now - timedelta(minutes=15)
        recent = db.session.execute(
            db.select(PasswordResetChallenge).where(
                PasswordResetChallenge.user_id == user.id,
                PasswordResetChallenge.created_at > cutoff,
            ).order_by(PasswordResetChallenge.created_at.desc())
        ).scalars().all()
        if recent and (now - recent[0].created_at).total_seconds() < 60:
            return False
        if len(recent) >= 5:
            return False

        # Preserve the rolling-window rows for quota accounting, then trim old data.
        old_rows = db.session.execute(
            db.select(PasswordResetChallenge).where(
                PasswordResetChallenge.user_id == user.id,
                PasswordResetChallenge.created_at < now - timedelta(days=1),
            )
        ).scalars().all()
        for old_row in old_rows:
            db.session.delete(old_row)

        user.password_reset_version += 1
        otp = generate_otp()
        challenge = PasswordResetChallenge(
            user_id=user.id,
            reset_version=user.password_reset_version,
            otp_digest="",
            created_at=now,
            expires_at=now + timedelta(minutes=5),
            failed_attempts=0,
            delivery_status="pending",
        )
        db.session.add(challenge)
        db.session.flush()
        challenge.otp_digest = otp_digest(
            app.config["SECRET_KEY"], challenge.id, user.id,
            challenge.reset_version, otp,
        )
        db.session.commit()
        session[RECOVERY_SESSION_KEY] = challenge.id

        sent = send_password_reset_otp(user.email, otp, app.config)
        challenge.delivery_status = "sent" if sent else "failed"
        try:
            db.session.commit()
        except SQLAlchemyError:
            db.session.rollback()
            app.logger.error("Password reset delivery state could not be saved.")
            return False
        return sent

    def clear_recovery_session() -> None:
        session.pop(RECOVERY_SESSION_KEY, None)

    def active_challenge() -> tuple[PasswordResetChallenge, User] | None:
        challenge_id = session.get(RECOVERY_SESSION_KEY)
        if not isinstance(challenge_id, int):
            return None
        challenge = db.session.get(PasswordResetChallenge, challenge_id)
        if challenge is None:
            return None
        user = db.session.get(User, challenge.user_id)
        if user is None:
            return None
        return challenge, user

    def recovery_is_verified(challenge: PasswordResetChallenge, user: User) -> bool:
        now = _utc_now()
        return bool(
            challenge.reset_version == user.password_reset_version
            and challenge.verified_at is not None
            and challenge.authorization_expires_at is not None
            and now < challenge.authorization_expires_at
            and challenge.consumed_at is None
        )

    @app.route("/forgot-password", methods=["GET", "POST"])
    def forgot_password():
        email_input = request.form.get("email", "")
        errors: dict[str, str] = {}

        if request.method == "POST":
            clear_recovery_session()
            canonical_email = normalize_email(email_input)
            if not canonical_email or "@" not in canonical_email:
                errors["email"] = "Vui lòng nhập email hợp lệ."
            else:
                user = db.session.execute(
                    db.select(User).where(User.email == canonical_email)
                ).scalar_one_or_none()
                if user is not None:
                    try:
                        issue_recovery_challenge(user)
                    except SQLAlchemyError:
                        db.session.rollback()
                        app.logger.error("Password reset request could not be processed.")
                flash(FORGOT_PASSWORD_MESSAGE, "success")
                return redirect(url_for("verify_reset_code"), code=303)

        return render_template(
            "forgot_password.html", email=email_input, errors=errors
        )

    @app.route("/resend-reset-code", methods=["POST"])
    def resend_reset_code():
        current = active_challenge()
        if current is None:
            clear_recovery_session()
            return redirect(url_for("forgot_password"), code=303)
        _challenge, user = current
        try:
            issue_recovery_challenge(user)
        except SQLAlchemyError:
            db.session.rollback()
            app.logger.error("Password reset resend could not be processed.")
        flash(FORGOT_PASSWORD_MESSAGE, "success")
        return redirect(url_for("verify_reset_code"), code=303)

    @app.route("/verify-reset-code", methods=["GET", "POST"])
    def verify_reset_code():
        errors: dict[str, str] = {}
        if request.method == "POST":
            current = active_challenge()
            code = request.form.get("otp", "")
            if current is None:
                clear_recovery_session()
                errors["otp"] = INVALID_RESET_CODE_MESSAGE
            else:
                challenge, user = current
                now = _utc_now()
                usable = (
                    challenge.reset_version == user.password_reset_version
                    and challenge.delivery_status == "sent"
                    and now < challenge.expires_at
                    and challenge.failed_attempts < 5
                    and challenge.verified_at is None
                    and challenge.consumed_at is None
                )
                if not usable:
                    errors["otp"] = INVALID_RESET_CODE_MESSAGE
                else:
                    well_formed = (
                        len(code) == 6 and code.isascii() and code.isdecimal()
                    )
                    matched = well_formed and otp_matches(
                        challenge.otp_digest,
                        app.config["SECRET_KEY"],
                        challenge.id,
                        user.id,
                        challenge.reset_version,
                        code,
                    )
                    if matched:
                        challenge.verified_at = now
                        challenge.authorization_expires_at = now + timedelta(
                            minutes=10
                        )
                        db.session.commit()
                        return redirect(url_for("reset_password"), code=303)
                    challenge.failed_attempts += 1
                    db.session.commit()
                    errors["otp"] = INVALID_RESET_CODE_MESSAGE
        return render_template("verify_reset_code.html", errors=errors)

    @app.route("/reset-password", methods=["GET", "POST"])
    def reset_password():
        current = active_challenge()
        if current is None or not recovery_is_verified(*current):
            clear_recovery_session()
            if request.method == "GET":
                return redirect(url_for("forgot_password"), code=303)
            return render_template(
                "verify_reset_code.html", errors={"otp": INVALID_RESET_CODE_MESSAGE}
            ), 400
        challenge, user = current
        errors: dict[str, str] = {}
        if request.method == "POST":
            new_password = request.form.get("new_password", "")
            confirm_password = request.form.get("confirm_password", "")
            if not new_password:
                errors["new_password"] = "Vui lòng nhập mật khẩu mới."
            elif len(new_password) < 8:
                errors["new_password"] = "Mật khẩu phải có ít nhất 8 ký tự."
            if not confirm_password:
                errors["confirm_password"] = "Vui lòng xác nhận mật khẩu mới."
            elif new_password and new_password != confirm_password:
                errors["confirm_password"] = "Mật khẩu xác nhận không khớp."
            if errors:
                return render_template(
                    "reset_password.html", errors=errors, service_error=None
                )

            try:
                # Conditional update protects against a concurrent newer request.
                expected_version = challenge.reset_version
                user.set_password(new_password)
                result = db.session.execute(
                    update(User)
                    .where(
                        User.id == user.id,
                        User.password_reset_version == expected_version,
                    )
                    .values(
                        password_hash=user.password_hash,
                        password_reset_version=expected_version + 1,
                    ),
                    execution_options={"synchronize_session": False},
                )
                challenge.consumed_at = _utc_now()
                if result.rowcount != 1:
                    db.session.rollback()
                    clear_recovery_session()
                    return redirect(url_for("forgot_password"), code=303)
                db.session.commit()
            except SQLAlchemyError:
                db.session.rollback()
                app.logger.error("Password reset database update failed.")
                return render_template(
                    "reset_password.html", errors={},
                    service_error=RECOVERY_SERVICE_ERROR,
                ), 503
            clear_recovery_session()
            flash(RESET_PASSWORD_SUCCESS_MESSAGE, "success")
            return redirect(url_for("login"), code=303)

        return render_template(
            "reset_password.html", errors=errors, service_error=None
        )

    @app.route("/register", methods=["GET", "POST"])
    def register():
        if current_user() is not None:
            return redirect(url_for("home"))

        email_input = request.form.get("email", "")
        errors: dict[str, str] = {}

        if request.method == "POST":
            password = request.form.get("password", "")
            confirm_password = request.form.get("confirm_password", "")
            canonical_email = normalize_email(email_input)

            if not canonical_email:
                errors["email"] = "Vui lòng nhập Email."
            if not password:
                errors["password"] = "Vui lòng nhập Mật khẩu."
            elif len(password) < 8:
                errors["password"] = "Mật khẩu phải có ít nhất 8 ký tự."
            if not confirm_password:
                errors["confirm_password"] = "Vui lòng xác nhận Mật khẩu."
            elif password and confirm_password != password:
                errors["confirm_password"] = "Mật khẩu xác nhận không khớp"

            if not errors:
                existing_user = db.session.execute(
                    db.select(User).where(User.email == canonical_email)
                ).scalar_one_or_none()

                if existing_user is not None:
                    errors["email"] = "Email đã được sử dụng"
                else:
                    user = User(email=canonical_email)
                    user.set_password(password)
                    db.session.add(user)
                    try:
                        db.session.commit()
                    except IntegrityError:
                        db.session.rollback()
                        errors["email"] = "Email đã được sử dụng"
                    else:
                        flash(REGISTER_SUCCESS_MESSAGE, "success")
                        return redirect(url_for("login"))

        return render_template(
            "register.html",
            email=email_input,
            errors=errors,
            service_error=None,
        )

    @app.route("/")
    def home():
        user = current_user()
        if user is None:
            return redirect(url_for("login"))
        rooms = _rooms_for_management()
        room_status_counts = _room_status_counts(rooms)
        return render_template(
            "home.html",
            user=user,
            rooms=rooms,
            room_count=len(rooms),
            room_status_counts=room_status_counts,
        )

    def render_room_management(
        user: User | None,
        room_status_filter: str = "all",
        **form_context,
    ):
        all_rooms = _rooms_for_management()
        room_status_counts = _room_status_counts(all_rooms)
        room_count = len(all_rooms)
        selected_state = ROOM_FILTER_TO_STATE.get(room_status_filter)
        rooms = [room for room in all_rooms if room.state == selected_state and ROOM_STATE_TO_STATUS.get(selected_state) == room.status] if selected_state else all_rooms
        room_display_values = {room.id: _room_display_values(room) for room in rooms}
        room_ids = [room.id for room in rooms]
        active_room_rentals = {}
        room_reservations_by_room: dict[int, list[RoomReservation]] = {}
        next_room_reservations: dict[int, RoomReservation] = {}
        maintenance_reservation_counts: dict[int, int] = {}
        schedule_now = datetime.now().replace(second=0, microsecond=0)
        if room_ids:
            rentals = db.session.execute(
                db.select(RoomRental).where(RoomRental.room_id.in_(room_ids))
                .order_by(RoomRental.rented_at.desc(), RoomRental.id.desc())
            ).scalars()
            for rental in rentals:
                active_room_rentals.setdefault(rental.room_id, rental)
            reservations = db.session.execute(
                db.select(RoomReservation).where(
                    RoomReservation.room_id.in_(room_ids),
                    RoomReservation.status == "booked",
                ).order_by(RoomReservation.reserved_from, RoomReservation.id)
            ).scalars().all()
            for reservation in reservations:
                room_reservations_by_room.setdefault(reservation.room_id, []).append(reservation)
                if reservation.reserved_from >= schedule_now:
                    next_room_reservations.setdefault(reservation.room_id, reservation)
                if reservation.reserved_until > schedule_now:
                    maintenance_reservation_counts[reservation.room_id] = maintenance_reservation_counts.get(reservation.room_id, 0) + 1
        context = {
            "errors": {}, "room_number": "", "description": "", "price": "",
            "selected_types": [], "room_types": room_type_options(),
            "modal_form": True, "room_modal_open": False, "service_error": None,
            "rent_modal_room": None, "rent_modal_open": False,
            "rental_started_at": None, "rental_checkout_value": "",
            "rental_error": None, "rental_edit_mode": False,
            "rental_min_checkout": None, "rental_min_checkout_input": None, "rental_max_checkout": None,
            "rental_nightly_rate": None, "rental_next_reservation": None,
            "reservation_modal_room": None, "reservation_modal_open": False,
            "reservation_modal_error": None, "reservation_errors": {},
            "reservation_form": {"guest_name": "", "guest_phone": "", "reserved_from": "", "reserved_until": ""},
            "cleaning_buffer_minutes": CLEANING_BUFFER_MINUTES,
            "rental_ready_at": None,
            "reservation_edit_mode": False, "reservation_modal_record": None,
        }
        context.update(form_context)
        return render_template(
            "room_management.html", user=user, rooms=rooms,
            room_display_values=room_display_values,
            active_room_rentals=active_room_rentals,
            room_reservations_by_room=room_reservations_by_room,
            next_room_reservations=next_room_reservations,
            maintenance_reservation_counts=maintenance_reservation_counts,
            room_count=len(rooms), all_room_count=room_count,
            room_status_filter=room_status_filter,
            room_status_counts=room_status_counts, **context,
        )

    @app.route("/rooms")
    def room_management():
        user = current_user()
        if user is None:
            return redirect(url_for("login"))
        room_status_filter = request.args.get("status", "all")
        if room_status_filter not in {"all", *ROOM_FILTER_TO_STATE}:
            room_status_filter = "all"
        return render_room_management(user, room_status_filter=room_status_filter)

    @app.route("/rooms/<room_number>/reserve", methods=["GET", "POST"])
    def reserve_room(room_number: str):
        user = current_user()
        if user is None:
            return redirect(url_for("login"))
        room = db.session.execute(
            db.select(Room).where(Room.number == str(room_number).strip())
        ).scalar_one_or_none()
        if room is None:
            flash("Không tìm thấy phòng cần đặt trước.", "error")
            return redirect(url_for("room_management"))
        if room.state == "cleaning" and room.status == "Dọn dẹp":
            flash("Không thể đặt trước khi phòng đang dọn dẹp.", "error")
            return redirect(url_for("room_management"))
        if room.state == "maintenance" and room.status == "Bảo trì":
            flash("Không thể đặt trước khi phòng đang bảo trì.", "error")
            return redirect(url_for("room_management"))
        if request.method == "GET":
            return render_room_management(
                user, reservation_modal_room=room, reservation_modal_open=True
            )

        form, errors, service_error, snapshot = validate_reservation_form(room)
        if snapshot is not None and not errors and service_error is None:
            reserved_from, reserved_until, duration, rate, total = snapshot
            try:
                db.session.add(RoomReservation(
                    room_id=room.id, room_number=room.number,
                    guest_name=form["guest_name"], guest_phone=form["guest_phone"],
                    reserved_from=reserved_from, reserved_until=reserved_until,
                    duration_minutes=duration, nightly_rate=rate, total_price=total,
                    status="booked", created_at=datetime.now().replace(second=0, microsecond=0),
                ))
                db.session.commit()
            except SQLAlchemyError:
                db.session.rollback()
                app.logger.exception("A room reservation could not be saved.")
                service_error = "Không thể lưu lịch đặt trước. Vui lòng thử lại."
                return render_room_management(
                    user, reservation_modal_room=room, reservation_modal_open=True,
                    reservation_form=form, reservation_errors=errors,
                    reservation_modal_error=service_error,
                ), 503
            flash(f"Đã đặt trước phòng {room.number} thành công.", "success")
            return redirect(url_for("room_management"))
        return render_room_management(
            user, reservation_modal_room=room, reservation_modal_open=True,
            reservation_form=form, reservation_errors=errors,
            reservation_modal_error=service_error,
        ), 400

    @app.route("/rooms/<room_number>/reservations/<int:reservation_id>/edit", methods=["GET", "POST"])
    def edit_room_reservation(room_number: str, reservation_id: int):
        user = current_user()
        if user is None:
            return redirect(url_for("login"))
        room = db.session.execute(
            db.select(Room).where(Room.number == str(room_number).strip())
        ).scalar_one_or_none()
        reservation = db.session.get(RoomReservation, reservation_id)
        if room is None or reservation is None or reservation.room_id != room.id or reservation.status != "booked":
            flash("Không tìm thấy lịch đặt trước đang hoạt động.", "error")
            return redirect(url_for("room_management"))
        if request.method == "GET":
            return render_room_management(
                user, reservation_modal_room=room, reservation_modal_open=True,
                reservation_form=reservation_form_values(reservation),
                reservation_edit_mode=True, reservation_modal_record=reservation,
            )
        form, errors, service_error, snapshot = validate_reservation_form(
            room, exclude_reservation_id=reservation.id
        )
        if snapshot is not None and not errors and service_error is None:
            reserved_from, reserved_until, duration, rate, total = snapshot
            try:
                reservation.guest_name = form["guest_name"]
                reservation.guest_phone = form["guest_phone"]
                reservation.reserved_from = reserved_from
                reservation.reserved_until = reserved_until
                reservation.duration_minutes = duration
                reservation.nightly_rate = rate
                reservation.total_price = total
                db.session.commit()
            except SQLAlchemyError:
                db.session.rollback()
                app.logger.exception("A room reservation update failed.")
                service_error = "Không thể cập nhật lịch đặt trước. Vui lòng thử lại."
                return render_room_management(
                    user, reservation_modal_room=room, reservation_modal_open=True,
                    reservation_form=form, reservation_errors=errors,
                    reservation_modal_error=service_error, reservation_edit_mode=True,
                    reservation_modal_record=reservation,
                ), 503
            flash(f"Đã cập nhật lịch đặt trước phòng {room.number}.", "success")
            return redirect(url_for("reserve_room", room_number=room.number))
        return render_room_management(
            user, reservation_modal_room=room, reservation_modal_open=True,
            reservation_form=form, reservation_errors=errors,
            reservation_modal_error=service_error, reservation_edit_mode=True,
            reservation_modal_record=reservation,
        ), 400

    @app.route("/rooms/<room_number>/reservations/<int:reservation_id>/cancel", methods=["POST"])
    def cancel_room_reservation(room_number: str, reservation_id: int):
        user = current_user()
        if user is None:
            return redirect(url_for("login"))
        room = db.session.execute(
            db.select(Room).where(Room.number == str(room_number).strip())
        ).scalar_one_or_none()
        reservation = db.session.get(RoomReservation, reservation_id)
        if room is None or reservation is None or reservation.room_id != room.id or reservation.status != "booked":
            flash("Không tìm thấy lịch đặt trước đang hoạt động.", "error")
            return redirect(url_for("room_management"))
        try:
            reservation.status = "cancelled"
            db.session.commit()
        except SQLAlchemyError:
            db.session.rollback()
            app.logger.exception("A room reservation cancellation failed.")
            flash("Không thể hủy lịch đặt trước. Vui lòng thử lại.", "error")
            return redirect(url_for("reserve_room", room_number=room.number))
        flash(f"Đã hủy lịch đặt trước phòng {room.number}.", "success")
        return redirect(url_for("reserve_room", room_number=room.number))

    @app.route("/rooms/<room_number>/rent", methods=["GET", "POST"])
    def rent_room(room_number: str):
        user = current_user()
        if user is None:
            return redirect(url_for("login"))

        normalized_number = str(room_number).strip()
        room = db.session.execute(
            db.select(Room).where(Room.number == normalized_number)
        ).scalar_one_or_none()
        if room is None:
            flash(f"Không tìm thấy phòng {normalized_number}.", "error")
            return redirect(url_for("room_management"))

        started_at = datetime.now().replace(second=0, microsecond=0)
        next_reservation = next_effective_booked_reservation(room.id, started_at)
        rental_max_checkout = (
            next_reservation.reserved_from - timedelta(minutes=CLEANING_BUFFER_MINUTES)
            if next_reservation else None
        )
        rental_ready_at = ready_after_recent_checkout(room)
        initial_checkout_value = (
            rental_max_checkout.strftime("%Y-%m-%dT%H:%M")
            if rental_max_checkout is not None and rental_max_checkout > started_at
            else ""
        )
        if request.method == "GET":
            if room.status != "Phòng trống" or room.state != "empty" or not room_service_state_is_valid(room):
                flash(f"Phòng {room.number} hiện không còn sẵn sàng để thuê.", "error")
                return redirect(url_for("room_management"))
            return render_room_management(
                user,
                rent_modal_room=room,
                rent_modal_open=True,
                rental_started_at=started_at,
                rental_checkout_value=initial_checkout_value,
                rental_next_reservation=next_reservation,
                rental_max_checkout=rental_max_checkout,
                rental_ready_at=rental_ready_at,
            )

        rental_error = None
        checkout_value = request.form.get("expected_checkout", "").strip()
        price_per_night = _room_display_values(room)["price"]
        try:
            expected_checkout = datetime.strptime(
                checkout_value, "%Y-%m-%dT%H:%M"
            )
            if expected_checkout.strftime("%Y-%m-%dT%H:%M") != checkout_value:
                raise ValueError
        except ValueError:
            expected_checkout = None
            rental_error = "Vui lòng chọn thời gian trả phòng hợp lệ."

        if room.status != "Phòng trống" or room.state != "empty" or not room_service_state_is_valid(room):
            rental_error = f"Phòng {room.number} hiện không còn sẵn sàng để thuê."
        elif price_per_night <= 0:
            rental_error = "Phòng chưa có giá thuê hợp lệ, không thể cho thuê."
        elif rental_ready_at is not None and started_at < rental_ready_at:
            rental_error = (
                f"Phòng chỉ sẵn sàng cho thuê từ {rental_ready_at.strftime('%H:%M')}; "
                f"cần chừa tối thiểu {CLEANING_BUFFER_MINUTES} phút sau lượt trước."
            )
        elif rental_max_checkout is not None and rental_max_checkout <= started_at:
            rental_error = "Không còn thời gian thuê hợp lệ trước lịch đặt tiếp theo."
        elif expected_checkout is not None and expected_checkout <= started_at:
            rental_error = "Thời gian trả phòng phải sau thời gian bắt đầu thuê."
        elif expected_checkout is not None and booked_reservations_conflicting_with_cleaning_buffer(
            room.id, started_at, expected_checkout
        ):
            rental_error = (
                f"Giờ trả phải chừa tối thiểu {CLEANING_BUFFER_MINUTES} phút trước lịch đặt tiếp theo."
                if next_reservation is not None
                else f"Phải chừa tối thiểu {CLEANING_BUFFER_MINUTES} phút để dọn dẹp giữa hai lượt khách."
            )

        if rental_error is None and expected_checkout is not None:
            duration_minutes = int(
                (expected_checkout - started_at).total_seconds() // 60
            )
            total_price = _rental_amount(price_per_night, duration_minutes)
            try:
                db.session.add(
                    RoomRental(
                        room_id=room.id,
                        room_number=room.number,
                        rented_at=started_at,
                        expected_checkout=expected_checkout,
                        duration_minutes=duration_minutes,
                        nightly_rate=price_per_night,
                        total_price=total_price,
                    )
                )
                room.status = "Đang thuê"
                room.state = "occupied"
                room.check_in = started_at.strftime("%H:%M")
                room.check_out = expected_checkout.strftime("%H:%M")
                db.session.commit()
            except SQLAlchemyError:
                db.session.rollback()
                app.logger.exception("A room rental could not be saved.")
                return render_room_management(
                    user,
                    rent_modal_room=room,
                    rent_modal_open=True,
                    rental_started_at=started_at,
                    rental_checkout_value=checkout_value,
                    rental_error="Không thể lưu lượt thuê phòng. Vui lòng thử lại.",
                    rental_max_checkout=rental_max_checkout,
                    rental_next_reservation=next_reservation,
                    rental_ready_at=rental_ready_at,
                ), 503

            flash(
                f"Đã cho thuê phòng {room.number}. "
                f"Tổng tiền: {total_price:,.0f} VNĐ.",
                "success",
            )
            return redirect(url_for("room_management"))

        return render_room_management(
            user,
            rent_modal_room=room,
            rent_modal_open=True,
            rental_started_at=started_at,
            rental_checkout_value=checkout_value,
            rental_error=rental_error,
            rental_max_checkout=rental_max_checkout,
            rental_next_reservation=next_reservation,
            rental_ready_at=rental_ready_at,
        ), 400

    @app.route("/rooms/<room_number>/rent/edit", methods=["GET", "POST"])
    def edit_room_rental(room_number: str):
        user = current_user()
        if user is None:
            return redirect(url_for("login"))

        normalized_number = str(room_number).strip()
        room = db.session.execute(
            db.select(Room).where(Room.number == normalized_number)
        ).scalar_one_or_none()
        if room is None:
            flash(f"Không tìm thấy phòng {normalized_number}.", "error")
            return redirect(url_for("room_management"))

        rental = db.session.execute(
            db.select(RoomRental)
            .where(
                RoomRental.room_id == room.id,
                RoomRental.room_number == room.number,
            )
            .order_by(RoomRental.rented_at.desc(), RoomRental.id.desc())
            .limit(1)
        ).scalar_one_or_none()
        if rental is None:
            flash(
                f"Không tìm thấy lượt thuê để điều chỉnh cho phòng {room.number}.",
                "error",
            )
            return redirect(url_for("room_management"))

        now = datetime.now().replace(second=0, microsecond=0)
        min_checkout = max(now, rental.rented_at)
        next_reservation = next_effective_booked_reservation(room.id, now)
        checkout_value = request.form.get(
            "expected_checkout",
            rental.expected_checkout.strftime("%Y-%m-%dT%H:%M"),
        ).strip()
        rental_error = None

        if request.method == "POST":
            try:
                expected_checkout = datetime.strptime(
                    checkout_value, "%Y-%m-%dT%H:%M"
                )
                if expected_checkout.strftime("%Y-%m-%dT%H:%M") != checkout_value:
                    raise ValueError
            except ValueError:
                expected_checkout = None
                rental_error = "Vui lòng chọn thời gian trả phòng hợp lệ."

            if room.status != "Đang thuê" or room.state != "occupied":
                rental_error = f"Phòng {room.number} hiện không còn được thuê."
            elif (
                expected_checkout is not None
                and expected_checkout <= min_checkout
            ):
                rental_error = "Thời gian trả phòng phải sau thời điểm hiện tại."

            if (
                rental_error is None
                and expected_checkout is not None
                and booked_reservations_conflicting_with_cleaning_buffer(
                    room.id, rental.rented_at, expected_checkout
                )
            ):
                rental_error = f"Giờ trả phải chừa tối thiểu {CLEANING_BUFFER_MINUTES} phút trước lịch đặt tiếp theo."

            if rental_error is None and expected_checkout is not None:
                duration_minutes = int(
                    (expected_checkout - rental.rented_at).total_seconds() // 60
                )
                total_price = _rental_amount(
                    rental.nightly_rate, duration_minutes
                )
                try:
                    rental.expected_checkout = expected_checkout
                    rental.duration_minutes = duration_minutes
                    rental.total_price = total_price
                    room.check_out = expected_checkout.strftime("%H:%M")
                    db.session.commit()
                except SQLAlchemyError:
                    db.session.rollback()
                    app.logger.exception("A room rental update failed.")
                    rental_error = (
                        "Không thể cập nhật thời gian trả phòng. Vui lòng thử lại."
                    )
                    return render_room_management(
                        user,
                        rent_modal_room=room,
                        rent_modal_open=True,
                        rental_started_at=rental.rented_at,
                        rental_checkout_value=checkout_value,
                        rental_error=rental_error,
                        rental_edit_mode=True,
                        rental_min_checkout=min_checkout,
                        rental_min_checkout_input=min_checkout + timedelta(minutes=1),
                        rental_max_checkout=(next_reservation.reserved_from - timedelta(minutes=CLEANING_BUFFER_MINUTES)) if next_reservation else None,
                        rental_nightly_rate=rental.nightly_rate,
                        rental_next_reservation=next_reservation,
                    ), 503

                flash(
                    f"Đã cập nhật giờ trả phòng {room.number}. "
                    f"Tổng tiền mới: {total_price:,.0f} VNĐ.",
                    "success",
                )
                return redirect(url_for("room_management"))

        return render_room_management(
            user,
            rent_modal_room=room,
            rent_modal_open=True,
            rental_started_at=rental.rented_at,
            rental_checkout_value=checkout_value,
            rental_error=rental_error,
            rental_edit_mode=True,
            rental_min_checkout=min_checkout,
            rental_min_checkout_input=min_checkout + timedelta(minutes=1),
            rental_max_checkout=(next_reservation.reserved_from - timedelta(minutes=CLEANING_BUFFER_MINUTES)) if next_reservation else None,
            rental_nightly_rate=rental.nightly_rate,
            rental_next_reservation=next_reservation,
        ), 400 if request.method == "POST" else 200
    @app.route("/rooms/<room_number>/checkout", methods=["POST"])
    def checkout_room(room_number: str):
        user = current_user()
        if user is None:
            return redirect(url_for("login"))

        normalized_number = str(room_number).strip()

        room = db.session.execute(
            db.select(Room).where(Room.number == normalized_number)
        ).scalar_one_or_none()

        if room is None:
            flash(f"Không tìm thấy phòng {normalized_number}.", "error")
            return redirect(url_for("room_management"))

        if room.status != "Đang thuê" or room.state != "occupied":
            flash(f"Phòng {room.number} hiện không được thuê.", "error")
            return redirect(url_for("room_management"))

        if not room_service_state_is_valid(room):
            flash("Không thể trả phòng vì dữ liệu dịch vụ hiện tại không nhất quán.", "error")
            return redirect(url_for("room_management"))

        transition_at = datetime.now().replace(second=0, microsecond=0)
        try:
            room.status = "Dọn dẹp"
            room.state = "cleaning"
            room.check_in = None
            room.check_out = None
            start_room_service(room, "cleaning", note=CHECKOUT_CLEANING_LOG_NOTE, started_at=transition_at)
            db.session.commit()
        except SQLAlchemyError:
            db.session.rollback()
            app.logger.exception("Room checkout and cleaning start failed.")
            flash("Không thể trả phòng. Vui lòng thử lại.", "error")
            return redirect(url_for("room_management"))
        except ValueError:
            db.session.rollback()
            flash("Không thể bắt đầu dọn dẹp do dữ liệu dịch vụ không nhất quán.", "error")
            return redirect(url_for("room_management"))

        next_reservation = next_effective_booked_reservation(room.id, transition_at)
        if (
            next_reservation is not None
            and next_reservation.reserved_from
            < transition_at + timedelta(minutes=CLEANING_BUFFER_MINUTES)
        ):
            flash(
                f"Lịch đặt tiếp theo không còn đủ {CLEANING_BUFFER_MINUTES} phút để dọn dẹp tiêu chuẩn.",
                "warning",
            )
        flash(f"Đã trả phòng {room.number}; phòng đang chờ dọn dẹp.", "success")
        return redirect(url_for("room_management"))

    def complete_room_service_transition(
        room_number: str,
        *,
        current_status: str,
        current_state: str,
        service_type: str,
        next_status: str,
        next_state: str,
        next_service_type: str | None = None,
        success_message: str,
    ):
        user = current_user()
        if user is None:
            return redirect(url_for("login"))
        normalized_number = str(room_number).strip()
        room = db.session.execute(
            db.select(Room).where(Room.number == normalized_number)
        ).scalar_one_or_none()
        if room is None:
            flash(f"Không tìm thấy phòng {normalized_number}.", "error")
            return redirect(url_for("room_management"))
        if (room.status, room.state) != (current_status, current_state):
            flash("Trạng thái phòng đã thay đổi hoặc không hợp lệ. Vui lòng tải lại.", "error")
            return redirect(url_for("room_management"))
        transition_at = datetime.now().replace(second=0, microsecond=0)
        try:
            close_active_room_service(room, service_type, ended_at=transition_at)
            if next_service_type:
                start_room_service(room, next_service_type, started_at=transition_at)
            room.status = next_status
            room.state = next_state
            room.check_in = None
            room.check_out = None
            db.session.commit()
        except ValueError:
            db.session.rollback()
            flash("Không thể hoàn tất thao tác vì nhật ký dịch vụ đang thiếu hoặc không nhất quán.", "error")
            return redirect(url_for("room_management"))
        except SQLAlchemyError:
            db.session.rollback()
            app.logger.exception("Room service completion failed.")
            flash("Không thể hoàn tất thao tác. Vui lòng thử lại.", "error")
            return redirect(url_for("room_management"))
        flash(success_message.format(room_number=room.number), "success")
        return redirect(url_for("room_management"))

    @app.route("/rooms/<room_number>/cleaning/complete", methods=["POST"])
    def complete_room_cleaning(room_number: str):
        return complete_room_service_transition(
            room_number,
            current_status="Dọn dẹp",
            current_state="cleaning",
            service_type="cleaning",
            next_status="Phòng trống",
            next_state="empty",
            success_message="Đã hoàn tất dọn dẹp phòng {room_number}.",
        )

    @app.route("/rooms/<room_number>/maintenance/complete", methods=["POST"])
    def complete_room_maintenance(room_number: str):
        return complete_room_service_transition(
            room_number,
            current_status="Bảo trì",
            current_state="maintenance",
            service_type="maintenance",
            next_status="Dọn dẹp",
            next_state="cleaning",
            next_service_type="cleaning",
            success_message="Đã hoàn tất bảo trì phòng {room_number}; phòng cần được dọn dẹp.",
        )

    @app.route("/rooms/new", methods=["GET", "POST"])
    def create_room():
        user = current_user()
        if user is None:
            return redirect(url_for("login"))

        errors: dict[str, str] = {}
        room_number = request.form.get("room_number", "").strip()
        description = request.form.get("description", "").strip()
        price_input = request.form.get("price", "").strip()
        check_in = request.form.get("check_in", "").strip()
        check_out = request.form.get("check_out", "").strip()
        selected_types = request.form.getlist("room_type")
        available_room_types = room_type_options()
        service_error: str | None = None

        if request.method == "POST":
            existing_numbers = {
                number.casefold()
                for number in db.session.execute(db.select(Room.number)).scalars()
            }
            if not room_number:
                errors["room_number"] = "Vui lòng nhập mã phòng."
            elif len(room_number) > 20 or not all(
                character.isascii()
                and (character.isalnum() or character in "-_")
                for character in room_number
            ):
                errors["room_number"] = "Mã phòng tối đa 20 ký tự, chỉ gồm chữ, số, - hoặc _."
            elif room_number.casefold() in existing_numbers:
                errors["room_number"] = "Mã phòng đã tồn tại."

            if not description:
                errors["description"] = "Vui lòng nhập mô tả ngắn."
            elif len(description) > 200:
                errors["description"] = "Mô tả không được vượt quá 200 ký tự."

            if len(selected_types) != 1 or selected_types[0] not in available_room_types:
                errors["room_type"] = "Vui lòng chọn đúng một thể loại phòng."

            try:
                price = int(price_input)
                if price <= 0:
                    raise ValueError
            except ValueError:
                errors["price"] = "Giá thuê phải là số nguyên lớn hơn 0."

            if not _valid_room_time(check_in):
                errors["check_in"] = "Giờ vào không hợp lệ. Vui lòng chọn giờ theo định dạng HH:MM."
            if not _valid_room_time(check_out):
                errors["check_out"] = "Giờ ra không hợp lệ. Vui lòng chọn giờ theo định dạng HH:MM."

            image = request.files.get("image")
            image_extension = ""
            image_data = b""
            if image is None or not image.filename:
                errors["image"] = "Vui lòng chọn hình ảnh phòng."
            else:
                safe_name = secure_filename(image.filename)
                image_extension = safe_name.rsplit(".", 1)[-1].lower() if "." in safe_name else ""
                image_data = image.read(5 * 1024 * 1024 + 1)
                signatures = ROOM_IMAGE_SIGNATURES.get(image_extension, ())
                valid_signature = any(
                    image_data.startswith(signature) for signature in signatures
                )
                if image_extension not in ALLOWED_ROOM_IMAGE_EXTENSIONS or not valid_signature:
                    errors["image"] = "Ảnh phải có định dạng JPG, PNG hoặc WEBP hợp lệ."
                elif len(image_data) > 5 * 1024 * 1024:
                    errors["image"] = "Ảnh không được vượt quá 5 MB."
                elif image_extension == "webp" and image_data[8:12] != b"WEBP":
                    errors["image"] = "Ảnh WEBP không hợp lệ."

            if not errors:
                upload_folder = Path(app.config["ROOM_UPLOAD_FOLDER"])
                image_name = f"{secrets.token_hex(16)}.{image_extension}"
                image_path = upload_folder / image_name
                try:
                    upload_folder.mkdir(parents=True, exist_ok=True)
                    image_path.write_bytes(image_data)
                    existing_positions = db.session.execute(
                        db.select(Room.position).where(Room.floor == "Phòng mới")
                    ).scalars().all()
                    db.session.add(
                        Room(
                            number=room_number,
                            floor="Phòng mới",
                            position=max(existing_positions, default=-1) + 1,
                            type=available_room_types[selected_types[0]],
                            description=description,
                            price=price,
                            image=image_name,
                            status="Phòng trống",
                            state="empty",
                            check_in=check_in or None,
                            check_out=check_out or None,
                            is_demo=False,
                        )
                    )
                    db.session.commit()
                except IntegrityError:
                    db.session.rollback()
                    image_path.unlink(missing_ok=True)
                    errors["room_number"] = "Mã phòng đã tồn tại."
                except SQLAlchemyError:
                    db.session.rollback()
                    image_path.unlink(missing_ok=True)
                    app.logger.exception("A room creation failed.")
                    service_error = "Không thể lưu phòng. Vui lòng thử lại."
                except OSError:
                    db.session.rollback()
                    image_path.unlink(missing_ok=True)
                    app.logger.exception("A room image could not be saved.")
                    service_error = "Không thể lưu hình ảnh phòng. Vui lòng thử lại."
                else:
                    flash(f"Đã thêm phòng {room_number}.", "success")
                    return redirect(url_for("room_management"))
                if service_error is not None:
                    if request.form.get("modal_form") == "1":
                        return render_room_management(
                            user,
                            errors=errors,
                            room_number=room_number,
                            description=description,
                            price=price_input,
                            selected_types=selected_types,
                            room_modal_open=True,
                            service_error=service_error,
                        ), 503
                    return render_template(
                        "room_form.html",
                        user=user,
                        errors=errors,
                        room_number=room_number,
                        description=description,
                        price=price_input,
                        selected_types=selected_types,
                        room_types=available_room_types,
                        service_error=service_error,
                    ), 503

        if request.form.get("modal_form") == "1":
            return render_room_management(
                user,
                errors=errors,
                room_number=room_number,
                description=description,
                price=price_input,
                check_in=check_in,
                check_out=check_out,
                selected_types=selected_types,
                room_modal_open=True,
            )

        return render_template(
            "room_form.html",
            user=user,
            errors=errors,
            room_number=room_number,
            description=description,
            price=price_input,
            check_in=check_in,
            check_out=check_out,
            selected_types=selected_types,
            room_types=available_room_types,
        )

    @app.route("/rooms/<room_number>/edit", methods=["GET", "POST"])
    def edit_room(room_number: str):
        user = current_user()
        if user is None:
            return redirect(url_for("login"))

        normalized_number = str(room_number).strip()
        room = db.session.execute(
            db.select(Room).where(Room.number == normalized_number)
        ).scalar_one_or_none()
        if room is None:
            flash(f"Không tìm thấy phòng {normalized_number}.", "error")
            return redirect(url_for("room_management"))
        if room.state == "occupied" or room.status == "Đang thuê":
            flash("Phòng đang được thuê; vui lòng trả phòng trước khi cập nhật.", "error")
            return redirect(url_for("room_management"))
        if ROOM_STATUS_TO_STATE.get(room.status) != room.state:
            flash("Trạng thái phòng không nhất quán; không thể cập nhật.", "error")
            return redirect(url_for("room_management"))

        current_state = room.state
        status_options_by_state = {
            "empty": [("Phòng trống", "Giữ Phòng trống"), ("Bảo trì", "Chuyển sang Bảo trì")],
            "cleaning": [("Dọn dẹp", "Giữ Dọn dẹp"), ("Bảo trì", "Chuyển sang Bảo trì")],
            "maintenance": [("Bảo trì", "Bảo trì")],
        }
        room_status_options = status_options_by_state[current_state]
        errors: dict[str, str] = {}
        room_number_input = request.form.get("room_number", room.number).strip()
        description = request.form.get("description", room.description).strip()
        price_input = request.form.get("price", str(room.price)).strip()
        check_in = request.form.get("check_in", room.check_in or "").strip()
        check_out = request.form.get("check_out", room.check_out or "").strip()
        room_status = request.form.get("status", room.status).strip()
        maintenance_note = request.form.get("maintenance_note", "").strip()
        selected_types = request.form.getlist("room_type")
        available_room_types = room_type_options()
        current_time = datetime.now().replace(second=0, microsecond=0)
        maintenance_reservation_count = len(db.session.execute(
            db.select(RoomReservation.id).where(
                RoomReservation.room_id == room.id,
                RoomReservation.status == "booked",
                RoomReservation.reserved_until > current_time,
            )
        ).scalars().all())

        if request.method == "GET":
            selected_types = [
                code
                for code, label in available_room_types.items()
                if label == room.type
            ]
            room_defaults = _room_type_defaults(room.type)
            if room_defaults is not None:
                if room.price <= 0:
                    price_input = str(room_defaults["price"])
                if not room.description:
                    description = room_defaults["description"]

        if request.method == "POST":
            existing_numbers = {
                number.casefold()
                for number in db.session.execute(
                    db.select(Room.number).where(Room.id != room.id)
                ).scalars()
            }
            if not room_number_input:
                errors["room_number"] = "Vui lòng nhập mã phòng."
            elif len(room_number_input) > 20 or not all(
                character.isascii()
                and (character.isalnum() or character in "-_")
                for character in room_number_input
            ):
                errors["room_number"] = "Mã phòng tối đa 20 ký tự, chỉ gồm chữ, số, - hoặc _."
            elif room_number_input.casefold() in existing_numbers:
                errors["room_number"] = "Mã phòng đã tồn tại."

            if not description:
                errors["description"] = "Vui lòng nhập mô tả ngắn."
            elif len(description) > 200:
                errors["description"] = "Mô tả không được vượt quá 200 ký tự."

            if len(selected_types) != 1 or selected_types[0] not in available_room_types:
                errors["room_type"] = "Vui lòng chọn đúng một thể loại phòng."

            allowed_statuses = {
                "empty": {"Phòng trống", "Bảo trì"},
                "cleaning": {"Dọn dẹp", "Bảo trì"},
                "maintenance": {"Bảo trì"},
            }[current_state]
            if room_status not in allowed_statuses:
                errors["status"] = "Trạng thái không hợp lệ với trạng thái phòng hiện tại."
            if not room_service_state_is_valid(room):
                errors["status"] = "Nhật ký dịch vụ hiện tại bị thiếu hoặc không nhất quán."
            if len(maintenance_note) > 500:
                errors["maintenance_note"] = "Lý do bảo trì không được vượt quá 500 ký tự."

            try:
                price = int(price_input)
                if price <= 0:
                    raise ValueError
            except ValueError:
                errors["price"] = "Giá thuê phải là số nguyên lớn hơn 0."

            if not _valid_room_time(check_in):
                errors["check_in"] = "Giờ vào không hợp lệ. Vui lòng chọn giờ theo định dạng HH:MM."
            if not _valid_room_time(check_out):
                errors["check_out"] = "Giờ ra không hợp lệ. Vui lòng chọn giờ theo định dạng HH:MM."

            image = request.files.get("image")
            image_data = b""
            image_extension = ""
            has_new_image = image is not None and bool(image.filename)
            if has_new_image:
                safe_name = secure_filename(image.filename)
                image_extension = safe_name.rsplit(".", 1)[-1].lower() if "." in safe_name else ""
                image_data = image.read(5 * 1024 * 1024 + 1)
                signatures = ROOM_IMAGE_SIGNATURES.get(image_extension, ())
                valid_signature = any(
                    image_data.startswith(signature) for signature in signatures
                )
                if image_extension not in ALLOWED_ROOM_IMAGE_EXTENSIONS or not valid_signature:
                    errors["image"] = "Ảnh phải có định dạng JPG, PNG hoặc WEBP hợp lệ."
                elif len(image_data) > 5 * 1024 * 1024:
                    errors["image"] = "Ảnh không được vượt quá 5 MB."
                elif image_extension == "webp" and image_data[8:12] != b"WEBP":
                    errors["image"] = "Ảnh WEBP không hợp lệ."

            if not errors:
                old_image = room.image
                new_image_name = None
                new_image_path = None
                service_error = None
                service_status = 200
                starts_maintenance = room_status == "Bảo trì" and current_state != "maintenance"
                transition_at = datetime.now().replace(second=0, microsecond=0) if starts_maintenance else None
                try:
                    if has_new_image:
                        upload_folder = Path(app.config["ROOM_UPLOAD_FOLDER"])
                        upload_folder.mkdir(parents=True, exist_ok=True)
                        new_image_name = f"{secrets.token_hex(16)}.{image_extension}"
                        new_image_path = upload_folder / new_image_name
                        new_image_path.write_bytes(image_data)
                        room.image = new_image_name

                    room.number = room_number_input
                    room.type = available_room_types[selected_types[0]]
                    room.description = description
                    room.price = price

                    if starts_maintenance:
                        if current_state == "cleaning":
                            close_active_room_service(room, "cleaning", ended_at=transition_at)
                        start_room_service(
                            room,
                            "maintenance",
                            note=maintenance_note,
                            started_at=transition_at,
                        )
                        room.check_in = None
                        room.check_out = None
                    elif current_state in {"cleaning", "maintenance"}:
                        room.check_in = None
                        room.check_out = None

                    room.status = room_status
                    room.state = ROOM_STATUS_TO_STATE[room_status]
                    if current_state == "empty" and room_status == "Phòng trống":
                        room.check_in = check_in or None
                        room.check_out = check_out or None
                    db.session.commit()
                except ValueError as error:
                    db.session.rollback()
                    if new_image_path is not None:
                        new_image_path.unlink(missing_ok=True)
                    errors["status"] = "Không thể đổi trạng thái do nhật ký dịch vụ đã thay đổi. Vui lòng tải lại."
                except IntegrityError:
                    db.session.rollback()
                    if new_image_path is not None:
                        new_image_path.unlink(missing_ok=True)
                    if starts_maintenance:
                        errors["status"] = "Phòng đã có nhật ký dịch vụ đang hoạt động. Vui lòng tải lại."
                    else:
                        errors["room_number"] = "Mã phòng đã tồn tại."
                except SQLAlchemyError:
                    db.session.rollback()
                    if new_image_path is not None:
                        new_image_path.unlink(missing_ok=True)
                    app.logger.exception("A room update failed.")
                    service_error = "Không thể cập nhật phòng. Vui lòng thử lại."
                    service_status = 503
                except OSError:
                    db.session.rollback()
                    if new_image_path is not None:
                        new_image_path.unlink(missing_ok=True)
                    app.logger.exception("A room image could not be saved.")
                    service_error = "Không thể lưu hình ảnh phòng. Vui lòng thử lại."
                    service_status = 503
                else:
                    if new_image_name and old_image and Path(old_image).name == old_image:
                        (Path(app.config["ROOM_UPLOAD_FOLDER"]) / old_image).unlink(
                            missing_ok=True
                        )
                    flash(f"Đã cập nhật phòng {room_number_input}.", "success")
                    if starts_maintenance and maintenance_reservation_count:
                        flash(
                            f"Phòng này đang có {maintenance_reservation_count} lịch đặt trước đang hiệu lực.",
                            "warning",
                        )
                    return redirect(url_for("room_management"))

        return render_template(
            "room_form.html",
            user=user,
            errors=errors,
            room_number=room_number_input,
            description=description,
            price=price_input,
            check_in=check_in,
            check_out=check_out,
            selected_types=selected_types,
            status=room_status,
            room_types=available_room_types,
            room_status_options=room_status_options,
            maintenance_note=maintenance_note,
            maintenance_reservation_count=maintenance_reservation_count,
            update_mode=True,
            edit_room_number=normalized_number,
            current_image=room.image,
            service_error=locals().get("service_error"),
        ), locals().get("service_status", 200)

    @app.route("/room-images/<path:filename>")
    def room_image(filename: str):
        if current_user() is None:
            return redirect(url_for("login"))
        return send_from_directory(app.config["ROOM_UPLOAD_FOLDER"], filename)

    @app.route("/rooms/<room_number>/delete", methods=["POST"])
    def delete_room(room_number: str):
        user = current_user()
        if user is None:
            return redirect(url_for("login"))

        normalized_number = str(room_number).strip()
        room = db.session.execute(
            db.select(Room).where(Room.number == normalized_number)
        ).scalar_one_or_none()
        if room is None:
            flash(f"Không tìm thấy phòng {normalized_number}.", "error")
            return redirect(url_for("room_management"))

        if (room.status, room.state) != ("Phòng trống", "empty"):
            flash(
                f"Chỉ có thể xóa phòng {normalized_number} khi phòng đang trống.",
                "error",
            )
            return redirect(url_for("room_management"))
        if active_room_service_logs(room.id):
            flash(f"Không thể xóa phòng {normalized_number} khi còn dịch vụ đang hoạt động.", "error")
            return redirect(url_for("room_management"))

        booked_reservation = db.session.execute(
            db.select(RoomReservation.id).where(
                RoomReservation.room_id == room.id,
                RoomReservation.status == "booked",
            ).limit(1)
        ).scalar_one_or_none()
        if booked_reservation is not None:
            flash(
                f"Không thể xóa phòng {normalized_number} vì còn lịch đặt trước đang hiệu lực. Hãy hủy hoặc hoàn tất lịch đặt trước trước.",
                "error",
            )
            return redirect(url_for("room_management"))

        image_name = room.image
        try:
            historical_reservations = db.session.execute(
                db.select(RoomReservation).where(
                    RoomReservation.room_id == room.id,
                    RoomReservation.status != "booked",
                )
            ).scalars().all()
            for reservation in historical_reservations:
                reservation.room_id = None
            historical_rentals = db.session.execute(
                db.select(RoomRental).where(RoomRental.room_id == room.id)
            ).scalars().all()
            for rental in historical_rentals:
                rental.room_id = None
            historical_service_logs = db.session.execute(
                db.select(RoomServiceLog).where(RoomServiceLog.room_id == room.id)
            ).scalars().all()
            for service_log in historical_service_logs:
                service_log.room_id = None
            db.session.delete(room)
            db.session.commit()
        except SQLAlchemyError:
            db.session.rollback()
            app.logger.exception("A room deletion failed.")
            flash("Không thể xóa phòng. Vui lòng thử lại.", "error")
            return redirect(url_for("room_management"))

        if image_name and Path(image_name).name == image_name:
            (Path(app.config["ROOM_UPLOAD_FOLDER"]) / image_name).unlink(
                missing_ok=True
            )
        flash(f"Đã xóa phòng {normalized_number}.", "success")
        return redirect(url_for("room_management"))

    @app.route("/account", methods=["GET", "POST"])
    def account():
        user = current_user()
        if user is None:
            return redirect(url_for("login"))

        errors: dict[str, str] = {}
        full_name = user.full_name
        birth_date = user.birth_date.isoformat() if user.birth_date else ""
        phone = user.phone
        avatar_upload = None

        if request.method == "POST":
            full_name = request.form.get("full_name", "").strip()
            birth_date = request.form.get("birth_date", "").strip()
            phone = request.form.get("phone", "").strip()

            if not full_name:
                errors["full_name"] = "Vui lòng nhập họ và tên."
            elif len(full_name) > 120:
                errors["full_name"] = "Họ và tên không được vượt quá 120 ký tự."

            parsed_birth_date = None
            if not birth_date:
                errors["birth_date"] = "Vui lòng chọn ngày sinh."
            else:
                try:
                    parsed_birth_date = date.fromisoformat(birth_date)
                    if parsed_birth_date.isoformat() != birth_date or parsed_birth_date > date.today():
                        raise ValueError
                except ValueError:
                    errors["birth_date"] = "Ngày sinh không hợp lệ."

            if not phone:
                errors["phone"] = "Vui lòng nhập số điện thoại."
            elif not _valid_vietnamese_phone(phone):
                errors["phone"] = "Số điện thoại không hợp lệ."

            avatar_upload = request.files.get("avatar")
            avatar_data = b""
            avatar_extension = ""
            if avatar_upload and avatar_upload.filename:
                safe_name = secure_filename(avatar_upload.filename)
                avatar_extension = safe_name.rsplit(".", 1)[-1].lower() if "." in safe_name else ""
                avatar_data = avatar_upload.read(5 * 1024 * 1024 + 1)
                signatures = PROFILE_IMAGE_SIGNATURES.get(avatar_extension, ())
                valid_signature = any(avatar_data.startswith(signature) for signature in signatures)
                if avatar_extension not in ALLOWED_ROOM_IMAGE_EXTENSIONS or not valid_signature:
                    errors["avatar"] = "Ảnh đại diện phải là JPG, PNG hoặc WEBP hợp lệ."
                elif len(avatar_data) > 5 * 1024 * 1024:
                    errors["avatar"] = "Ảnh đại diện không được vượt quá 5 MB."
                elif avatar_extension == "webp" and avatar_data[8:12] != b"WEBP":
                    errors["avatar"] = "Ảnh WEBP không hợp lệ."

            if not errors:
                old_avatar = user.avatar
                avatar_name = None
                avatar_path = None
                upload_folder = Path(app.config["ROOM_UPLOAD_FOLDER"])
                try:
                    if avatar_data:
                        avatar_name = f"profile-{secrets.token_hex(16)}.{avatar_extension}"
                        avatar_path = upload_folder / avatar_name
                        upload_folder.mkdir(parents=True, exist_ok=True)
                        avatar_path.write_bytes(avatar_data)

                    user.full_name = full_name
                    user.birth_date = parsed_birth_date
                    user.phone = phone
                    if avatar_name:
                        user.avatar = avatar_name
                    db.session.commit()
                except SQLAlchemyError:
                    db.session.rollback()
                    if avatar_path:
                        avatar_path.unlink(missing_ok=True)
                    app.logger.exception("A user profile update failed.")
                    errors["service"] = "Không thể cập nhật thông tin. Vui lòng thử lại."
                except OSError:
                    db.session.rollback()
                    if avatar_path:
                        avatar_path.unlink(missing_ok=True)
                    errors["service"] = "Không thể lưu ảnh đại diện. Vui lòng thử lại."
                else:
                    if avatar_name and old_avatar and Path(old_avatar).name == old_avatar:
                        (upload_folder / old_avatar).unlink(missing_ok=True)
                    flash("Cập nhật thông tin cá nhân thành công.", "success")
                    return redirect(url_for("account"))

        return render_template(
            "account.html",
            user=user,
            errors=errors,
            full_name=full_name,
            birth_date=birth_date,
            phone=phone,
            today=date.today().isoformat(),
        )

    @app.route("/change-password", methods=["GET", "POST"])
    def change_password():
        user = current_user()
        if user is None:
            return redirect(url_for("login"))

        errors: dict[str, str] = {}
        service_error = None

        if request.method == "POST":
            current_password = request.form.get("current_password", "")
            new_password = request.form.get("new_password", "")
            confirm_password = request.form.get("confirm_password", "")

            if not current_password:
                errors["current_password"] = "Vui lòng nhập mật khẩu hiện tại."
            else:
                try:
                    current_password_is_valid = user.check_password(current_password)
                except ValueError:
                    app.logger.error("A User record has an invalid password hash.")
                    current_password_is_valid = False
                if not current_password_is_valid:
                    errors["current_password"] = "Mật khẩu hiện tại không đúng."

            if not new_password:
                errors["new_password"] = "Vui lòng nhập mật khẩu mới."

            if not confirm_password:
                errors["confirm_password"] = "Vui lòng xác nhận mật khẩu mới."
            elif confirm_password != new_password:
                errors["confirm_password"] = "Mật khẩu xác nhận không khớp."

            if not errors:
                user.set_password(new_password)
                try:
                    db.session.commit()
                except SQLAlchemyError:
                    db.session.rollback()
                    app.logger.exception("A user password update failed.")
                    service_error = (
                        "Không thể đổi mật khẩu. Vui lòng thử lại."
                    )
                else:
                    flash("Đổi mật khẩu thành công", "success")
                    return redirect(url_for("change_password"))

        return render_template(
            "change_password.html",
            user=user,
            errors=errors,
            service_error=service_error,
        )

    @app.route("/profile-images/<path:filename>")
    def profile_image(filename: str):
        if current_user() is None:
            return redirect(url_for("login"))
        return send_from_directory(app.config["ROOM_UPLOAD_FOLDER"], filename)

    @app.route("/logout", methods=["POST"])
    def logout():
        session.clear()
        flash("Đăng xuất thành công.", "success")
        return redirect(url_for("login"))

    def room_type_page_context() -> dict[str, Any]:
        stored_room_types = db.session.execute(
            db.select(RoomType).order_by(RoomType.id)
        ).scalars().all()
        room_counts: dict[str, int] = {}
        occupied_counts: dict[str, int] = {}
        stored_rooms = db.session.execute(db.select(Room)).scalars().all()
        rooms_by_type: dict[str, list[dict[str, Any]]] = {}
        for room in stored_rooms:
            normalized_name = (room.type or "").strip().casefold()
            room_counts[normalized_name] = room_counts.get(normalized_name, 0) + 1
            rooms_by_type.setdefault(normalized_name, []).append(
                {
                    "id": room.id,
                    "number": room.number,
                    "status": room.status,
                    "occupied": room.status == "Đang thuê" or room.state == "occupied",
                }
            )
            if room.status == "Đang thuê" or room.state == "occupied":
                occupied_counts[normalized_name] = (
                    occupied_counts.get(normalized_name, 0) + 1
                )
        for rooms in rooms_by_type.values():
            rooms.sort(key=lambda room: (room["number"].casefold(), room["id"]))
        return {
            "room_types": stored_room_types,
            "room_type_rooms": {
                str(room_type.id): rooms_by_type.get(room_type.name.strip().casefold(), [])
                for room_type in stored_room_types
            },
            "room_type_counts": {
                room_type.id: room_counts.get(room_type.name.strip().casefold(), 0)
                for room_type in stored_room_types
            },
            "room_type_occupied_counts": {
                room_type.id: occupied_counts.get(
                    room_type.name.strip().casefold(), 0
                )
                for room_type in stored_room_types
            },
            "room_type_targets": [
                {"id": room_type.id, "name": room_type.name}
                for room_type in stored_room_types
            ],
        }

    @app.route("/room-types")
    def room_types():
        user = current_user()
        if user is None:
            return redirect(url_for("login"))

        return render_template(
            "room_types.html", user=user, **room_type_page_context()
        )

    @app.route("/room-types/new", methods=["GET", "POST"])
    def create_room_type():
        user = current_user()
        if user is None:
            return redirect(url_for("login"))

        errors: dict[str, str] = {}
        form_values = {
            "name": request.form.get("name", ""),
        }
        service_error = None
        service_status = 200

        if request.method == "POST":
            name = form_values["name"].strip()

            if not name:
                errors["name"] = "Vui lòng nhập tên thể loại phòng."
            elif len(name) > 120:
                errors["name"] = "Tên thể loại phòng không được vượt quá 120 ký tự."
            elif any(
                candidate.name.strip().casefold() == name.casefold()
                for candidate in db.session.execute(db.select(RoomType)).scalars()
            ):
                errors["name"] = "Tên thể loại phòng đã tồn tại."

            if not errors:
                room_type = RoomType(
                    name=name,
                    price=0,
                    quantity=0,
                    capacity="",
                    description="",
                    status="active",
                )
                db.session.add(room_type)
                try:
                    db.session.commit()
                except IntegrityError:
                    db.session.rollback()
                    errors["name"] = "Tên loại phòng đã tồn tại."
                except SQLAlchemyError:
                    db.session.rollback()
                    app.logger.error("A room type creation failed.")
                    service_error = (
                        "Hệ thống tạm thời không thể lưu thể loại phòng. Vui lòng thử lại."
                    )
                    service_status = 503
                else:
                    flash("Thêm thể loại phòng thành công.", "success")
                    return redirect(url_for("room_types"))

        return (
            render_template(
                "room_types.html",
                user=user,
                **room_type_page_context(),
                create_room_type=True,
                form_values=form_values,
                errors=errors,
                service_error=service_error,
            ),
            service_status,
        )

    @app.route("/room-types/<int:room_type_id>/delete", methods=["POST"])
    def delete_room_type(room_type_id: int):
        user = current_user()
        if user is None:
            return redirect(url_for("login"))

        room_type = db.session.get(RoomType, room_type_id)
        if room_type is None:
            flash("Không tìm thấy loại phòng cần xóa.", "error")
            return redirect(url_for("room_types"))

        room_type_name = room_type.name
        if rooms_using_room_type(room_type_name):
            flash(
                "Không thể xóa thể loại phòng này vì đang có phòng sử dụng.",
                "error",
            )
            return redirect(url_for("room_types"))

        try:
            db.session.delete(room_type)
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash(
                f'Không thể xóa thể loại phòng "{room_type_name}" vì đang được sử dụng.',
                "error",
            )
        except SQLAlchemyError:
            db.session.rollback()
            app.logger.error("A room type deletion failed.")
            flash(
                f'Hệ thống tạm thời không thể xóa thể loại phòng "{room_type_name}". Vui lòng thử lại.',
                "error",
            )
        else:
            flash(f'Đã xóa thể loại phòng "{room_type_name}" thành công.', "success")

        return redirect(url_for("room_types"))

    @app.route("/room-types/<int:room_type_id>/edit", methods=["GET", "POST"])
    def edit_room_type(room_type_id: int):
        user = current_user()
        if user is None:
            return redirect(url_for("login"))

        if request.method == "GET":
            return redirect(url_for("room_types"))

        room_type = db.session.get(RoomType, room_type_id)
        if room_type is None:
            flash("Không tìm thấy loại phòng cần cập nhật.", "error")
            return redirect(url_for("room_types"))

        errors: dict[str, str] = {}
        name_input = request.form.get("name", room_type.name)
        target_value = request.form.get("target_room_type_id", "").strip()
        submitted_ids = request.form.getlist("selected_room_ids")
        form_values = {
            "name": name_input,
            "target_room_type_id": target_value,
            "selected_room_ids": submitted_ids,
        }
        transfer_error = None
        service_error = None
        service_status = 200
        name = name_input.strip()
        name_changed = name != room_type.name
        source_rooms, selected_rooms, remaining_rooms, selection_error = (
            validate_selected_room_ids(room_type, submitted_ids)
        )
        transfer_error = selection_error

        if not name:
            errors["name"] = "Vui lòng nhập tên thể loại phòng."
        elif len(name) > 120:
            errors["name"] = "Tên thể loại phòng không được vượt quá 120 ký tự."
        elif name_changed and any(
            candidate.name.strip().casefold() == name.casefold()
            for candidate in db.session.execute(
                db.select(RoomType).where(RoomType.id != room_type.id)
            ).scalars()
        ):
            errors["name"] = "Tên thể loại phòng đã tồn tại."

        target = None
        if selected_rooms and transfer_error is None:
            try:
                target_id = int(target_value)
            except (TypeError, ValueError):
                target_id = None
            target = db.session.get(RoomType, target_id) if target_id else None
            if target is None:
                transfer_error = "Vui lòng chọn một thể loại phòng đích hợp lệ."
            elif target.id == room_type.id:
                transfer_error = "Thể loại phòng nguồn và đích phải khác nhau."

        if not errors and transfer_error is None:
            if not name_changed and not selected_rooms:
                flash("Không có thay đổi nào được thực hiện.", "info")
                return redirect(url_for("room_types"))

            previous_name = room_type.name
            try:
                if target is not None:
                    for room in selected_rooms:
                        room.type = target.name
                if name_changed:
                    for room in remaining_rooms:
                        room.type = name
                    room_type.name = name
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                errors["name"] = "Tên loại phòng đã tồn tại."
            except SQLAlchemyError:
                db.session.rollback()
                app.logger.exception("A room type update failed.")
                service_error = (
                    "Hệ thống tạm thời không thể lưu thay đổi. Vui lòng thử lại."
                )
                service_status = 503
            else:
                if target is not None and name_changed:
                    flash(
                        f'Đã đổi tên thể loại phòng "{previous_name}" thành "{name}" '
                        f'và chuyển {len(selected_rooms)} phòng sang "{target.name}".',
                        "success",
                    )
                elif target is not None:
                    flash(
                        f'Đã chuyển {len(selected_rooms)} phòng từ "{previous_name}" '
                        f'sang "{target.name}" thành công.',
                        "success",
                    )
                else:
                    flash("Cập nhật tên thể loại phòng thành công.", "success")
                return redirect(url_for("room_types"))

        return (
            render_template(
                "room_types.html",
                user=user,
                **room_type_page_context(),
                edit_room_type=room_type,
                form_values=form_values,
                errors=errors,
                transfer_error=transfer_error,
                service_error=service_error,
            ),
            service_status,
        )

    @app.route("/room-types/<int:room_type_id>/transfer", methods=["POST"])
    def transfer_room_type_rooms(room_type_id: int):
        user = current_user()
        if user is None:
            return redirect(url_for("login"))

        source = db.session.get(RoomType, room_type_id)
        if source is None:
            flash("Không tìm thấy thể loại phòng nguồn.", "error")
            return redirect(url_for("room_types"))

        target_value = request.form.get("target_room_type_id", "").strip()
        submitted_ids = request.form.getlist("selected_room_ids")
        source_rooms, selected_rooms, _remaining_rooms, transfer_error = (
            validate_selected_room_ids(source, submitted_ids)
        )
        target = None
        if selected_rooms and transfer_error is None:
            try:
                target_id = int(target_value)
            except (TypeError, ValueError):
                target_id = None
            target = db.session.get(RoomType, target_id) if target_id else None
            if target is None:
                transfer_error = "Vui lòng chọn một thể loại phòng đích hợp lệ."
            elif target.id == source.id:
                transfer_error = "Thể loại phòng nguồn và đích phải khác nhau."

        if transfer_error is None and not selected_rooms:
            flash("Không có thay đổi nào được thực hiện.", "info")
            return redirect(url_for("room_types"))

        form_values = {
            "name": source.name,
            "target_room_type_id": target_value,
            "selected_room_ids": submitted_ids,
        }
        service_error = None
        service_status = 200
        if transfer_error is None and target is not None:
            source_name = source.name
            try:
                for room in selected_rooms:
                    room.type = target.name
                db.session.commit()
            except SQLAlchemyError:
                db.session.rollback()
                app.logger.exception("A room type transfer failed.")
                service_error = (
                    "Hệ thống tạm thời không thể chuyển phòng. Vui lòng thử lại."
                )
                service_status = 503
            else:
                flash(
                    f'Đã chuyển {len(selected_rooms)} phòng từ "{source_name}" '
                    f'sang "{target.name}" thành công.',
                    "success",
                )
                return redirect(url_for("room_types"))

        return (
            render_template(
                "room_types.html",
                user=user,
                **room_type_page_context(),
                edit_room_type=source,
                form_values=form_values,
                errors={},
                transfer_error=transfer_error,
                service_error=service_error,
            ),
            service_status,
        )

    @app.errorhandler(CSRFError)
    def handle_csrf_error(_error: CSRFError):
        if request.endpoint in {"reserve_room", "edit_room_reservation", "cancel_room_reservation"}:
            user = current_user()
            if user is None:
                return redirect(url_for("login"))
            room = db.session.execute(
                db.select(Room).where(Room.number == str(request.view_args.get("room_number", "")).strip())
            ).scalar_one_or_none()
            if room is None:
                return redirect(url_for("room_management"))
            edit_mode = request.endpoint == "edit_room_reservation"
            record = db.session.get(RoomReservation, request.view_args.get("reservation_id")) if edit_mode else None
            form = {
                "guest_name": request.form.get("guest_name", ""),
                "guest_phone": request.form.get("guest_phone", ""),
                "reserved_from": request.form.get("reserved_from", ""),
                "reserved_until": request.form.get("reserved_until", ""),
            }
            if edit_mode and record is not None:
                form = reservation_form_values(record)
            return (
                render_room_management(
                    user, reservation_modal_room=room, reservation_modal_open=True,
                    reservation_form=form,
                    reservation_edit_mode=edit_mode,
                    reservation_modal_record=record,
                    reservation_modal_error="Phiên biểu mẫu không hợp lệ hoặc đã hết hạn. Vui lòng thử lại.",
                ),
                400,
            )
        if request.endpoint == "forgot_password":
            return render_template(
                "forgot_password.html",
                email=request.form.get("email", ""),
                errors={},
                service_error="Phiên biểu mẫu không hợp lệ hoặc đã hết hạn. Vui lòng thử lại.",
            ), 400
        if request.endpoint in {"verify_reset_code", "resend_reset_code"}:
            return render_template(
                "verify_reset_code.html",
                errors={"otp": "Phiên biểu mẫu không hợp lệ hoặc đã hết hạn. Vui lòng thử lại."},
            ), 400
        if request.endpoint == "reset_password":
            return render_template(
                "reset_password.html",
                errors={},
                service_error="Phiên biểu mẫu không hợp lệ hoặc đã hết hạn. Vui lòng thử lại.",
            ), 400
        if request.endpoint == "change_password":
            user = current_user()
            if user is None:
                return redirect(url_for("login"))
            return (
                render_template(
                    "change_password.html",
                    user=user,
                    errors={},
                    service_error=(
                        "Phiên biểu mẫu không hợp lệ hoặc đã hết hạn. Vui lòng thử lại."
                    ),
                ),
                400,
            )
        if request.endpoint == "create_room_type":
            user = current_user()
            return (
                render_template(
                    "room_types.html",
                    user=user,
                    **room_type_page_context(),
                    create_room_type=True,
                    form_values={
                        "name": request.form.get("name", ""),
                        "price": request.form.get("price", ""),
                        "quantity": request.form.get("quantity", "0"),
                        "capacity": request.form.get("capacity", ""),
                        "description": request.form.get("description", ""),
                        "status": request.form.get("status", "active"),
                    },
                    errors={},
                    service_error=(
                        "Phiên biểu mẫu không hợp lệ hoặc đã hết hạn. Vui lòng thử lại."
                    ),
                ),
                400,
            )
        if request.endpoint == "delete_room_type":
            user = current_user()
            return (
                render_template(
                    "room_types.html",
                    user=user,
                    **room_type_page_context(),
                    service_error=(
                        "Phiên biểu mẫu không hợp lệ hoặc đã hết hạn. Vui lòng thử lại."
                    ),
                ),
                400,
            )
        if request.endpoint in {"edit_room_type", "transfer_room_type_rooms"}:
            user = current_user()
            if user is None:
                return redirect(url_for("login"))
            room_type = db.session.get(RoomType, request.view_args["room_type_id"])
            if room_type is None:
                flash("Không tìm thấy thể loại phòng cần cập nhật.", "error")
                return redirect(url_for("room_types"))
            return (
                render_template(
                    "room_types.html",
                    user=user,
                    **room_type_page_context(),
                    edit_room_type=room_type,
                    form_values={
                        "name": request.form.get("name", room_type.name),
                        "target_room_type_id": request.form.get(
                            "target_room_type_id", ""
                        ),
                        "selected_room_ids": request.form.getlist(
                            "selected_room_ids"
                        ),
                    },
                    errors={},
                    transfer_error=None,
                    service_error=(
                        "Phiên biểu mẫu không hợp lệ hoặc đã hết hạn. Vui lòng thử lại."
                    ),
                ),
                400,
            )
        session.pop("user_id", None)
        if request.endpoint == "create_room":
            if request.form.get("modal_form") == "1":
                return (
                    render_room_management(
                        None,
                        room_modal_open=True,
                        service_error=(
                            "Phiên biểu mẫu không hợp lệ hoặc đã hết hạn. Vui lòng thử lại."
                        ),
                    ),
                    400,
                )
            return (
                render_template(
                    "room_form.html",
                    user=None,
                    errors={},
                    room_number="",
                    description="",
                    price="",
                    selected_types=[],
                    room_types=room_type_options(),
                    service_error=(
                        "Phiên biểu mẫu không hợp lệ hoặc đã hết hạn. Vui lòng thử lại."
                    ),
                ),
                400,
            )
        template_name = (
            "register.html" if request.endpoint == "register" else (
                "room_form.html" if request.endpoint == "create_room" else "login.html"
            )
        )
        return (
            render_template(
                template_name,
                email="",
                errors={},
                credential_error=None,
                service_error=(
                    "Phiên biểu mẫu không hợp lệ hoặc đã hết hạn. Vui lòng thử lại."
                ),
            ),
            400,
        )

    @app.errorhandler(SQLAlchemyError)
    def handle_database_error(_error: SQLAlchemyError):
        db.session.rollback()
        session.pop("user_id", None)
        app.logger.error("A database operation failed.")
        template_name = (
            "register.html" if request.endpoint == "register" else "login.html"
        )
        return (
            render_template(
                template_name,
                email="",
                errors={},
                credential_error=None,
                service_error=(
                    "Hệ thống tạm thời không thể xử lý yêu cầu. Vui lòng thử lại."
                ),
            ),
            503,
        )

    with app.app_context():
        db.create_all()
        user_columns = {column["name"] for column in inspect(db.engine).get_columns("users")}
        profile_columns = {
            "full_name": "VARCHAR(120) NOT NULL DEFAULT ''",
            "birth_date": "DATE",
            "phone": "VARCHAR(30) NOT NULL DEFAULT ''",
            "avatar": "VARCHAR(255)",
            "password_reset_version": "INTEGER NOT NULL DEFAULT 0",
        }
        with db.engine.begin() as connection:
            for column_name, column_definition in profile_columns.items():
                if column_name not in user_columns:
                    connection.execute(
                        text(f"ALTER TABLE users ADD COLUMN {column_name} {column_definition}")
                    )
        _seed_demo_user(app)
        _seed_room_types()
        _seed_rooms()

    return app


app = create_app()
