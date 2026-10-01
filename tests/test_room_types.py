"""Acceptance tests for the room type search page."""

from __future__ import annotations

import re

from conftest import DEMO_EMAIL, DEMO_PASSWORD
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


def test_room_type_management_delete_requires_confirmation(client):
    assert _login(client).status_code == 302

    html = client.get("/room-types").get_data(as_text=True)

    assert re.search(
        r'<button class="action-button action-button--primary room-type-add" type="button" disabled>',
        html,
    )
    assert html.count('class="action-button action-button--edit" type="button" disabled') == 2
    assert html.count('class="action-button action-button--delete" type="submit"') == 2
    assert html.count("Bạn có chắc chắn muốn xóa thể loại phòng này?") == 2


def test_room_type_can_be_deleted(client, app):
    assert _login(client).status_code == 302
    with app.app_context():
        room_type = db.session.execute(
            db.select(RoomType).where(RoomType.name == "Phòng tiêu chuẩn")
        ).scalar_one()
        room_type_id = room_type.id

    html = client.get("/room-types").get_data(as_text=True)
    token = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', html)
    assert token is not None
    response = client.post(
        f"/room-types/{room_type_id}/delete",
        data={"csrf_token": token.group(1)},
    )

    assert response.status_code == 302
    page = client.get("/room-types").get_data(as_text=True)
    assert "<strong>Phòng tiêu chuẩn</strong>" not in page
    assert "Phòng VIP" in page


def test_room_cards_stay_on_room_management_page(client):
    assert _login(client).status_code == 302

    room_types_page = client.get("/room-types").get_data(as_text=True)
    room_management_page = client.get("/").get_data(as_text=True)

    assert "Phòng 101" not in room_types_page
    assert 'aria-label="Phòng mẫu 101' in room_management_page
    assert 'class="room-grid"' in room_management_page
