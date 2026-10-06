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
    RoomSeedState,
    RoomType,
    RoomTypeSeedState,
    PasswordResetChallenge,
    User,
    normalize_email,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
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


ROOM_STATUS_ORDER = ("Phòng trống", "Đang thuê")


def _room_status_counts(rooms: list[Room]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for room in rooms:
        status = (room.status or "").strip()
        if not status:
            continue
        counts[status] = counts.get(status, 0) + 1

    ordered_counts: dict[str, int] = {}
    for status in ROOM_STATUS_ORDER:
        if status in counts:
            ordered_counts[status] = counts[status]
    for status, count in counts.items():
        if status not in ordered_counts:
            ordered_counts[status] = count
    return ordered_counts


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
        status_by_filter = {
            "empty": "Phòng trống",
            "occupied": "Đang thuê",
        }
        selected_status = status_by_filter.get(room_status_filter)
        rooms = (
            [room for room in all_rooms if room.status == selected_status]
            if selected_status
            else all_rooms
        )
        room_display_values = {
            room.id: _room_display_values(room)
            for room in rooms
        }
        room_ids = [room.id for room in rooms]
        active_room_rentals = {}
        if room_ids:
            rentals = db.session.execute(
                db.select(RoomRental)
                .where(RoomRental.room_id.in_(room_ids))
                .order_by(RoomRental.rented_at.desc(), RoomRental.id.desc())
            ).scalars()
            for rental in rentals:
                active_room_rentals.setdefault(rental.room_id, rental)
        context = {
            "errors": {},
            "room_number": "",
            "description": "",
            "price": "",
            "selected_types": [],
            "room_types": room_type_options(),
            "modal_form": True,
            "room_modal_open": False,
            "service_error": None,
            "rent_modal_room": None,
            "rent_modal_open": False,
            "rental_started_at": None,
            "rental_checkout_value": "",
            "rental_error": None,
            "rental_edit_mode": False,
            "rental_min_checkout": None,
        }
        context.update(form_context)
        return render_template(
            "room_management.html",
            user=user,
            rooms=rooms,
            room_display_values=room_display_values,
            active_room_rentals=active_room_rentals,
            room_count=len(rooms),
            all_room_count=room_count,
            room_status_filter=room_status_filter,
            room_status_counts=room_status_counts,
            **context,
        )

    @app.route("/rooms")
    def room_management():
        user = current_user()
        if user is None:
            return redirect(url_for("login"))
        room_status_filter = request.args.get("status", "all")
        if room_status_filter not in {"all", "empty", "occupied"}:
            room_status_filter = "all"
        return render_room_management(user, room_status_filter=room_status_filter)

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
        if request.method == "GET":
            if room.status != "Phòng trống" or room.state != "empty":
                flash(f"Phòng {room.number} hiện không còn trống.", "error")
                return redirect(url_for("room_management"))
            return render_room_management(
                user,
                rent_modal_room=room,
                rent_modal_open=True,
                rental_started_at=started_at,
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

        if room.status != "Phòng trống" or room.state != "empty":
            rental_error = f"Phòng {room.number} hiện không còn trống."
        elif price_per_night <= 0:
            rental_error = "Phòng chưa có giá thuê hợp lệ, không thể cho thuê."
        elif expected_checkout is not None and expected_checkout <= started_at:
            rental_error = "Thời gian trả phòng phải sau thời gian bắt đầu thuê."

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
        ), 400 if request.method == "POST" else 200

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

        errors: dict[str, str] = {}
        room_number_input = request.form.get("room_number", room.number).strip()
        description = request.form.get("description", room.description).strip()
        price_input = request.form.get("price", str(room.price)).strip()
        check_in = request.form.get("check_in", room.check_in or "").strip()
        check_out = request.form.get("check_out", room.check_out or "").strip()
        room_status = request.form.get("status", room.status).strip()
        selected_types = request.form.getlist("room_type")
        available_room_types = room_type_options()
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

            if room_status not in {"Phòng trống", "Đang thuê"}:
                errors["status"] = "Vui lòng chọn trạng thái phòng hợp lệ."

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
                    room.status = room_status
                    room.state = "occupied" if room_status == "Đang thuê" else "empty"
                    room.check_in = check_in or None
                    room.check_out = check_out or None
                    db.session.commit()
                except IntegrityError:
                    db.session.rollback()
                    if new_image_path is not None:
                        new_image_path.unlink(missing_ok=True)
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

        if room.status == "Đang thuê" or room.state == "occupied":
            flash(
                f"Không thể xóa phòng {normalized_number} đang được thuê.",
                "error",
            )
            return redirect(url_for("room_management"))

        image_name = room.image
        try:
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

            digits_only = re.sub(r"\D", "", phone)
            if not phone:
                errors["phone"] = "Vui lòng nhập số điện thoại."
            elif not re.fullmatch(r"(?:0(?:3|5|7|8|9)\d{8}|84\d{9})", digits_only):
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
        for room in stored_rooms:
            normalized_name = (room.type or "").strip().casefold()
            room_counts[normalized_name] = room_counts.get(normalized_name, 0) + 1
            if room.status == "Đang thuê" or room.state == "occupied":
                occupied_counts[normalized_name] = (
                    occupied_counts.get(normalized_name, 0) + 1
                )
        return {
            "room_types": stored_room_types,
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
        form_values = {
            "name": name_input,
            "target_room_type_id": target_value,
        }
        transfer_error = None
        service_error = None
        service_status = 200

        if request.method == "POST":
            name = name_input.strip()
            name_changed = name != room_type.name
            target = None

            if name_changed:
                if not name:
                    errors["name"] = "Vui lòng nhập tên thể loại phòng."
                elif len(name) > 120:
                    errors["name"] = "Tên thể loại phòng không được vượt quá 120 ký tự."
                elif any(
                    candidate.name.strip().casefold() == name.casefold()
                    for candidate in db.session.execute(
                        db.select(RoomType).where(RoomType.id != room_type.id)
                    ).scalars()
                ):
                    errors["name"] = "Tên thể loại phòng đã tồn tại."

            if target_value:
                try:
                    target_id = int(target_value)
                except ValueError:
                    target_id = None
                target = db.session.get(RoomType, target_id) if target_id else None
                if target is None:
                    transfer_error = "Vui lòng chọn một thể loại phòng đích hợp lệ."
                elif target.id == room_type.id:
                    transfer_error = "Thể loại phòng nguồn và đích phải khác nhau."

            previous_name = room_type.name
            rooms_to_update = (
                rooms_using_room_type(previous_name)
                if name_changed or target is not None
                else []
            )
            if target is not None and not rooms_to_update:
                transfer_error = "Không có phòng thuộc thể loại này để chuyển."

            if not errors and transfer_error is None:
                if not name_changed and target is None:
                    flash("Không có thay đổi nào được thực hiện.", "info")
                    return redirect(url_for("room_types"))

                room_count = len(rooms_to_update)
                try:
                    if target is not None:
                        for room in rooms_to_update:
                            room.type = target.name
                    elif name_changed:
                        for room in rooms_to_update:
                            room.type = name
                    if name_changed:
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
                            f'và chuyển {room_count} phòng sang "{target.name}".',
                            "success",
                        )
                    elif target is not None:
                        flash(
                            f'Đã chuyển {room_count} phòng từ "{previous_name}" '
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

        target_value = request.form.get("target_room_type_id", "")
        try:
            target_id = int(target_value)
        except (TypeError, ValueError):
            target_id = None
        target = db.session.get(RoomType, target_id) if target_id else None
        rooms_to_transfer = rooms_using_room_type(source.name)
        occupied_count = sum(
            room.status == "Đang thuê" or room.state == "occupied"
            for room in rooms_to_transfer
        )
        transfer_error = None
        if target is None:
            transfer_error = "Vui lòng chọn một thể loại phòng đích hợp lệ."
        elif target.id == source.id:
            transfer_error = "Thể loại phòng nguồn và đích phải khác nhau."
        elif not rooms_to_transfer:
            transfer_error = "Không có phòng thuộc thể loại này để chuyển."

        form_values = {
            "name": source.name,
            "target_room_type_id": target_value,
        }
        service_error = None
        service_status = 200
        if transfer_error is None:
            source_name = source.name
            target_name = target.name
            room_count = len(rooms_to_transfer)
            try:
                for room in rooms_to_transfer:
                    room.type = target_name
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
                    f'Đã chuyển {room_count} phòng từ "{source_name}" '
                    f'sang "{target_name}" thành công.',
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
