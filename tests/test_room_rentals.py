"""Acceptance tests for renting an available room."""

from __future__ import annotations

import importlib
import re
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

import pytest

from conftest import DEMO_EMAIL, DEMO_PASSWORD
from hotel_app.extensions import db
from hotel_app.models import Room, RoomRental, RoomReservation

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



def _freeze_app_now(monkeypatch, now: datetime) -> None:
    app_module = importlib.import_module("hotel_app.app")

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return now if tz is None else now.replace(tzinfo=tz)

    monkeypatch.setattr(app_module, "datetime", FrozenDateTime)


def _set_rental_interval(app, rental_id: int, started_at: datetime, checkout: datetime) -> None:
    duration_minutes = int((checkout - started_at).total_seconds() // 60)
    with app.app_context():
        rental = db.session.get(RoomRental, rental_id)
        room = db.session.get(Room, rental.room_id)
        rental.rented_at = started_at
        rental.expected_checkout = checkout
        rental.duration_minutes = duration_minutes
        rental.total_price = int(
            (Decimal(rental.nightly_rate) * Decimal(duration_minutes) / Decimal(1440))
            .quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        )
        room.check_in = started_at.strftime("%H:%M")
        room.check_out = checkout.strftime("%H:%M")
        db.session.commit()

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



@pytest.mark.parametrize("duration_minutes", [1, 30, 59, 60, 61])
def test_new_rental_enforces_minimum_duration_and_is_atomic(client, app, monkeypatch, duration_minutes):
    assert _login(client).status_code == 302
    csrf_token = _csrf_token(client, "/rooms/101/rent")
    started_at = datetime(2035, 5, 6, 22, 2)
    _freeze_app_now(monkeypatch, started_at)

    response = client.post(
        "/rooms/101/rent",
        data={
            "csrf_token": csrf_token,
            "expected_checkout": _datetime_local(
                started_at + timedelta(minutes=duration_minutes)
            ),
            # A client-supplied start must not affect the server's actual start.
            "rental_started_at": "2000-01-01T00:00",
        },
    )

    with app.app_context():
        room = db.session.execute(
            db.select(Room).where(Room.number == "101")
        ).scalar_one()
        rentals = db.session.execute(
            db.select(RoomRental).where(RoomRental.room_number == "101")
        ).scalars().all()
        if duration_minutes < 60:
            html = response.get_data(as_text=True)
            assert response.status_code == 400
            assert "Thời gian thuê tối thiểu là 60 phút." in html
            assert "data-open-on-load" in html
            assert _datetime_local(started_at + timedelta(minutes=duration_minutes)) in html
            assert (room.status, room.state, room.check_in, room.check_out) == (
                "Phòng trống", "empty", None, None
            )
            assert rentals == []
        else:
            assert response.status_code == 302
            assert len(rentals) == 1
            assert rentals[0].rented_at == started_at
            assert rentals[0].duration_minutes == duration_minutes
            assert (room.status, room.state) == ("Đang thuê", "occupied")


def test_new_rental_requires_checkout_and_preserves_room(client, app, monkeypatch):
    assert _login(client).status_code == 302
    csrf_token = _csrf_token(client, "/rooms/101/rent")
    _freeze_app_now(monkeypatch, datetime(2035, 5, 6, 22, 2))

    response = client.post(
        "/rooms/101/rent",
        data={"csrf_token": csrf_token, "expected_checkout": ""},
    )

    assert response.status_code == 400
    assert "Vui lòng chọn thời gian trả phòng hợp lệ." in response.get_data(as_text=True)
    with app.app_context():
        room = db.session.execute(
            db.select(Room).where(Room.number == "101")
        ).scalar_one()
        assert (room.status, room.state, room.check_in, room.check_out) == (
            "Phòng trống", "empty", None, None
        )
        assert db.session.execute(db.select(RoomRental)).scalars().all() == []



def test_cleaning_buffer_can_leave_no_valid_minimum_rental_window(client, app, monkeypatch):
    assert _login(client).status_code == 302
    started_at = datetime(2035, 5, 6, 16, 30)
    with app.app_context():
        room = db.session.execute(
            db.select(Room).where(Room.number == "101")
        ).scalar_one()
        reservation_start = started_at + timedelta(minutes=90)
        db.session.add(
            RoomReservation(
                room_id=room.id, room_number=room.number, guest_name="Boundary",
                guest_phone="0901234567", reserved_from=reservation_start,
                reserved_until=reservation_start + timedelta(hours=2),
                duration_minutes=120, nightly_rate=500000, total_price=41667,
                status="booked", created_at=started_at,
            )
        )
        db.session.commit()
    csrf_token = _csrf_token(client, "/rooms/101/rent")
    _freeze_app_now(monkeypatch, started_at)

    page = client.get("/rooms/101/rent").get_data(as_text=True)
    assert "Không còn khoảng thời gian thuê đủ tối thiểu 60 phút trước lịch đặt này." in page
    assert f'min="{_datetime_local(started_at + timedelta(minutes=60))}"' in page
    assert f'max="{_datetime_local(started_at + timedelta(minutes=30))}"' in page

    response = client.post(
        "/rooms/101/rent",
        data={
            "csrf_token": csrf_token,
            "expected_checkout": _datetime_local(started_at + timedelta(minutes=30)),
        },
    )
    assert response.status_code == 400
    assert "Không còn thời gian thuê tối thiểu 60 phút trước lịch đặt tiếp theo." in response.get_data(as_text=True)
    with app.app_context():
        room = db.session.execute(
            db.select(Room).where(Room.number == "101")
        ).scalar_one()
        assert (room.status, room.state, room.check_in, room.check_out) == (
            "Phòng trống", "empty", None, None
        )
        assert db.session.execute(db.select(RoomRental)).scalars().all() == []

def test_new_rental_dialog_minimum_checkout_is_one_hour(client, monkeypatch):
    assert _login(client).status_code == 302
    started_at = datetime(2035, 5, 6, 22, 2)
    _freeze_app_now(monkeypatch, started_at)

    html = client.get("/rooms/101/rent").get_data(as_text=True)

    assert f'min="{_datetime_local(started_at + timedelta(minutes=60))}"' in html
    assert "minimumCheckoutValue" in html

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



@pytest.mark.parametrize("duration_minutes", [30, 59, 60, 61])
def test_rental_adjustment_enforces_minimum_total_duration_atomically(
    client, app, monkeypatch, duration_minutes
):
    assert _login(client).status_code == 302
    rental = _rent_room(client)
    started_at = datetime(2035, 5, 6, 22, 2)
    old_checkout = started_at + timedelta(hours=2)
    _set_rental_interval(app, rental.id, started_at, old_checkout)
    csrf_token = _csrf_token(client, "/rooms/101/rent/edit")
    _freeze_app_now(monkeypatch, started_at)

    response = client.post(
        "/rooms/101/rent/edit",
        data={
            "csrf_token": csrf_token,
            "expected_checkout": _datetime_local(
                started_at + timedelta(minutes=duration_minutes)
            ),
        },
    )

    with app.app_context():
        unchanged = db.session.get(RoomRental, rental.id)
        room = db.session.execute(
            db.select(Room).where(Room.number == "101")
        ).scalar_one()
        if duration_minutes < 60:
            html = response.get_data(as_text=True)
            assert response.status_code == 400
            assert "Thời gian thuê tối thiểu là 60 phút." in html
            assert "data-open-on-load" in html
            assert _datetime_local(started_at + timedelta(minutes=duration_minutes)) in html
            assert unchanged.expected_checkout == old_checkout
            assert unchanged.duration_minutes == 120
            assert unchanged.total_price > 0
            assert room.check_out == old_checkout.strftime("%H:%M")
        else:
            assert response.status_code == 302
            assert unchanged.expected_checkout == started_at + timedelta(minutes=duration_minutes)
            assert unchanged.duration_minutes == duration_minutes
            assert room.check_out == unchanged.expected_checkout.strftime("%H:%M")
            assert unchanged.nightly_rate == rental.nightly_rate


def test_existing_rental_can_extend_by_ten_minutes_without_another_full_hour(
    client, app, monkeypatch
):
    assert _login(client).status_code == 302
    rental = _rent_room(client)
    started_at = datetime(2035, 5, 6, 14, 0)
    original_checkout = started_at + timedelta(hours=5)
    _set_rental_interval(app, rental.id, started_at, original_checkout)
    with app.app_context():
        room = db.session.execute(
            db.select(Room).where(Room.number == "101")
        ).scalar_one()
        room.price = 900000
        db.session.commit()
    csrf_token = _csrf_token(client, "/rooms/101/rent/edit")
    _freeze_app_now(monkeypatch, original_checkout)
    new_checkout = original_checkout + timedelta(minutes=10)

    response = client.post(
        "/rooms/101/rent/edit",
        data={"csrf_token": csrf_token, "expected_checkout": _datetime_local(new_checkout)},
    )

    assert response.status_code == 302
    with app.app_context():
        updated = db.session.get(RoomRental, rental.id)
        assert updated.expected_checkout == new_checkout
        assert updated.duration_minutes == 310
        assert updated.nightly_rate == 500000
        expected_total = int(
            (Decimal(500000) * Decimal(310) / Decimal(1440))
            .quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        )
        assert updated.total_price == expected_total


def test_legacy_short_rental_can_be_adjusted_to_sixty_minutes(
    client, app, monkeypatch
):
    assert _login(client).status_code == 302
    rental = _rent_room(client)
    started_at = datetime(2035, 5, 6, 22, 2)
    _set_rental_interval(
        app, rental.id, started_at, started_at + timedelta(minutes=1)
    )
    assert client.get("/rooms").status_code == 200
    csrf_token = _csrf_token(client, "/rooms/101/rent/edit")
    _freeze_app_now(monkeypatch, started_at + timedelta(minutes=30))

    response = client.post(
        "/rooms/101/rent/edit",
        data={
            "csrf_token": csrf_token,
            "expected_checkout": _datetime_local(started_at + timedelta(minutes=60)),
        },
    )

    assert response.status_code == 302
    with app.app_context():
        updated = db.session.get(RoomRental, rental.id)
        assert updated.rented_at == started_at
        assert updated.expected_checkout == started_at + timedelta(minutes=60)
        assert updated.duration_minutes == 60


def test_rental_edit_minimum_uses_original_start_and_future_time(client, app, monkeypatch):
    assert _login(client).status_code == 302
    rental = _rent_room(client)
    started_at = datetime(2035, 5, 6, 14, 0)
    _set_rental_interval(app, rental.id, started_at, started_at + timedelta(hours=5))

    for now, expected_minimum in [
        (started_at + timedelta(minutes=30), started_at + timedelta(minutes=60)),
        (started_at + timedelta(hours=2), started_at + timedelta(hours=2, minutes=1)),
    ]:
        _freeze_app_now(monkeypatch, now)
        html = client.get("/rooms/101/rent/edit").get_data(as_text=True)
        match = re.search(r'<input[^>]*id="expected-checkout"[^>]*min="([^"]+)"', html)
        assert match is not None
        assert match.group(1) == _datetime_local(expected_minimum)

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
    assert "Hoàn tất dọn dẹp" in available_actions
    assert "Cho thuê" not in available_actions
    assert "Xóa phòng" not in available_actions
    assert "Điều chỉnh thuê" not in available_actions
    assert "Trả phòng" not in available_actions
    with app.app_context():
        room = db.session.execute(db.select(Room).where(Room.number == "101")).scalar_one()
        rental = db.session.get(RoomRental, rented.id)
        assert room.status == "Dọn dẹp"
        assert room.state == "cleaning"
        assert room.check_in is None
        assert room.check_out is None
        assert rental is not None


def test_rental_edit_uses_saved_nightly_rate_after_room_price_changes(client, app):
    assert _login(client).status_code == 302
    rental = _rent_room(client)
    with app.app_context():
        stored = db.session.get(RoomRental, rental.id)
        stored.nightly_rate = 500000
        room = db.session.execute(db.select(Room).where(Room.number == "101")).scalar_one()
        room.price = 700000
        db.session.commit()
        rental_start = stored.rented_at
    html = client.get("/rooms/101/rent/edit").get_data(as_text=True)
    assert html.count('data-nightly-rate="500000"') == 2
    assert "Giá áp dụng cho lượt thuê" in html
    assert "500,000 VNĐ / đêm" in html
    assert "Giữ nguyên theo giá tại thời điểm bắt đầu thuê." in html
    checkout = rental_start + timedelta(hours=3)
    response = client.post("/rooms/101/rent/edit", data={"csrf_token": _csrf_token(client, "/rooms/101/rent/edit"), "expected_checkout": _datetime_local(checkout)})
    assert response.status_code == 302
    with app.app_context():
        updated = db.session.get(RoomRental, rental.id)
        assert updated.nightly_rate == 500000
        assert updated.total_price == int((Decimal(500000) * Decimal(180) / Decimal(1440)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def test_new_rental_modal_keeps_current_effective_room_price(client, app):
    assert _login(client).status_code == 302
    with app.app_context():
        room = db.session.execute(db.select(Room).where(Room.number == "101")).scalar_one()
        room.price = 700000
        db.session.commit()
    html = client.get("/rooms/101/rent").get_data(as_text=True)
    assert 'data-nightly-rate="700000"' in html
    assert "700,000 VNĐ / đêm" in html


def test_rental_edit_shows_nearest_booked_reservation_and_ignores_cancelled(client, app):
    assert _login(client).status_code == 302
    rental = _rent_room(client)
    with app.app_context():
        room = db.session.execute(db.select(Room).where(Room.number == "101")).scalar_one()
        base = datetime.now().replace(second=0, microsecond=0) + timedelta(days=2)
        for label, offset, status in [("Cancelled near", 1, "cancelled"), ("Nearest booked", 3, "booked"), ("Later booked", 8, "booked")]:
            start = base + timedelta(hours=offset)
            end = start + timedelta(hours=2)
            db.session.add(RoomReservation(room_id=room.id, room_number=room.number, guest_name=label, guest_phone="0901234567", reserved_from=start, reserved_until=end, duration_minutes=120, nightly_rate=500000, total_price=41667, status=status, created_at=datetime.now().replace(second=0, microsecond=0)))
        db.session.commit()
        nearest = base + timedelta(hours=3)
        later = base + timedelta(hours=8)
    html = client.get("/rooms/101/rent/edit").get_data(as_text=True)
    modal = html.split('<dialog\n  class="room-dialog rent-dialog"', 1)[1].split("</dialog>", 1)[0]
    assert "Lịch đặt trước tiếp theo:" in modal
    assert nearest.strftime("%d/%m/%Y %H:%M") in modal
    assert later.strftime("%d/%m/%Y %H:%M") not in modal
    assert "Cancelled near" not in modal
    assert f'max="{_datetime_local(nearest - timedelta(minutes=60))}"' in modal


def test_rental_edit_without_upcoming_reservation_has_no_schedule_hint(client):
    assert _login(client).status_code == 302
    _rent_room(client)
    html = client.get("/rooms/101/rent/edit").get_data(as_text=True)
    assert "Lịch đặt trước tiếp theo:" not in html
    assert 'id="expected-checkout"' in html
    assert "max=" not in re.search(r'<input[^>]*id="expected-checkout"[^>]*>', html).group(0)


def test_rental_edit_checkout_at_reservation_buffer_boundary_is_allowed(client, app):
    assert _login(client).status_code == 302
    rental = _rent_room(client)
    with app.app_context():
        room = db.session.execute(db.select(Room).where(Room.number == "101")).scalar_one()
        start = datetime.now().replace(second=0, microsecond=0) + timedelta(days=1)
        db.session.add(RoomReservation(room_id=room.id, room_number=room.number, guest_name="Boundary", guest_phone="0901234567", reserved_from=start, reserved_until=start+timedelta(days=1), duration_minutes=1440, nightly_rate=500000, total_price=500000, status="booked", created_at=datetime.now().replace(second=0, microsecond=0)))
        db.session.commit()
    response = client.post("/rooms/101/rent/edit", data={"csrf_token": _csrf_token(client, "/rooms/101/rent/edit"), "expected_checkout": _datetime_local(start - timedelta(minutes=60))})
    assert response.status_code == 302
    with app.app_context():
        updated = db.session.get(RoomRental, rental.id)
        room = db.session.execute(db.select(Room).where(Room.number == "101")).scalar_one()
        assert updated.expected_checkout == start - timedelta(minutes=60)
        assert room.check_out == (start - timedelta(minutes=60)).strftime("%H:%M")


def test_rental_edit_checkout_after_reservation_start_is_rejected_atomically(client, app):
    assert _login(client).status_code == 302
    rental = _rent_room(client)
    with app.app_context():
        room = db.session.execute(db.select(Room).where(Room.number == "101")).scalar_one()
        start = datetime.now().replace(second=0, microsecond=0) + timedelta(days=1)
        db.session.add(RoomReservation(room_id=room.id, room_number=room.number, guest_name="Boundary", guest_phone="0901234567", reserved_from=start, reserved_until=start+timedelta(days=1), duration_minutes=1440, nightly_rate=500000, total_price=500000, status="booked", created_at=datetime.now().replace(second=0, microsecond=0)))
        db.session.commit()
        stored = db.session.get(RoomRental, rental.id)
        before_rental = (stored.expected_checkout, stored.duration_minutes, stored.total_price)
        before_checkout = room.check_out
    rejected = start + timedelta(minutes=1)
    response = client.post("/rooms/101/rent/edit", data={"csrf_token": _csrf_token(client, "/rooms/101/rent/edit"), "expected_checkout": _datetime_local(rejected)})
    html = response.get_data(as_text=True)
    assert response.status_code == 400
    assert "60 phút" in html
    assert 'data-open-on-load' in html and _datetime_local(rejected) in html
    with app.app_context():
        stored = db.session.get(RoomRental, rental.id)
        room = db.session.execute(db.select(Room).where(Room.number == "101")).scalar_one()
        assert (stored.expected_checkout, stored.duration_minutes, stored.total_price) == before_rental
        assert room.check_out == before_checkout


def test_rental_edit_minimum_includes_stay_and_future_time(client, app):
    assert _login(client).status_code == 302
    rental = _rent_room(client)
    with app.app_context():
        started_at = db.session.get(RoomRental, rental.id).rented_at
    now_minute = datetime.now().replace(second=0, microsecond=0)
    html = client.get("/rooms/101/rent/edit").get_data(as_text=True)
    match = re.search(r'<input[^>]*id="expected-checkout"[^>]*min="([^"]+)"', html)
    assert match is not None
    minimum = datetime.strptime(match.group(1), "%Y-%m-%dT%H:%M")
    assert minimum >= started_at + timedelta(minutes=60)
    assert minimum > now_minute
    assert minimum <= max(started_at + timedelta(minutes=60), now_minute + timedelta(minutes=2))

def test_occupied_room_edit_anchor_and_direct_get_render_usable_edit_modal(client, app):
    assert _login(client).status_code == 302
    rental = _rent_room(client)
    with app.app_context():
        stored = db.session.get(RoomRental, rental.id)
        stored.nightly_rate = 612345
        room = db.session.execute(db.select(Room).where(Room.number == "101")).scalar_one()
        room.price = 900000
        db.session.commit()
        started_at = stored.rented_at
        expected_checkout = stored.expected_checkout

    listing = client.get("/rooms").get_data(as_text=True)
    card = _room_card_html(listing, "101")
    assert card.count('href="/rooms/101/rent/edit"') == 1
    edit_link = re.search(r'<a\b[^>]*href="/rooms/101/rent/edit"[^>]*>(.*?)</a>', card, re.DOTALL)
    assert edit_link is not None and "Điều chỉnh thuê" in edit_link.group(1)
    assert "disabled" not in edit_link.group(0)
    assert 'aria-disabled="true"' not in edit_link.group(0)

    response = client.get("/rooms/101/rent/edit")
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert 'id="rent-room-dialog"' in html
    assert 'data-open-on-load' in html
    assert 'data-edit-mode="true"' in html
    assert 'action="/rooms/101/rent/edit"' in html
    assert f'value="{_datetime_local(started_at)}"' in html
    assert f'value="{_datetime_local(expected_checkout)}"' in html
    assert html.count('data-nightly-rate="612345"') == 2
    assert "612,345 VNĐ / đêm" in html


def test_room_action_is_not_blocked_by_css_or_unsafe_dialog_initialization():
    root = Path(__file__).resolve().parents[1]
    css = (root / "src/hotel_app/static/css/hotel.css").read_text(encoding="utf-8")
    template = (root / "src/hotel_app/templates/room_management.html").read_text(encoding="utf-8")
    script = template.split("<script>", 1)[1].split("</script>", 1)[0]

    assert "pointer-events: none" not in css
    assert ".room-card::before" not in css and ".room-card::after" not in css
    assert 'document.getElementById("open-room-dialog").addEventListener' not in script
    assert 'document.getElementById("close-rent-dialog").addEventListener' not in script
    assert "const bindClick = (id, handler)" in script
    assert "checkoutInput?.addEventListener" in script
    assert "if (reservationDialog && reservationStart && reservationEnd" in script
    assert script.index("rentDialog.showModal();") < script.index('const reservationDialog =')
