"""Acceptance tests for the room type search page."""

from __future__ import annotations

import re
from io import BytesIO

from conftest import DEMO_EMAIL, DEMO_PASSWORD


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


def test_room_management_requires_login(client):
    response = client.get("/rooms")

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/login")


def test_create_room_requires_login(client):
    response = client.get("/rooms/new")

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
    assert html.count('type="checkbox" name="room_type"') == 3
    assert html.count('type="checkbox"') == 3
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
    assert "Sức chứa" in html
    assert "Phòng tiêu chuẩn" in html
    assert "500,000 VNĐ" in html
    assert "Phòng VIP" in html
    assert "1,200,000 VNĐ" in html
    assert 'name="room_type"' not in html


def test_room_type_management_actions_are_disabled(client):
    assert _login(client).status_code == 302

    html = client.get("/room-types").get_data(as_text=True)

    assert re.search(
        r'<button class="action-button action-button--primary room-type-add" type="button" disabled>',
        html,
    )
    assert html.count('class="action-button action-button--edit" type="button" disabled') == 2
    assert html.count('class="action-button action-button--delete" type="button" disabled') == 2


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
