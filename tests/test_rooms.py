"""Acceptance tests for room deletion."""

from __future__ import annotations

import re

from conftest import DEMO_EMAIL, DEMO_PASSWORD
from hotel_app.extensions import db
from hotel_app.models import Room


def _csrf_token(client, page: str = "/login") -> str:
    response = client.get(page)
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


def test_home_renders_database_rooms_with_confirmation(client):
    assert _login(client).status_code == 302

    html = client.get("/").get_data(as_text=True)

    assert 'aria-label="Phòng mẫu 101, Phòng trống"' in html
    assert 'action="/rooms/1/delete"' in html
    assert "Bạn có chắc chắn muốn xóa phòng này?" in html


def test_authenticated_user_can_delete_room(client, app):
    assert _login(client).status_code == 302
    with app.app_context():
        room = db.session.execute(
            db.select(Room).where(Room.number == "101")
        ).scalar_one()
        room_id = room.id

    response = client.post(
        f"/rooms/{room_id}/delete",
        data={"csrf_token": _csrf_token(client, "/")},
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/")
    html = client.get("/").get_data(as_text=True)
    assert 'aria-label="Phòng mẫu 101, Phòng trống"' not in html
    assert 'aria-label="Phòng mẫu 102, Phòng trống"' in html


def test_room_delete_requires_login(client):
    response = client.post(
        "/rooms/1/delete",
        data={"csrf_token": _csrf_token(client)},
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/login")
