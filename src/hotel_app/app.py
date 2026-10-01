"""Minimal Flask application for SCRUM-21 / PB-01 Login."""

from __future__ import annotations

import os
import secrets
from copy import deepcopy
from datetime import timedelta
from pathlib import Path
from typing import Any

from flask import Flask, flash, redirect, render_template, request, send_from_directory, session, url_for
from flask_wtf.csrf import CSRFError
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from werkzeug.utils import secure_filename

from .extensions import csrf, db
from .models import User, normalize_email


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
        "price": "500,000 VNĐ",
        "capacity": "2 người",
        "description": "Phòng cơ bản đầy đủ tiện nghi",
    },
    {
        "name": "Phòng VIP",
        "price": "1,200,000 VNĐ",
        "capacity": "4 người",
        "description": "Phòng rộng, view biển, có bồn tắm",
    },
)


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
                    "check_in": None,
                    "check_out": None,
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
            selected_types=selected_types,
            room_types=ROOM_TYPES,
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

        return render_template("room_types.html", user=user, room_types=ROOM_TYPE_CATALOG)

    @app.errorhandler(CSRFError)
    def handle_csrf_error(_error: CSRFError):
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

    return app


app = create_app()