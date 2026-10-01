"""Acceptance tests for the room type search page."""

from __future__ import annotations

import re
from html import unescape
from io import BytesIO

import pytest
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from conftest import DEMO_EMAIL, DEMO_PASSWORD, create_app
from hotel_app.extensions import db
from hotel_app.models import RoomType


def _csrf_token(client) -> str:
    response = client.get("/login")
    match = re.search(
        r'name="csrf_token"[^>]*value="([^"]+)"',
        response.get_data(as_text=True),
    )
    assert match is not None
    return match.group(1)


def _login(client):
    return client.post(
        "/login",
        data={
            "csrf_token": _csrf_token(client),
            "email": DEMO_EMAIL,
            "password": DEMO_PASSWORD,
        },
    )


def test_room_types_requires_login(client):
    response = client.get("/room-types")

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/login")

    edit_response = client.get("/room-types/1/edit")
    assert edit_response.status_code == 302
    assert edit_response.headers["Location"].endswith("/login")


def test_room_management_requires_login(client):
    response = client.get("/rooms")

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/login")


def test_create_room_requires_login(client):
    response = client.get("/rooms/new")

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/login")


def test_edit_room_requires_login(client):
    response = client.get("/rooms/101/edit")

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/login")


def test_create_room_form_has_required_fields_and_checkbox_types(client):
    assert _login(client).status_code == 302

    html = client.get("/rooms/new").get_data(as_text=True)

    assert "Thêm phòng mới" in html
    assert "Thêm mới" not in html
    assert 'href="/rooms" aria-current="page"' in html
    assert 'enctype="multipart/form-data"' in html
    assert 'name="room_number"' in html and " required" in html
    assert 'name="description"' in html
    assert 'name="price"' in html
    assert html.count('type="radio" name="room_type"') == 3
    assert html.count('type="radio"') == 3
    assert 'name="check_in" type="time"' in html
    assert 'name="check_out" type="time"' in html
    assert 'name="image" type="file"' in html


def test_room_list_opens_add_form_as_modal(client):
    assert _login(client).status_code == 302

    html = client.get("/rooms").get_data(as_text=True)

    assert 'id="open-room-dialog"' in html
    assert '<dialog class="room-dialog" id="room-dialog"' in html
    assert 'id="room-dialog-title">Thêm phòng mới</h2>' in html
    assert 'href="/rooms/new"' in html


def test_modal_validation_keeps_room_list_visible_and_reopens_dialog(client):
    assert _login(client).status_code == 302
    html = client.get("/rooms").get_data(as_text=True)
    csrf_token = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', html)
    assert csrf_token is not None

    response = client.post(
        "/rooms/new",
        data={
            "csrf_token": csrf_token.group(1),
            "modal_form": "1",
            "room_number": "407",
            "description": "",
            "price": "0",
            "room_type": [],
        },
        content_type="multipart/form-data",
    )
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'data-open-on-load' in html
    assert 'id="room-list"' in html
    assert "Vui lòng nhập mô tả ngắn." in html
    assert "Vui lòng chọn hình ảnh phòng." in html


def test_room_types_page_shows_type_management_table(client):
    assert _login(client).status_code == 302

    response = client.get("/room-types")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Quản lý Thể loại phòng" in html
    assert "Danh sách thể loại phòng" in html
    assert "Tên thể loại phòng" in html
    assert "Đơn giá / đêm" in html
    assert "Số lượng phòng" in html
    assert "Sức chứa" in html
    assert "Trạng thái" in html
    assert "Phòng tiêu chuẩn" in html
    assert "500,000 VNĐ" in html
    assert "Phòng VIP" in html
    assert "1,200,000 VNĐ" in html
    assert 'name="room_type"' not in html


