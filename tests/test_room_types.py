"""Acceptance tests for the room type search page."""

from __future__ import annotations

import re

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


def test_home_redirects_to_room_management(client):
    assert _login(client).status_code == 302

    response = client.get("/")

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/rooms")
