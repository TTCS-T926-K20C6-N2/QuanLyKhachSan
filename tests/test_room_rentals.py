"""Acceptance tests for renting an available room."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP

from conftest import DEMO_EMAIL, DEMO_PASSWORD
from hotel_app.extensions import db
from hotel_app.models import Room, RoomRental


def _csrf_token(client, path: str = "/login") -> str:
    html = client.get(path).get_data(as_text=True)
    match = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', html)
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


def _room_card_html(html: str, room_number: str) -> str:
    match = re.search(
        rf'<article\s+class="room-card [^"]+"\s+'
        rf'aria-label="Phòng {re.escape(room_number)}, [^"]+"\s*>'
        r"(.*?)</article>",
        html,
        re.DOTALL,
    )
    assert match is not None
    return match.group(1)


def _datetime_local(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M")


def test_available_room_opens_rental_dialog_with_room_details(client):
    assert _login(client).status_code == 302

    listing = client.get("/rooms").get_data(as_text=True)
    assert 'href="/rooms/101/rent"' in listing
    assert "Cho thuê" in listing

    response = client.get("/rooms/101/rent")
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert 'id="rent-room-dialog"' in html
    assert "data-open-on-load" in html
    assert "Thông tin phòng" in html
    assert "Thời gian bắt đầu thuê" in html
    assert "Thời gian trả phòng" in html
    assert 'id="rental-duration"' in html
    assert 'id="rental-total"' in html
    assert re.search(
        r'id="expected-checkout"\s+name="expected_checkout"\s+'
        r'type="datetime-local"',
        html,
    )


def test_renting_room_persists_duration_total_and_occupied_state(client, app):
    assert _login(client).status_code == 302

    client.get("/rooms/101/rent")
    response = client.post(
        "/rooms/101/rent",
        data={
            "csrf_token": _csrf_token(client, "/rooms/101/rent"),
            "expected_checkout": _datetime_local(
                datetime.now().replace(second=0, microsecond=0)
                + timedelta(hours=2)
            ),
            "rental_started_at": "2000-01-01T00:00",
        },
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/rooms")
    listing = client.get("/rooms").get_data(as_text=True)
    assert 'aria-label="Phòng 101, Đang thuê"' in listing
    assert "Đã cho thuê phòng 101." in listing

    with app.app_context():
        rental = db.session.execute(
            db.select(RoomRental).where(RoomRental.room_number == "101")
        ).scalar_one()
        duration_minutes = int(
            (rental.expected_checkout - rental.rented_at).total_seconds() // 60
        )
        expected_total = int(
            (Decimal(rental.nightly_rate) * Decimal(duration_minutes) / Decimal(1440))
            .quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        )
        assert rental.rented_at.year > 2020
        assert 0 < duration_minutes <= 120
        assert rental.nightly_rate == 500000
        assert rental.total_price == expected_total
        assert rental.total_price > 0


def test_rental_rejects_checkout_before_start_without_changing_room(client, app):
    assert _login(client).status_code == 302
    csrf_token = _csrf_token(client, "/rooms/101/rent")
    response = client.post(
        "/rooms/101/rent",
        data={
            "csrf_token": csrf_token,
            "expected_checkout": _datetime_local(
                datetime.now().replace(second=0, microsecond=0)
                - timedelta(minutes=1)
            ),
        },
    )

    assert response.status_code == 400
    assert "Thời gian trả phòng phải sau thời gian bắt đầu thuê." in response.get_data(as_text=True)
    assert "data-open-on-load" in response.get_data(as_text=True)
    with app.app_context():
        room = db.session.execute(
            db.select(Room).where(Room.number == "101")
        ).scalar_one()
        assert room.status == "Phòng trống"
        assert db.session.execute(db.select(RoomRental)).scalars().all() == []


def test_occupied_room_cannot_be_rented_again(client, app):
    assert _login(client).status_code == 302
    with app.app_context():
        room = db.session.execute(
            db.select(Room).where(Room.number == "101")
        ).scalar_one()
        room.status = "Đang thuê"
        room.state = "occupied"
        db.session.commit()

    response = client.get("/rooms/101/rent")
    assert response.status_code == 302
    listing = client.get("/rooms").get_data(as_text=True)
    match = re.search(
        r'<article\s+class="room-card [^"]+"\s+'
        r'aria-label="Phòng 101, Đang thuê"\s*>(.*?)</article>',
        listing,
        re.DOTALL,
    )
    assert match is not None
    occupied_card = match.group(1)
    assert "Cho thuê" not in occupied_card


def _rent_room(client, room_number: str = "101") -> RoomRental:
    response = client.post(
        f"/rooms/{room_number}/rent",
        data={
            "csrf_token": _csrf_token(client, f"/rooms/{room_number}/rent"),
            "expected_checkout": _datetime_local(
                datetime.now().replace(second=0, microsecond=0)
                + timedelta(hours=2)
            ),
        },
    )
    assert response.status_code == 302
    with client.application.app_context():
        return db.session.execute(
            db.select(RoomRental)
            .where(RoomRental.room_number == room_number)
            .order_by(RoomRental.id.desc())
            .limit(1)
        ).scalar_one()


def test_active_rental_can_change_checkout_and_recalculate_price(client, app):
    assert _login(client).status_code == 302
    rental = _rent_room(client)
    with app.app_context():
        rental_start = db.session.get(RoomRental, rental.id).rented_at
        old_checkout = db.session.get(RoomRental, rental.id).expected_checkout
    new_checkout = rental_start + timedelta(hours=3)

    edit_page = client.get("/rooms/101/rent/edit").get_data(as_text=True)
    assert "data-open-on-load" in edit_page
    assert "Tùy chọn cho thuê" in edit_page
    assert "Giờ bắt đầu giữ nguyên" in edit_page
    assert _datetime_local(old_checkout) in edit_page
    listing = client.get("/rooms").get_data(as_text=True)
    assert 'href="/rooms/101/rent/edit"' in listing
    assert "Điều chỉnh thuê" in listing

    response = client.post(
        "/rooms/101/rent/edit",
        data={
            "csrf_token": _csrf_token(client, "/rooms/101/rent/edit"),
            "expected_checkout": _datetime_local(new_checkout),
        },
    )

    assert response.status_code == 302
    assert "Đã cập nhật giờ trả phòng 101." in client.get("/rooms").get_data(as_text=True)
    with app.app_context():
        updated = db.session.get(RoomRental, rental.id)
        room = db.session.execute(
            db.select(Room).where(Room.number == "101")
        ).scalar_one()
        expected_minutes = 180
        expected_total = int(
            (Decimal(updated.nightly_rate) * Decimal(expected_minutes) / Decimal(1440))
            .quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        )
        assert updated.expected_checkout == new_checkout
        assert updated.duration_minutes == expected_minutes
        assert updated.total_price == expected_total
        assert room.check_out == new_checkout.strftime("%H:%M")


def test_active_rental_rejects_checkout_in_the_past(client, app):
    assert _login(client).status_code == 302
    rental = _rent_room(client)
    with app.app_context():
        original_checkout = db.session.get(RoomRental, rental.id).expected_checkout
        original_total = db.session.get(RoomRental, rental.id).total_price

    response = client.post(
        "/rooms/101/rent/edit",
        data={
            "csrf_token": _csrf_token(client, "/rooms/101/rent/edit"),
            "expected_checkout": _datetime_local(
                datetime.now().replace(second=0, microsecond=0) - timedelta(minutes=1)
            ),
        },
    )

    assert response.status_code == 400
    assert "Thời gian trả phòng phải sau thời điểm hiện tại." in response.get_data(as_text=True)
    assert "data-open-on-load" in response.get_data(as_text=True)
    with app.app_context():
        unchanged = db.session.get(RoomRental, rental.id)
        assert unchanged.expected_checkout == original_checkout
        assert unchanged.total_price == original_total


def test_cannot_adjust_rental_for_occupied_room_without_rental_record(client, app):
    assert _login(client).status_code == 302
    with app.app_context():
        room = db.session.execute(
            db.select(Room).where(Room.number == "101")
        ).scalar_one()
        room.status = "Đang thuê"
        room.state = "occupied"
        db.session.commit()

    response = client.get("/rooms/101/rent/edit")
    assert response.status_code == 302
    assert "Không tìm thấy lượt thuê để điều chỉnh cho phòng 101." in client.get("/rooms").get_data(as_text=True)


def test_rental_requires_csrf_token(client):
    assert _login(client).status_code == 302
    response = client.post(
        "/rooms/101/rent",
        data={"expected_checkout": _datetime_local(datetime.now() + timedelta(hours=1))},
    )
    assert response.status_code == 400


def test_room_card_actions_follow_rental_and_checkout_lifecycle(client, app):
    assert _login(client).status_code == 302
    rented = _rent_room(client, "101")

    listing = client.get("/rooms").get_data(as_text=True)
    occupied_card = _room_card_html(listing, "101")
    actions = occupied_card
    assert "Điều chỉnh thuê" in actions
    assert "Trả phòng" in actions
    assert "Cập nhật" not in actions
    assert "Xóa phòng" not in actions
    assert 'href="/rooms/101/rent"' not in actions
    checkout_form = re.search(
        r'<form(?:(?!>).)*class="room-checkout"(?:(?!>).)*action="/rooms/101/checkout"[^>]*>(.*?)</form>',
        occupied_card,
        re.DOTALL,
    )
    assert checkout_form is not None
    token = re.search(r'name="csrf_token" value="([^"]+)"', checkout_form.group(1))
    assert token is not None

    no_csrf_client = client.application.test_client()
    assert no_csrf_client.post("/rooms/101/checkout").status_code == 400

    response = client.post("/rooms/101/checkout", data={"csrf_token": token.group(1)})
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/rooms")
    available_listing = client.get("/rooms").get_data(as_text=True)
    available_card = _room_card_html(available_listing, "101")
    available_actions = available_card.split('<div class="room-actions">', 1)[1].split("</div>", 1)[0]
    assert "Cho thuê" in available_actions
    assert "Cập nhật" in available_actions
    assert "Xóa phòng" in available_actions
    assert "Điều chỉnh thuê" not in available_actions
    assert "Trả phòng" not in available_actions
    with app.app_context():
        room = db.session.execute(db.select(Room).where(Room.number == "101")).scalar_one()
        rental = db.session.get(RoomRental, rented.id)
        assert room.status == "Phòng trống"
        assert room.state == "empty"
        assert room.check_in is None
        assert room.check_out is None
        assert rental is not None