def test_room_type_management_exposes_edit_and_delete_actions(client):
    assert _login(client).status_code == 302

    html = client.get("/room-types").get_data(as_text=True)

    assert 'class="action-button action-button--primary room-type-add" href="/room-types/new"' in html
    assert html.count('class="action-button action-button--edit" href="/room-types/') == 2
    assert html.count('class="action-button action-button--delete" type="submit"') == 2
    assert html.count('name="csrf_token"') == 3
    assert "window.confirm(this.dataset.confirm)" in html
    assert 'data-confirm="Bạn có chắc chắn muốn xóa thể loại phòng: Phòng tiêu chuẩn?"' in html
    assert 'data-confirm="Bạn có chắc chắn muốn xóa thể loại phòng: Phòng VIP?"' in html


def test_create_room_type_form_is_available_to_logged_in_user(client):
    assert _login(client).status_code == 302

    response = client.get("/room-types/new")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'action="/room-types/new"' in html
    assert 'name="csrf_token"' in html
    assert 'id="room-type-capacity" name="capacity"' in html
    assert "Thêm thể loại phòng" in html


def test_create_room_type_persists_and_updates_listing(client, app):
    assert _login(client).status_code == 302
    form_html = client.get("/room-types/new").get_data(as_text=True)
    csrf_token = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', form_html)
    assert csrf_token is not None

    response = client.post(
        "/room-types/new",
        data={
            "csrf_token": csrf_token.group(1),
            "name": "Phòng gia đình",
            "price": "950000",
            "quantity": "6",
            "capacity": "5 người",
            "description": "Phòng dành cho gia đình.",
            "status": "active",
        },
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/room-types")
    html = client.get("/room-types").get_data(as_text=True)
    assert "Thêm thể loại phòng thành công." in html
    assert "Phòng gia đình" in html
    assert "950,000 VNĐ" in html
    with app.app_context():
        created = db.session.execute(
            db.select(RoomType).where(RoomType.name == "Phòng gia đình")
        ).scalar_one()
        assert created.quantity == 6
        assert created.capacity == "5 người"
        assert created.description == "Phòng dành cho gia đình."


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("name", "Phòng VIP", "Tên loại phòng đã tồn tại."),
        ("price", "0", "Giá phòng phải là số nguyên lớn hơn 0."),
        ("quantity", "-1", "Số lượng phòng phải là số nguyên không âm."),
        ("capacity", "", "Vui lòng nhập sức chứa."),
        ("status", "paused", "Vui lòng chọn trạng thái hợp lệ."),
    ],
)
def test_invalid_room_type_creation_keeps_form_values(client, field, value, message):
    assert _login(client).status_code == 302
    form_html = client.get("/room-types/new").get_data(as_text=True)
    csrf_token = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', form_html)
    assert csrf_token is not None
    data = {
        "csrf_token": csrf_token.group(1),
        "name": "Phòng thử nghiệm",
        "price": "800000",
        "quantity": "2",
        "capacity": "3 người",
        "description": "Mô tả thử nghiệm",
        "status": "active",
    }
    data[field] = value

    response = client.post("/room-types/new", data=data)
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert message in html
    assert "Phòng thử nghiệm" in html or field == "name"


def test_create_room_type_requires_login_and_csrf(client, app):
    response = client.post(
        "/room-types/new",
        data={"csrf_token": _csrf_token(client), "name": "Không được thêm"},
    )
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/login")

    with app.app_context():
        assert db.session.execute(
            db.select(RoomType).where(RoomType.name == "Không được thêm")
        ).scalar_one_or_none() is None

    assert _login(client).status_code == 302
    response = client.post("/room-types/new", data={"name": "Thiếu CSRF"})
    assert response.status_code == 400
    with app.app_context():
        assert db.session.execute(
            db.select(RoomType).where(RoomType.name == "Thiếu CSRF")
        ).scalar_one_or_none() is None


