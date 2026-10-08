"""Acceptance tests for the 60-minute room scheduling buffer."""

from __future__ import annotations

import re
from datetime import datetime, timedelta

import pytest

from conftest import DEMO_EMAIL, DEMO_PASSWORD, create_app
from hotel_app.app import CLEANING_BUFFER_MINUTES, intervals_conflict_with_cleaning_buffer
from hotel_app.extensions import db
from hotel_app.models import Room, RoomRental, RoomReservation, RoomServiceLog


def _now():
    return datetime.now().replace(second=0, microsecond=0)


def _local(value):
    return value.strftime("%Y-%m-%dT%H:%M")


def _token(client, path="/login"):
    html = client.get(path).get_data(as_text=True)
    match = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', html)
    assert match is not None
    return match.group(1)


def _login(client):
    return client.post("/login", data={"csrf_token": _token(client), "email": DEMO_EMAIL, "password": DEMO_PASSWORD})


def _room_id(app, number="101"):
    with app.app_context():
        return db.session.execute(db.select(Room.id).where(Room.number == number)).scalar_one()


def _add_reservation(app, room_id, start, end, *, status="booked", guest="Guest"):
    with app.app_context():
        room = db.session.get(Room, room_id)
        duration = int((end - start).total_seconds() // 60)
        row = RoomReservation(
            room_id=room_id, room_number=room.number, guest_name=guest,
            guest_phone="0901234567", reserved_from=start, reserved_until=end,
            duration_minutes=duration, nightly_rate=500000,
            total_price=500000 * duration // 1440, status=status, created_at=_now(),
        )
        db.session.add(row)
        db.session.commit()
        return row.id


def _reserve(client, start, end, *, room_number="101", guest="Guest"):
    return client.post(
        f"/rooms/{room_number}/reserve",
        data={"csrf_token": _token(client, f"/rooms/{room_number}/reserve"),
              "guest_name": guest, "guest_phone": "0901234567",
              "reserved_from": _local(start), "reserved_until": _local(end)},
    )


def _rental(app, *, start=None, checkout=None, room_number="101"):
    now = _now()
    start = start or now - timedelta(hours=3)
    checkout = checkout or now + timedelta(hours=1)
    with app.app_context():
        room = db.session.execute(db.select(Room).where(Room.number == room_number)).scalar_one()
        room.status, room.state = "Đang thuê", "occupied"
        room.check_in, room.check_out = start.strftime("%H:%M"), checkout.strftime("%H:%M")
        row = RoomRental(
            room_id=room.id, room_number=room.number, rented_at=start,
            expected_checkout=checkout,
            duration_minutes=int((checkout - start).total_seconds() // 60),
            nightly_rate=500000, total_price=500000,
        )
        db.session.add(row)
        db.session.commit()
        return room.id, row.id


def _edit_reservation(client, reservation_id, start, end):
    path = f"/rooms/101/reservations/{reservation_id}/edit"
    return client.post(path, data={
        "csrf_token": _token(client, path), "guest_name": "Edited Guest",
        "guest_phone": "0901234567", "reserved_from": _local(start),
        "reserved_until": _local(end),
    })


@pytest.mark.parametrize("gap,conflicts", [(0, True), (1, True), (30, True), (59, True), (60, False), (61, False)])
def test_buffer_helper_exact_boundary(gap, conflicts):
    first_start = datetime(2030, 1, 1, 10, 0)
    first_end = datetime(2030, 1, 1, 12, 0)
    second_start = first_end + timedelta(minutes=gap)
    second_end = second_start + timedelta(hours=2)
    assert CLEANING_BUFFER_MINUTES == 60
    assert intervals_conflict_with_cleaning_buffer(first_start, first_end, second_start, second_end) is conflicts


@pytest.mark.parametrize("gap,expected", [(0, 400), (1, 400), (30, 400), (59, 400), (60, 302), (61, 302)])
def test_new_reservation_after_existing_booking_enforces_gap(client, app, gap, expected):
    assert _login(client).status_code == 302
    room_id = _room_id(app)
    start = _now() + timedelta(days=4)
    end = start + timedelta(hours=2)
    _add_reservation(app, room_id, start, end)
    response = _reserve(client, end + timedelta(minutes=gap), end + timedelta(minutes=gap + 120))
    assert response.status_code == expected
    if expected == 400:
        assert "Phải chừa tối thiểu 60 phút" in response.get_data(as_text=True)


@pytest.mark.parametrize("gap,expected", [(59, 400), (60, 302), (61, 302)])
def test_new_reservation_before_existing_booking_enforces_gap(client, app, gap, expected):
    assert _login(client).status_code == 302
    room_id = _room_id(app)
    existing_start = _now() + timedelta(days=5)
    _add_reservation(app, room_id, existing_start, existing_start + timedelta(hours=2))
    new_end = existing_start - timedelta(minutes=gap)
    response = _reserve(client, new_end - timedelta(hours=2), new_end)
    assert response.status_code == expected


def test_reservation_inserted_between_two_bookings_checks_both_sides(client, app):
    assert _login(client).status_code == 302
    room_id = _room_id(app)
    a_start = _now() + timedelta(days=5)
    a_end = a_start + timedelta(hours=2)
    c_start = a_end + timedelta(hours=4)
    c_end = c_start + timedelta(hours=2)
    _add_reservation(app, room_id, a_start, a_end, guest="A")
    _add_reservation(app, room_id, c_start, c_end, guest="C")
    allowed = _reserve(client, a_end + timedelta(minutes=60), c_start - timedelta(minutes=60))
    assert allowed.status_code == 302


def test_reservation_inserted_between_bookings_rejects_short_next_gap(client, app):
    assert _login(client).status_code == 302
    room_id = _room_id(app)
    a_start = _now() + timedelta(days=5)
    a_end = a_start + timedelta(hours=2)
    c_start = a_end + timedelta(hours=4)
    _add_reservation(app, room_id, a_start, a_end, guest="A")
    _add_reservation(app, room_id, c_start, c_start + timedelta(hours=2), guest="C")
    response = _reserve(client, a_end + timedelta(minutes=60), c_start - timedelta(minutes=30))
    assert response.status_code == 400
    assert "60 phút" in response.get_data(as_text=True)


@pytest.mark.parametrize("status", ["cancelled", "completed"])
def test_non_booked_reservations_do_not_consume_buffer(client, app, status):
    assert _login(client).status_code == 302
    room_id = _room_id(app)
    start = _now() + timedelta(days=4)
    _add_reservation(app, room_id, start, start + timedelta(hours=2), status=status)
    assert _reserve(client, start + timedelta(minutes=1), start + timedelta(hours=2)).status_code == 302


def test_reservation_edit_excludes_itself_but_checks_every_other_booking(client, app):
    assert _login(client).status_code == 302
    room_id = _room_id(app)
    start = _now() + timedelta(days=4)
    reservation_id = _add_reservation(app, room_id, start, start + timedelta(hours=2))
    # Editing a row without changing its schedule must not conflict with itself.
    assert _edit_reservation(client, reservation_id, start, start + timedelta(hours=2)).status_code == 302
    other_start = start + timedelta(hours=3)
    _add_reservation(app, room_id, other_start, other_start + timedelta(hours=2))
    response = _edit_reservation(client, reservation_id, start, start + timedelta(hours=2, minutes=1))
    assert response.status_code == 400
    assert "60 phút" in response.get_data(as_text=True)


@pytest.mark.parametrize("gap,expected", [(59, 400), (60, 302), (61, 302)])
def test_active_rental_to_reservation_requires_buffer(client, app, gap, expected):
    assert _login(client).status_code == 302
    room_id, _ = _rental(app)
    with app.app_context():
        checkout = db.session.execute(db.select(RoomRental).where(RoomRental.room_id == room_id)).scalar_one().expected_checkout
    start = checkout + timedelta(minutes=gap)
    response = _reserve(client, start, start + timedelta(hours=2))
    assert response.status_code == expected


def test_active_rental_raw_overlap_is_still_rejected(client, app):
    assert _login(client).status_code == 302
    room_id, _ = _rental(app)
    with app.app_context():
        checkout = db.session.execute(db.select(RoomRental).where(RoomRental.room_id == room_id)).scalar_one().expected_checkout
    response = _reserve(client, checkout - timedelta(minutes=1), checkout + timedelta(hours=1))
    assert response.status_code == 400


@pytest.mark.parametrize("gap,expected", [(59, 400), (60, 302), (61, 302)])
def test_new_rental_checkout_respects_next_booking_buffer(client, app, gap, expected):
    assert _login(client).status_code == 302
    room_id = _room_id(app)
    booking_start = _now() + timedelta(hours=6)
    _add_reservation(app, room_id, booking_start, booking_start + timedelta(hours=2))
    checkout = booking_start - timedelta(minutes=gap)
    response = client.post("/rooms/101/rent", data={
        "csrf_token": _token(client, "/rooms/101/rent"),
        "expected_checkout": _local(checkout),
    })
    assert response.status_code == expected
    with app.app_context():
        rentals = db.session.execute(db.select(RoomRental).where(RoomRental.room_id == room_id)).scalars().all()
        assert len(rentals) == (1 if expected == 302 else 0)


def test_new_rental_ui_displays_effective_latest_checkout(client, app):
    assert _login(client).status_code == 302
    room_id = _room_id(app)
    booking_start = _now() + timedelta(hours=6)
    _add_reservation(app, room_id, booking_start, booking_start + timedelta(hours=2))
    html = client.get("/rooms/101/rent").get_data(as_text=True)
    latest = booking_start - timedelta(minutes=60)
    assert f'max="{_local(latest)}"' in html
    assert f'value="{_local(latest)}"' in html
    assert "Giờ trả muộn nhất" in html
    assert "tối thiểu 60 phút để dọn dẹp" in html


@pytest.mark.parametrize("gap,expected", [(59, 400), (60, 302), (61, 302)])
def test_rental_adjustment_boundary_and_rejection_are_atomic(client, app, gap, expected):
    assert _login(client).status_code == 302
    room_id, rental_id = _rental(app)
    booking_start = _now() + timedelta(hours=6)
    _add_reservation(app, room_id, booking_start, booking_start + timedelta(hours=2))
    proposed = booking_start - timedelta(minutes=gap)
    with app.app_context():
        rental = db.session.get(RoomRental, rental_id)
        room = db.session.get(Room, room_id)
        before = (rental.expected_checkout, rental.duration_minutes, rental.total_price, room.check_out, rental.nightly_rate)
    if gap == 60:
        html = client.get("/rooms/101/rent/edit").get_data(as_text=True)
        assert f'max="{_local(booking_start - timedelta(minutes=60))}"' in html
        assert "Phòng cần tối thiểu 60 phút" in html
    response = client.post("/rooms/101/rent/edit", data={
        "csrf_token": _token(client, "/rooms/101/rent/edit"),
        "expected_checkout": _local(proposed),
    })
    assert response.status_code == expected
    with app.app_context():
        rental = db.session.get(RoomRental, rental_id)
        room = db.session.get(Room, room_id)
        if expected == 400:
            assert (rental.expected_checkout, rental.duration_minutes, rental.total_price, room.check_out, rental.nightly_rate) == before
        else:
            assert rental.expected_checkout == proposed
            assert rental.nightly_rate == before[-1]


def test_checkout_is_not_blocked_by_close_booking_and_shows_warning(client, app):
    assert _login(client).status_code == 302
    room_id, _ = _rental(app, checkout=_now() + timedelta(minutes=15))
    start = _now() + timedelta(minutes=30)
    reservation_id = _add_reservation(app, room_id, start, start + timedelta(hours=2))
    response = client.post("/rooms/101/checkout", data={"csrf_token": _token(client, "/rooms")})
    assert response.status_code == 302
    page = client.get("/rooms").get_data(as_text=True)
    assert "không còn đủ 60 phút" in page
    with app.app_context():
        room = db.session.get(Room, room_id)
        reservation = db.session.get(RoomReservation, reservation_id)
        log = db.session.execute(db.select(RoomServiceLog).where(RoomServiceLog.room_id == room_id, RoomServiceLog.ended_at.is_(None))).scalar_one()
        assert (room.status, room.state) == ("Dọn dẹp", "cleaning")
        assert reservation.status == "booked"
        assert log.service_type == "cleaning" and log.note == "__checkout__"


def test_recent_checkout_after_early_cleaning_blocks_rent_and_reservation(client, app):
    assert _login(client).status_code == 302
    room_id = _room_id(app)
    now = _now()
    with app.app_context():
        room = db.session.get(Room, room_id)
        checkout_at = now - timedelta(minutes=30)
        db.session.add(RoomRental(room_id=room_id, room_number=room.number, rented_at=checkout_at-timedelta(hours=2), expected_checkout=checkout_at, duration_minutes=120, nightly_rate=500000, total_price=500000))
        db.session.add(RoomServiceLog(room_id=room_id, room_number=room.number, service_type="cleaning", started_at=checkout_at, ended_at=now-timedelta(minutes=20), note="__checkout__"))
        db.session.commit()
    ready_at = now + timedelta(minutes=30)
    rejected = client.post("/rooms/101/rent", data={"csrf_token": _token(client, "/rooms/101/rent"), "expected_checkout": _local(ready_at+timedelta(hours=1))})
    assert rejected.status_code == 400 and "sẵn sàng" in rejected.get_data(as_text=True)
    too_early = _reserve(client, now + timedelta(minutes=20), now + timedelta(hours=2))
    assert too_early.status_code == 400 and "60 phút" in too_early.get_data(as_text=True)
    at_ready = _reserve(client, ready_at, ready_at + timedelta(hours=2))
    assert at_ready.status_code == 302


def test_rental_is_eligible_at_post_checkout_readiness_boundary(client, app):
    assert _login(client).status_code == 302
    room_id = _room_id(app)
    now = _now()
    with app.app_context():
        room = db.session.get(Room, room_id)
        checkout_at = now - timedelta(minutes=60)
        db.session.add(RoomRental(room_id=room_id, room_number=room.number, rented_at=checkout_at-timedelta(hours=2), expected_checkout=checkout_at, duration_minutes=120, nightly_rate=500000, total_price=500000))
        db.session.add(RoomServiceLog(room_id=room_id, room_number=room.number, service_type="cleaning", started_at=checkout_at, ended_at=now, note="__checkout__"))
        db.session.commit()
    response = client.post("/rooms/101/rent", data={"csrf_token": _token(client, "/rooms/101/rent"), "expected_checkout": _local(now+timedelta(hours=1))})
    assert response.status_code == 302
    with app.app_context():
        room = db.session.get(Room, room_id)
        assert (room.status, room.state) == ("Đang thuê", "occupied")


def test_actual_checkout_and_early_cleaning_completion_keep_buffer_separate(client, app):
    assert _login(client).status_code == 302
    checkout_at = _now()
    rented = client.post("/rooms/101/rent", data={
        "csrf_token": _token(client, "/rooms/101/rent"),
        "expected_checkout": _local(checkout_at + timedelta(hours=2)),
    })
    assert rented.status_code == 302
    room_id = _room_id(app)
    listing = client.get("/rooms").get_data(as_text=True)
    match = re.search(r'<form(?:(?!>).)*class="room-checkout"(?:(?!>).)*action="/rooms/101/checkout"[^>]*>(.*?)</form>', listing, re.S)
    assert match is not None
    token = re.search(r'name="csrf_token" value="([^"]+)"', match.group(1))
    assert token is not None
    assert client.post("/rooms/101/checkout", data={"csrf_token": token.group(1)}).status_code == 302
    with app.app_context():
        service_log = db.session.execute(db.select(RoomServiceLog).where(RoomServiceLog.room_id == room_id, RoomServiceLog.service_type == "cleaning", RoomServiceLog.note == "__checkout__")).scalar_one()
        actual_checkout = service_log.started_at
        service_log_id = service_log.id
    assert client.post("/rooms/101/cleaning/complete", data={"csrf_token": _token(client, "/rooms")}).status_code == 302
    with app.app_context():
        room = db.session.get(Room, room_id)
        assert (room.status, room.state) == ("Phòng trống", "empty")
        assert db.session.get(RoomServiceLog, service_log_id).ended_at is not None
    early_rent = client.post("/rooms/101/rent", data={"csrf_token": _token(client, "/rooms/101/rent"), "expected_checkout": _local(actual_checkout + timedelta(hours=2))})
    assert early_rent.status_code == 400
    assert "sẵn sàng" in early_rent.get_data(as_text=True)
    assert _reserve(client, actual_checkout + timedelta(minutes=30), actual_checkout + timedelta(hours=2)).status_code == 400
    assert _reserve(client, actual_checkout + timedelta(minutes=60), actual_checkout + timedelta(hours=3)).status_code == 302


def test_existing_short_gap_legacy_bookings_survive_app_startup(app, client):
    assert _login(client).status_code == 302
    room_id = _room_id(app)
    start = _now() + timedelta(days=9)
    first_id = _add_reservation(app, room_id, start, start + timedelta(hours=2), guest="Legacy A")
    second_id = _add_reservation(app, room_id, start + timedelta(hours=2, minutes=30), start + timedelta(hours=4), guest="Legacy B")
    database_uri = app.config["SQLALCHEMY_DATABASE_URI"]
    page = client.get("/rooms")
    assert page.status_code == 200
    with app.app_context():
        before = [(row.id, row.reserved_from, row.reserved_until, row.status) for row in db.session.execute(db.select(RoomReservation).where(RoomReservation.id.in_((first_id, second_id))).order_by(RoomReservation.id)).scalars()]
        db.session.remove()
        db.engine.dispose()
    restarted = create_app({"APP_ENV": "testing", "TESTING": True, "SECRET_KEY": "test-only-secret-key", "SQLALCHEMY_DATABASE_URI": database_uri, "SESSION_COOKIE_SECURE": False})
    with restarted.app_context():
        after = [(row.id, row.reserved_from, row.reserved_until, row.status) for row in db.session.execute(db.select(RoomReservation).where(RoomReservation.id.in_((first_id, second_id))).order_by(RoomReservation.id)).scalars()]
        assert after == before
