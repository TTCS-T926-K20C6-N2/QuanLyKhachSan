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


def test_room_types_page_contains_search_options_and_add_action(client):
    assert _login(client).status_code == 302

    response = client.get("/room-types")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'name="room_type"' in html
    assert "Tất cả" in html
    assert "Phòng tiêu chuẩn" in html
    assert "Phòng 2 giường đơn" in html
    assert "Phòng 1 giường đôi" in html
    assert "Phòng vip" in html
    assert "Thêm thể loại phòng" in html


def test_room_type_filter_returns_matching_rooms(client):
    assert _login(client).status_code == 302

    response = client.get("/room-types?room_type=Phòng%20vip")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "3 phòng" in html
    assert "Phòng 104" in html
    assert "Phòng 203" in html
    assert "Phòng 302" in html
    assert "Phòng 101" not in html


def test_invalid_room_type_filter_falls_back_to_all_rooms(client):
    assert _login(client).status_code == 302

    response = client.get("/room-types?room_type=Không%20tồn%20tại")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "12 phòng" in html
