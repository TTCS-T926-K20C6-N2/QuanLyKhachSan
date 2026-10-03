from __future__ import annotations

import re

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from conftest import DEMO_EMAIL, DEMO_PASSWORD
from hotel_app.extensions import db
from hotel_app.models import Room


RENTED_STATUS = "Đang thuê"
EMPTY_STATUS = "Phòng trống"


def _room_card(html: str, number: str) -> str:
    match = re.search(
        rf'<article\s+class="room-card [^"]+"\s+'
        rf'aria-label="[^"]*{re.escape(number)}, [^"]+"\s*>(.*?)</article>',
        html,
        re.DOTALL,
    )
    assert match is not None
    return match.group(0)


def _checkout_token(client) -> str:
    html = client.get("/rooms").get_data(as_text=True)
    match = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', html)
    assert match is not None
    return match.group(1)


def _login(client):
    html = client.get("/login").get_data(as_text=True)
    match = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', html)
    assert match is not None
    return client.post(
        "/login",
        data={
            "csrf_token": match.group(1),
            "email": DEMO_EMAIL,
            "password": DEMO_PASSWORD,
        },
    )


def _make_rented(app) -> dict[str, object]:
    with app.app_context():
        room = db.session.execute(
            db.select(Room).where(Room.number == "102")
        ).scalar_one()
        room.status = RENTED_STATUS
        room.state = "occupied"
        room.description = "Mô tả được giữ nguyên"
        room.price = 987654
        room.image = "kept-image.png"
        snapshot = {
            "number": room.number,
            "type": room.type,
            "description": room.description,
            "price": room.price,
            "image": room.image,
            "check_in": room.check_in,
            "check_out": room.check_out,
        }
        db.session.commit()
        return snapshot


def test_room_cards_only_show_checkout_for_rented_rooms(client, app):
    assert _login(client).status_code == 302
    _make_rented(app)

    html = client.get("/rooms").get_data(as_text=True)

    assert "Trả phòng" in _room_card(html, "102")
    assert "Trả phòng" not in _room_card(html, "101")


def test_checkout_updates_both_status_fields_and_persists_without_other_changes(
    client, app
):
    assert _login(client).status_code == 302
    original = _make_rented(app)

    response = client.post(
        "/rooms/102/checkout", data={"csrf_token": _checkout_token(client)}
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/rooms")
    listing = client.get("/rooms").get_data(as_text=True)
    assert 'class="room-card room-card--empty"' in _room_card(listing, "102")
    assert 'aria-label="Phòng 102, Phòng trống"' in listing
    assert "Đã trả phòng 102 thành công." in listing
    home = client.get("/").get_data(as_text=True)
    assert 'aria-label="Phòng 102, Phòng trống"' in home

    with app.app_context():
        room = db.session.execute(
            db.select(Room).where(Room.number == "102")
        ).scalar_one()
        assert room.status == EMPTY_STATUS
        assert room.state == "empty"
        for field, value in original.items():
            assert getattr(room, field) == value


def test_checkout_requires_login_and_csrf(client):
    login_page = client.get("/login").get_data(as_text=True)
    token_match = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', login_page)
    assert token_match is not None
    unauthenticated = client.post(
        "/rooms/102/checkout", data={"csrf_token": token_match.group(1)}
    )
    assert unauthenticated.status_code == 302
    assert unauthenticated.headers["Location"].endswith("/login")

    assert _login(client).status_code == 302
    missing_token = client.post("/rooms/102/checkout")
    assert missing_token.status_code == 400
    with client.session_transaction() as session:
        assert "user_id" in session


def test_checkout_handles_missing_and_already_empty_rooms(client, app):
    assert _login(client).status_code == 302
    token = _checkout_token(client)

    missing = client.post("/rooms/NO-SUCH-ROOM/checkout", data={"csrf_token": token})
    empty = client.post("/rooms/101/checkout", data={"csrf_token": token})

    assert missing.status_code == 302
    assert empty.status_code == 302
    html = client.get("/rooms").get_data(as_text=True)
    assert "Không tìm thấy phòng NO-SUCH-ROOM." in html
    assert "Phòng 101 không đang được thuê." in html
    with app.app_context():
        assert db.session.execute(
            db.select(Room).where(Room.number == "101")
        ).scalar_one().status == EMPTY_STATUS


def test_checkout_rolls_back_database_error(client, app, monkeypatch):
    assert _login(client).status_code == 302
    _make_rented(app)
    token = _checkout_token(client)

    def fail_commit(_session):
        raise SQLAlchemyError("simulated checkout failure")

    monkeypatch.setattr(Session, "commit", fail_commit)
    response = client.post("/rooms/102/checkout", data={"csrf_token": token})

    assert response.status_code == 302
    assert "Không thể trả phòng" in client.get("/rooms").get_data(as_text=True)
    with app.app_context():
        room = db.session.execute(
            db.select(Room).where(Room.number == "102")
        ).scalar_one()
        assert room.status == RENTED_STATUS
        assert room.state == "occupied"
