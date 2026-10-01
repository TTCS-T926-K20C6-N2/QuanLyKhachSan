"""Minimal Flask application for SCRUM-21 / PB-01 Login."""

from __future__ import annotations

import os
import secrets
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from flask import Flask, flash, redirect, render_template, request, send_from_directory, session, url_for
from flask_wtf.csrf import CSRFError
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from werkzeug.utils import secure_filename

from .extensions import csrf, db
from .models import RoomType, RoomTypeSeedState, User, normalize_email


PROJECT_ROOT = Path(__file__).resolve().parents[2]
INSTANCE_PATH = PROJECT_ROOT / "instance"
INVALID_CREDENTIAL_MESSAGE = "Email hoặc mật khẩu không đúng"
REGISTER_SUCCESS_MESSAGE = "Tạo tài khoản thành công. Vui lòng đăng nhập."
DEVELOPMENT_DEMO_EMAIL = "demo@example.test"
DEVELOPMENT_DEMO_PASSWORD = "Demo1@Hotel2026"
TRUE_VALUES = {"1", "true", "yes", "on"}
ROOM_TYPES = {
    "single": "Phòng đơn",
    "double": "Phòng đôi",
    "vip": "Phòng VIP",
}
ALLOWED_ROOM_IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}
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
                "number": "101", "type": "Phòng tiêu chuẩn",
                "status": "Phòng trống", "state": "empty",
                "check_in": None, "check_out": None,
            },
            {
                "number": "102", "type": "Phòng 2 giường đơn",
                "status": "Đang thuê", "state": "occupied",
                "check_in": "14:00", "check_out": "12:00",
            },
            {
                "number": "103", "type": "Phòng tiêu chuẩn",
                "status": "Phòng trống", "state": "empty",
                "check_in": None, "check_out": None,
            },
            {
                "number": "104", "type": "Phòng VIP",
                "status": "Đang thuê", "state": "occupied",
                "check_in": "15:30", "check_out": "11:30",
            },
        ),
    },
    {
        "name": "Tầng 2",
        "rooms": (
            {
                "number": "201", "type": "Phòng 1 giường đôi",
                "status": "Phòng trống", "state": "empty",
                "check_in": None, "check_out": None,
            },
            {
                "number": "202", "type": "Phòng tiêu chuẩn",
                "status": "Đang thuê", "state": "occupied",
                "check_in": "13:15", "check_out": "12:00",
            },
            {
                "number": "203", "type": "Phòng VIP",
                "status": "Phòng trống", "state": "empty",
                "check_in": None, "check_out": None,
            },
            {
                "number": "204", "type": "Phòng 2 giường đơn",
                "status": "Phòng trống", "state": "empty",
                "check_in": None, "check_out": None,
            },
        ),
    },
    {
        "name": "Tầng 3",
        "rooms": (
            {
                "number": "301", "type": "Phòng tiêu chuẩn",
                "status": "Đang thuê", "state": "occupied",
                "check_in": "14:00", "check_out": "12:00",
            },
            {
                "number": "302", "type": "Phòng VIP",
                "status": "Phòng trống", "state": "empty",
                "check_in": None, "check_out": None,
            },
            {
                "number": "303", "type": "Phòng 1 giường đôi",
                "status": "Phòng trống", "state": "empty",
                "check_in": None, "check_out": None,
            },
            {
                "number": "304", "type": "Phòng tiêu chuẩn",
                "status": "Phòng trống", "state": "empty",
                "check_in": None, "check_out": None,
            },
        ),
    },
)
ROOM_TYPE_CATALOG = (
    {
        "name": "Phòng tiêu chuẩn",
        "price": 500000,
        "quantity": 0,
        "capacity": "2 người",
        "description": "Phòng cơ bản đầy đủ tiện nghi",
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
ROOM_TYPE_STATUSES = {"active", "inactive"}


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
    if seed_state is not None and seed_state.initialized:
        return

    existing_room_type = db.session.execute(
        db.select(RoomType.id).limit(1)
    ).first()
    if existing_room_type is not None:
        seed_state = seed_state or RoomTypeSeedState(id=1)
        seed_state.initialized = True
        db.session.add(seed_state)
        db.session.commit()
        return

    seed_state = seed_state or RoomTypeSeedState(id=1)
    seed_state.initialized = True
    db.session.add_all(RoomType(**room_type) for room_type in ROOM_TYPE_CATALOG)
    db.session.add(seed_state)
    db.session.commit()


def _session_room_floors() -> list[dict[str, Any]]:
    floors = session.get("room_floors")
    if floors is None:
        floors = deepcopy(ROOM_FLOORS)

    normalized_floors: list[dict[str, Any]] = []
    for floor in floors:
        normalized_floor = dict(floor)
        normalized_floor["rooms"] = list(floor.get("rooms", ()))
        normalized_floors.append(normalized_floor)

    session["room_floors"] = normalized_floors
    return normalized_floors


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
        return redirect(url_for("room_management"))

    def render_room_management(user: User | None, **form_context):
        floors = _session_room_floors()
        room_count = sum(len(floor["rooms"]) for floor in floors)
        context = {
            "errors": {},
            "room_number": "",
            "description": "",
            "price": "",
            "selected_types": [],
            "room_types": ROOM_TYPES,
            "modal_form": True,
            "room_modal_open": False,
            "service_error": None,
        }
        context.update(form_context)
        return render_template(
            "home.html",
            user=user,
            floors=floors,
            room_count=room_count,
            **context,
        )

    @app.route("/rooms")
    def room_management():
        user = current_user()
        if user is None:
            return redirect(url_for("login"))
        return render_room_management(user)

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

        if request.method == "POST":
            floors = _session_room_floors()
            existing_numbers = {
                str(room.get("number", "")).casefold()
                for floor in floors
                for room in floor.get("rooms", [])
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

            if len(selected_types) != 1 or selected_types[0] not in ROOM_TYPES:
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
                upload_folder.mkdir(parents=True, exist_ok=True)
                image_name = f"{secrets.token_hex(16)}.{image_extension}"
                (upload_folder / image_name).write_bytes(image_data)

                new_room = {
                    "number": room_number,
                    "type": ROOM_TYPES[selected_types[0]],
                    "description": description,
                    "price": price,
                    "image": image_name,
                    "status": "Phòng trống",
                    "state": "empty",
                    "check_in": check_in or None,
                    "check_out": check_out or None,
                }
                new_floor = next(
                    (floor for floor in floors if floor["name"] == "Phòng mới"),
                    None,
                )
                if new_floor is None:
                    new_floor = {"name": "Phòng mới", "rooms": []}
                    floors.append(new_floor)
                new_floor["rooms"].append(new_room)
                session["room_floors"] = floors
                flash(f"Đã thêm phòng {room_number}.", "success")
                return redirect(url_for("room_management"))

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
            room_types=ROOM_TYPES,
        )

    @app.route("/rooms/<room_number>/edit", methods=["GET", "POST"])
    def edit_room(room_number: str):
        user = current_user()
        if user is None:
            return redirect(url_for("login"))

        normalized_number = str(room_number).strip()
        floors = _session_room_floors()
        room = next(
            (
                candidate
                for floor in floors
                for candidate in floor.get("rooms", [])
                if str(candidate.get("number")) == normalized_number
            ),
            None,
        )
        if room is None:
            flash(f"Không tìm thấy phòng {normalized_number}.", "error")
            return redirect(url_for("room_management"))

        errors: dict[str, str] = {}
        room_number_input = request.form.get("room_number", room.get("number", "")).strip()
        description = request.form.get("description", room.get("description", "")).strip()
        price_input = request.form.get("price", str(room.get("price", ""))).strip()
        check_in = request.form.get("check_in", room.get("check_in") or "").strip()
        check_out = request.form.get("check_out", room.get("check_out") or "").strip()
        selected_types = request.form.getlist("room_type")
        if request.method == "GET":
            selected_types = [
                code for code, label in ROOM_TYPES.items() if label == room.get("type")
            ]
            if not selected_types:
                room_type_label = str(room.get("type", "")).casefold()
                selected_types = [
                    "vip" if "vip" in room_type_label else (
                        "single" if "tiêu chuẩn" in room_type_label else "double"
                    )
                ]

        if request.method == "POST":
            existing_numbers = {
                str(candidate.get("number", "")).casefold()
                for floor in floors
                for candidate in floor.get("rooms", [])
                if candidate is not room
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

            if len(selected_types) != 1 or selected_types[0] not in ROOM_TYPES:
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
                old_image = room.get("image")
                room.update(
                    number=room_number_input,
                    type=ROOM_TYPES[selected_types[0]],
                    description=description,
                    price=price,
                    check_in=check_in or None,
                    check_out=check_out or None,
                )
                if has_new_image:
                    upload_folder = Path(app.config["ROOM_UPLOAD_FOLDER"])
                    upload_folder.mkdir(parents=True, exist_ok=True)
                    image_name = f"{secrets.token_hex(16)}.{image_extension}"
                    (upload_folder / image_name).write_bytes(image_data)
                    room["image"] = image_name
                    if old_image and Path(old_image).name == old_image:
                        (upload_folder / old_image).unlink(missing_ok=True)
                session["room_floors"] = floors
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
            room_types=ROOM_TYPES,
            update_mode=True,
            edit_room_number=normalized_number,
            current_image=room.get("image"),
            service_error=None,
        )

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
        floors = _session_room_floors()

        for floor in floors:
            rooms = floor.get("rooms", [])
            for index, room in enumerate(rooms):
                if str(room.get("number")) == normalized_number:
                    del rooms[index]
                    session["room_floors"] = floors
                    image_name = room.get("image")
                    if image_name and Path(image_name).name == image_name:
                        (Path(app.config["ROOM_UPLOAD_FOLDER"]) / image_name).unlink(
                            missing_ok=True
                        )
                    flash(f"Đã xóa phòng {normalized_number}.", "success")
                    return redirect(url_for("room_management"))

        flash(f"Không tìm thấy phòng {normalized_number}.", "error")
        return redirect(url_for("room_management"))

    @app.route("/account")
    def account():
        user = current_user()
        if user is None:
            return redirect(url_for("login"))
        return redirect(url_for("room_management"))

    @app.route("/logout", methods=["POST"])
    def logout():
        session.clear()
        flash("Đăng xuất thành công.", "success")
        return redirect(url_for("login"))

    @app.route("/room-types")
    def room_types():
        user = current_user()
        if user is None:
            return redirect(url_for("login"))

        stored_room_types = db.session.execute(
            db.select(RoomType).order_by(RoomType.id)
        ).scalars().all()
        return render_template(
            "room_types.html", user=user, room_types=stored_room_types
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

        room_type = db.session.get(RoomType, room_type_id)
        if room_type is None:
            flash("Không tìm thấy loại phòng cần cập nhật.", "error")
            return redirect(url_for("room_types"))

        errors: dict[str, str] = {}
        form_values = {
            "name": request.form.get("name", room_type.name),
            "price": request.form.get("price", str(room_type.price)),
            "quantity": request.form.get("quantity", str(room_type.quantity)),
            "description": request.form.get("description", room_type.description),
            "status": request.form.get("status", room_type.status),
        }
        service_error = None
        service_status = 200

        if request.method == "POST":
            name = form_values["name"].strip()
            price_input = form_values["price"].strip()
            quantity_input = form_values["quantity"].strip()

            if not name:
                errors["name"] = "Vui lòng nhập tên loại phòng."
            elif len(name) > 120:
                errors["name"] = "Tên loại phòng không được vượt quá 120 ký tự."
            elif any(
                candidate.name.casefold() == name.casefold()
                for candidate in db.session.execute(
                    db.select(RoomType).where(RoomType.id != room_type.id)
                ).scalars()
            ):
                errors["name"] = "Tên loại phòng đã tồn tại."

            try:
                price = int(price_input)
                if price <= 0 or price > 2147483647:
                    raise ValueError
            except ValueError:
                errors["price"] = "Giá phòng phải là số nguyên lớn hơn 0."

            try:
                quantity = int(quantity_input)
                if quantity < 0 or quantity > 2147483647:
                    raise ValueError
            except ValueError:
                errors["quantity"] = "Số lượng phòng phải là số nguyên không âm."

            if form_values["status"] not in ROOM_TYPE_STATUSES:
                errors["status"] = "Vui lòng chọn trạng thái hợp lệ."

            if not errors:
                room_type.name = name
                room_type.price = price
                room_type.quantity = quantity
                room_type.description = form_values["description"].strip()
                room_type.status = form_values["status"]
                try:
                    db.session.commit()
                except IntegrityError:
                    db.session.rollback()
                    errors["name"] = "Tên loại phòng đã tồn tại."
                except SQLAlchemyError:
                    db.session.rollback()
                    app.logger.error("A room type update failed.")
                    service_error = (
                        "Hệ thống tạm thời không thể lưu thay đổi. Vui lòng thử lại."
                    )
                    service_status = 503
                else:
                    flash("Cập nhật loại phòng thành công.", "success")
                    return redirect(url_for("room_types"))

        stored_room_types = db.session.execute(
            db.select(RoomType).order_by(RoomType.id)
        ).scalars().all()
        return (
            render_template(
                "room_types.html",
                user=user,
                room_types=stored_room_types,
                edit_room_type=room_type,
                form_values=form_values,
                errors=errors,
                service_error=service_error,
            ),
            service_status,
        )

    @app.errorhandler(CSRFError)
    def handle_csrf_error(_error: CSRFError):
        if request.endpoint == "delete_room_type":
            user = current_user()
            stored_room_types = db.session.execute(
                db.select(RoomType).order_by(RoomType.id)
            ).scalars().all()
            return (
                render_template(
                    "room_types.html",
                    user=user,
                    room_types=stored_room_types,
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
                    room_types=ROOM_TYPES,
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
        _seed_demo_user(app)
        _seed_room_types()

    return app


app = create_app()