def test_canceling_room_type_delete_keeps_record(client, app):
    assert _login(client).status_code == 302

    listing = client.get("/room-types").get_data(as_text=True)
    assert 'data-confirm="Bạn có chắc chắn muốn xóa thể loại phòng: Phòng tiêu chuẩn?"' in listing

    with app.app_context():
        stored = db.session.get(RoomType, 1)
        assert stored is not None
        assert stored.name == "Phòng tiêu chuẩn"


def test_room_type_delete_removes_record_and_updates_listing(client, app):
    assert _login(client).status_code == 302
    listing = client.get("/room-types").get_data(as_text=True)
    csrf_token = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', listing)
    assert csrf_token is not None

    response = client.post(
        "/room-types/1/delete",
        data={"csrf_token": csrf_token.group(1)},
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/room-types")
    html = client.get("/room-types").get_data(as_text=True)
    assert 'Đã xóa thể loại phòng "Phòng tiêu chuẩn" thành công.' in unescape(html)
    assert 'href="/room-types/1/edit"' not in html
    assert "Phòng VIP" in html
    with app.app_context():
        assert db.session.get(RoomType, 1) is None
        assert db.session.get(RoomType, 2) is not None


def test_room_type_delete_requires_login(client, app):
    response = client.post(
        "/room-types/1/delete",
        data={"csrf_token": _csrf_token(client)},
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/login")
    with app.app_context():
        assert db.session.get(RoomType, 1) is not None


def test_room_type_delete_reports_missing_record(client, app):
    assert _login(client).status_code == 302
    listing = client.get("/room-types").get_data(as_text=True)
    csrf_token = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', listing)
    assert csrf_token is not None
    response = client.post(
        "/room-types/999/delete",
        data={"csrf_token": csrf_token.group(1)},
    )

    assert response.status_code == 302
    html = client.get("/room-types").get_data(as_text=True)
    assert "Không tìm thấy loại phòng cần xóa." in html
    with app.app_context():
        assert db.session.get(RoomType, 1) is not None


def test_room_type_delete_rejects_get(client, app):
    assert _login(client).status_code == 302

    response = client.get("/room-types/1/delete")

    assert response.status_code == 405
    with app.app_context():
        assert db.session.get(RoomType, 1) is not None


def test_room_type_delete_requires_csrf_and_preserves_login(client, app):
    assert _login(client).status_code == 302

    response = client.post("/room-types/1/delete")

    assert response.status_code == 400
    assert "Phiên biểu mẫu không hợp lệ hoặc đã hết hạn." in response.get_data(as_text=True)
    assert client.get("/room-types").status_code == 200
    with app.app_context():
        assert db.session.get(RoomType, 1) is not None


def test_room_type_delete_rolls_back_on_database_error(client, app, monkeypatch):
    assert _login(client).status_code == 302
    listing = client.get("/room-types").get_data(as_text=True)
    csrf_token = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', listing)
    assert csrf_token is not None

    def fail_commit(_session):
        raise SQLAlchemyError("simulated database failure")

    monkeypatch.setattr(Session, "commit", fail_commit)

    response = client.post(
        "/room-types/1/delete",
        data={"csrf_token": csrf_token.group(1)},
    )

    assert response.status_code == 302
    html = client.get("/room-types").get_data(as_text=True)
    assert "Hệ thống tạm thời không thể xóa thể loại phòng" in html
    with app.app_context():
        assert db.session.get(RoomType, 1) is not None


def test_deleting_all_room_types_stays_empty_after_restart(app, client):
    assert _login(client).status_code == 302
    listing = client.get("/room-types").get_data(as_text=True)
    csrf_token = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', listing)
    assert csrf_token is not None

    for room_type_id in (1, 2):
        response = client.post(
            f"/room-types/{room_type_id}/delete",
            data={"csrf_token": csrf_token.group(1)},
        )
        assert response.status_code == 302

    restarted_app = create_app(
        {
            "APP_ENV": "testing",
            "TESTING": True,
            "SECRET_KEY": "test-only-secret-key",
            "SQLALCHEMY_DATABASE_URI": app.config["SQLALCHEMY_DATABASE_URI"],
        }
    )
    with restarted_app.app_context():
        assert db.session.execute(db.select(RoomType)).scalars().all() == []


def test_room_type_edit_form_contains_current_values(client):
    assert _login(client).status_code == 302

    listing = client.get("/room-types").get_data(as_text=True)
    assert 'href="/room-types/1/edit"' in listing
    response = client.get("/room-types/1/edit")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'action="/room-types/1/edit"' in html
    assert 'id="room-type-name" name="name" type="text" maxlength="120" value="Phòng tiêu chuẩn"' in html
    assert 'id="room-type-price" name="price" type="number" min="1" step="1" value="500000"' in html
    assert 'id="room-type-quantity" name="quantity" type="number" min="0" step="1" value="0"' in html
    assert '<textarea id="room-type-description" name="description" rows="3">Phòng cơ bản đầy đủ tiện nghi</textarea>' in html
    assert '<option value="active" selected>Đang kinh doanh</option>' in html
    assert "2 người" in html
    assert "Hủy" in html and "Lưu thay đổi" in html


def test_room_type_update_persists_and_updates_listing(client, app):
    assert _login(client).status_code == 302
    form_html = client.get("/room-types/1/edit").get_data(as_text=True)
    csrf_token = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', form_html)
    assert csrf_token is not None

    response = client.post(
        "/room-types/1/edit",
        data={
            "csrf_token": csrf_token.group(1),
            "name": "Phòng tiêu chuẩn Plus",
            "price": "725000",
            "quantity": "18",
            "description": "Đã nâng cấp đầy đủ tiện nghi.",
            "status": "inactive",
        },
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/room-types")
    html = client.get("/room-types").get_data(as_text=True)
    assert "Cập nhật loại phòng thành công." in html
    assert "Phòng tiêu chuẩn Plus" in html
    assert "725,000 VNĐ" in html
    assert "18" in html
    assert "Đã nâng cấp đầy đủ tiện nghi." in html
    assert "Ngừng kinh doanh" in html
    assert "2 người" in html

    restarted_app = create_app(
        {
            "APP_ENV": "testing",
            "TESTING": True,
            "SECRET_KEY": "test-only-secret-key",
            "SQLALCHEMY_DATABASE_URI": app.config["SQLALCHEMY_DATABASE_URI"],
        }
    )
    with restarted_app.app_context():
        persisted = db.session.get(RoomType, 1)
        assert persisted is not None
        assert persisted.name == "Phòng tiêu chuẩn Plus"
        assert persisted.price == 725000
        assert persisted.quantity == 18
        assert persisted.status == "inactive"
        assert persisted.capacity == "2 người"


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("name", "   ", "Vui lòng nhập tên loại phòng."),
        ("price", "0", "Giá phòng phải là số nguyên lớn hơn 0."),
        ("price", "abc", "Giá phòng phải là số nguyên lớn hơn 0."),
        ("quantity", "-1", "Số lượng phòng phải là số nguyên không âm."),
        ("quantity", "abc", "Số lượng phòng phải là số nguyên không âm."),
        ("status", "paused", "Vui lòng chọn trạng thái hợp lệ."),
    ],
)
def test_invalid_room_type_update_keeps_input_and_does_not_save(
    client, app, field, value, message
):
    assert _login(client).status_code == 302
    form_html = client.get("/room-types/1/edit").get_data(as_text=True)
    csrf_token = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', form_html)
    assert csrf_token is not None
    data = {
        "csrf_token": csrf_token.group(1),
        "name": "Không được lưu",
        "price": "800000",
        "quantity": "12",
        "description": "Dữ liệu nhập thử",
        "status": "active",
    }
    data[field] = value

    response = client.post("/room-types/1/edit", data=data)
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert message in html
    assert value in html
    with app.app_context():
        stored = db.session.get(RoomType, 1)
        assert stored is not None
        assert stored.name == "Phòng tiêu chuẩn"
        assert stored.price == 500000
        assert stored.quantity == 0
        assert stored.description == "Phòng cơ bản đầy đủ tiện nghi"
        assert stored.status == "active"


def test_room_cards_stay_on_room_management_page(client):
    assert _login(client).status_code == 302

    room_types_page = client.get("/room-types").get_data(as_text=True)
    room_management_page = client.get("/rooms").get_data(as_text=True)

    assert "Phòng 101" not in room_types_page
    assert 'aria-label="Phòng 101, Phòng trống"' in room_management_page
    assert 'aria-label="Phòng 102, Đang thuê"' in room_management_page
    assert 'href="/rooms" aria-current="page"' in room_management_page
    assert 'class="room-grid"' in room_management_page
    assert "Giờ vào" in room_management_page
    assert "Giờ ra" in room_management_page
    assert "14:00" in room_management_page
    assert "room-card--empty" in room_management_page
    assert "room-card--occupied" in room_management_page
    assert "Tổng quan / Sơ đồ phòng" not in room_management_page
    assert 'href="/" aria-current="page"' not in room_management_page


def test_room_delete_removes_room_from_management_page(client):
    assert _login(client).status_code == 302

    room_management_page = client.get("/rooms").get_data(as_text=True)
    csrf_token = re.search(
        r'name="csrf_token"[^>]*value="([^"]+)"',
        room_management_page,
    )
    assert csrf_token is not None

    response = client.post(
        "/rooms/101/delete",
        data={"csrf_token": csrf_token.group(1)},
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/rooms")

    room_management_page = client.get("/rooms").get_data(as_text=True)
    assert 'aria-label="Phòng 101, Phòng trống"' not in room_management_page
    assert 'aria-label="Phòng 102, Đang thuê"' in room_management_page


def test_room_list_has_update_link_and_edit_form_is_prefilled(client):
    assert _login(client).status_code == 302

    room_management_page = client.get("/rooms").get_data(as_text=True)
    assert 'href="/rooms/101/edit"' in room_management_page
    assert "Cập nhật" in room_management_page

    edit_page = client.get("/rooms/101/edit").get_data(as_text=True)
    assert "Cập nhật phòng" in edit_page
    assert 'action="/rooms/101/edit"' in edit_page
    assert 'name="room_number" type="text" value="101"' in edit_page
    assert re.search(r'value="single"[^>]*checked', edit_page)
    assert 'name="image" type="file"' in edit_page
    assert 'name="image" type="file" required' not in edit_page

    occupied_edit_page = client.get("/rooms/102/edit").get_data(as_text=True)
    assert 'name="check_in" type="time" value="14:00"' in occupied_edit_page
    assert 'name="check_out" type="time" value="12:00"' in occupied_edit_page


def test_edit_room_updates_check_in_and_check_out(client):
    assert _login(client).status_code == 302
    form_html = client.get("/rooms/102/edit").get_data(as_text=True)
    csrf_token = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', form_html)
    assert csrf_token is not None

    response = client.post(
        "/rooms/102/edit",
        data={
            "csrf_token": csrf_token.group(1),
            "room_number": "102",
            "description": "Phòng đang thuê",
            "price": "650000",
            "room_type": "double",
            "check_in": "16:30",
            "check_out": "10:30",
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 302
    html = client.get("/rooms").get_data(as_text=True)
    assert 'aria-label="Phòng 102, Đang thuê"' in html
    assert html.count("16:30") >= 1
    assert html.count("10:30") >= 1


def test_edit_room_validates_required_fields(client):
    assert _login(client).status_code == 302
    form_html = client.get("/rooms/101/edit").get_data(as_text=True)
    csrf_token = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', form_html)
    assert csrf_token is not None

    response = client.post(
        "/rooms/101/edit",
        data={
            "csrf_token": csrf_token.group(1),
            "room_number": "101",
            "description": "",
            "price": "0",
            "room_type": [],
            "image": (BytesIO(b"not an image"), "room.txt"),
        },
        content_type="multipart/form-data",
    )
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Vui lòng nhập mô tả ngắn." in html
    assert "Giá thuê phải là số nguyên lớn hơn 0." in html
    assert "Vui lòng chọn đúng một thể loại phòng." in html
    assert "Ảnh phải có định dạng JPG, PNG hoặc WEBP hợp lệ." in html


def test_edit_room_updates_data_uploads_image_and_flashes_success(client):
    assert _login(client).status_code == 302
    form_html = client.get("/rooms/101/edit").get_data(as_text=True)
    csrf_token = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', form_html)
    assert csrf_token is not None

    response = client.post(
        "/rooms/101/edit",
        data={
            "csrf_token": csrf_token.group(1),
            "room_number": "101A",
            "description": "Phòng đã được cập nhật",
            "price": "900000",
            "room_type": "vip",
            "image": (BytesIO(b"\x89PNG\r\n\x1a\nupdated image"), "updated.png"),
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/rooms")
    html = client.get("/rooms").get_data(as_text=True)
    assert "Đã cập nhật phòng 101A." in html
    assert 'aria-label="Phòng 101A, Phòng trống"' in html
    assert "Phòng VIP" in html
    assert "Phòng đã được cập nhật" in html
    assert "900,000 VNĐ / đêm" in html
    image_url = re.search(r'src="(/room-images/[^\"]+)" alt="Ảnh phòng 101A"', html)
    assert image_url is not None
    assert client.get(image_url.group(1)).data.startswith(b"\x89PNG\r\n\x1a\n")


def test_create_room_uploads_image_and_defaults_to_empty(client):
    assert _login(client).status_code == 302
    form_html = client.get("/rooms/new").get_data(as_text=True)
    csrf_token = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', form_html)
    assert csrf_token is not None

    response = client.post(
        "/rooms/new",
        data={
            "csrf_token": csrf_token.group(1),
            "room_number": "405",
            "description": "Phòng có ban công",
            "price": "750000",
            "room_type": "double",
            "image": (BytesIO(b"\x89PNG\r\n\x1a\nroom image"), "room.png"),
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 302
    html = client.get("/rooms").get_data(as_text=True)
    assert 'aria-label="Phòng 405, Phòng trống"' in html
    assert "Phòng đôi" in html
    assert "Phòng có ban công" in html
    assert "750,000 VNĐ / đêm" in html
    image_url = re.search(r'src="(/room-images/[^\"]+)" alt="Ảnh phòng 405"', html)
    assert image_url is not None
    uploaded_image = client.get(image_url.group(1))
    assert uploaded_image.status_code == 200
    assert uploaded_image.data.startswith(b"\x89PNG\r\n\x1a\n")


def test_create_room_validates_price_room_type_and_image(client):
    assert _login(client).status_code == 302
    form_html = client.get("/rooms/new").get_data(as_text=True)
    csrf_token = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', form_html)
    assert csrf_token is not None

    response = client.post(
        "/rooms/new",
        data={
            "csrf_token": csrf_token.group(1),
            "room_number": "406",
            "description": "Phòng thử nghiệm",
            "price": "0",
            "room_type": ["single", "vip"],
            "image": (BytesIO(b"not an image"), "room.txt"),
        },
        content_type="multipart/form-data",
    )
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Giá thuê phải là số nguyên lớn hơn 0." in html
    assert "Vui lòng chọn đúng một thể loại phòng." in html
    assert "Ảnh phải có định dạng JPG, PNG hoặc WEBP hợp lệ." in html
    assert 'aria-label="Phòng 406, Phòng trống"' not in client.get("/rooms").get_data(as_text=True)


def test_home_redirects_to_room_management(client):
    assert _login(client).status_code == 302

    response = client.get("/")

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/rooms")
