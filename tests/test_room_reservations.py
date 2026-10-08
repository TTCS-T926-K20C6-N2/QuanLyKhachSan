"""Acceptance tests for future room reservations and schedule conflicts."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from conftest import DEMO_EMAIL, DEMO_PASSWORD, create_app
from hotel_app.extensions import db
from hotel_app.models import Room, RoomRental, RoomReservation, RoomType, User


def _token(client, path="/login"):
    html = client.get(path).get_data(as_text=True)
    match = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', html)
    assert match is not None
    return match.group(1)


def _login(client):
    return client.post("/login", data={"csrf_token": _token(client), "email": DEMO_EMAIL, "password": DEMO_PASSWORD})


def _now_minute():
    return datetime.now().replace(second=0, microsecond=0)


def _local(value):
    return value.strftime("%Y-%m-%dT%H:%M")


def _room(app, number="101"):
    with app.app_context():
        return db.session.execute(db.select(Room).where(Room.number == number)).scalar_one().id


def _set_active_rental(app, number="101", *, start=None, checkout=None):
    now = _now_minute()
    start = start or now - timedelta(days=1)
    checkout = checkout or now + timedelta(days=1)
    with app.app_context():
        room = db.session.execute(db.select(Room).where(Room.number == number)).scalar_one()
        room.status = "Đang thuê"
        room.state = "occupied"
        room.check_in = start.strftime("%H:%M")
        room.check_out = checkout.strftime("%H:%M")
        rental = RoomRental(room_id=room.id, room_number=room.number, rented_at=start, expected_checkout=checkout, duration_minutes=int((checkout-start).total_seconds()//60), nightly_rate=room.price or 500000, total_price=500000)
        db.session.add(rental)
        db.session.commit()
        return room.id, rental.id


def _reservation_data(room_number="101", *, start=None, end=None, **extra):
    now = _now_minute()
    data = {"guest_name": "  Nguyễn An  ", "guest_phone": "0901234567", "reserved_from": _local(start or now + timedelta(days=2)), "reserved_until": _local(end or now + timedelta(days=3))}
    data.update(extra)
    return data


def _create_reservation(client, room_number="101", *, start=None, end=None, **extra):
    return client.post(f"/rooms/{room_number}/reserve", data={"csrf_token": _token(client, f"/rooms/{room_number}/reserve"), **_reservation_data(room_number, start=start, end=end, **extra)})


def _add_reservation(app, room_id, start, end, *, status="booked", guest="Guest", rate=500000):
    with app.app_context():
        room = db.session.get(Room, room_id)
        duration = int((end-start).total_seconds()//60)
        row = RoomReservation(room_id=room_id, room_number=room.number, guest_name=guest, guest_phone="0901234567", reserved_from=start, reserved_until=end, duration_minutes=duration, nightly_rate=rate, total_price=rate*duration//1440, status=status, created_at=_now_minute())
        db.session.add(row)
        db.session.commit()
        return row.id


def test_additive_schema_keeps_room_rental_columns_and_existing_room(app):
    with app.app_context():
        assert inspect(db.engine).has_table("room_reservations")
        assert {"id", "room_id", "room_number", "rented_at", "expected_checkout", "duration_minutes", "nightly_rate", "total_price"} <= {c["name"] for c in inspect(db.engine).get_columns("room_rentals")}
        assert db.session.execute(db.select(Room).where(Room.number == "101")).scalar_one()


def test_reservation_get_renders_modal_fields_and_existing_schedule_list(client, app):
    assert _login(client).status_code == 302
    room_id = _room(app)
    now = _now_minute()
    _add_reservation(app, room_id, now + timedelta(days=2), now + timedelta(days=3))
    response = client.get("/rooms/101/reserve")
    html = response.get_data(as_text=True)
    assert response.status_code == 200 and "data-open-on-load" in html
    assert 'name="guest_name"' in html and 'name="guest_phone"' in html
    assert 'name="reserved_from"' in html and 'name="reserved_until"' in html
    assert 'name="csrf_token"' in html and "Xác nhận đặt trước" in html
    assert "101" in html and "VNĐ / đêm" in html and "Lịch đặt trước của phòng" in html
    assert "Sửa" in html and "Hủy đặt" in html


def test_reservation_after_active_checkout_keeps_room_and_rental_unchanged(client, app):
    assert _login(client).status_code == 302
    room_id, rental_id = _set_active_rental(app)
    with app.app_context():
        room = db.session.get(Room, room_id)
        before_room = (room.status, room.state, room.check_in, room.check_out)
        rental = db.session.get(RoomRental, rental_id)
        before_rental = (rental.rented_at, rental.expected_checkout, rental.duration_minutes, rental.nightly_rate, rental.total_price)
        start = rental.expected_checkout + timedelta(minutes=60)
    response = _create_reservation(client, start=start, end=start + timedelta(days=2))
    assert response.status_code == 302
    with app.app_context():
        reservation = db.session.execute(db.select(RoomReservation)).scalar_one()
        assert reservation.status == "booked" and reservation.room_id == room_id
        assert reservation.room_number == "101" and reservation.guest_name == "Nguyễn An"
        room = db.session.get(Room, room_id)
        assert (room.status, room.state, room.check_in, room.check_out) == before_room
        rental = db.session.get(RoomRental, rental_id)
        assert (rental.rented_at, rental.expected_checkout, rental.duration_minutes, rental.nightly_rate, rental.total_price) == before_rental
        assert reservation.nightly_rate == (room.price or 500000)
        assert reservation.duration_minutes == 2 * 24 * 60
        assert reservation.total_price == reservation.nightly_rate * 2


def test_reservation_overlapping_current_rental_is_rejected_and_checkout_boundary_allowed(client, app):
    assert _login(client).status_code == 302
    room_id, _rental_id = _set_active_rental(app)
    with app.app_context():
        rental = db.session.execute(db.select(RoomRental).where(RoomRental.room_id == room_id)).scalar_one()
        checkout = rental.expected_checkout
    response = _create_reservation(client, start=checkout-timedelta(minutes=1), end=checkout+timedelta(days=1))
    assert response.status_code == 400 and "60 phút" in response.get_data(as_text=True)
    response = _create_reservation(client, start=checkout+timedelta(minutes=60), end=checkout+timedelta(days=1))
    assert response.status_code == 302


@pytest.mark.parametrize("start,end,field", [("2026-10-10T12:00", "2026-10-10T12:00", "reserved_until"), ("2026-10-11T12:00", "2026-10-10T12:00", "reserved_until"), ("not-a-time", "2026-10-12T12:00", "reserved_from"), ("2020-01-01T12:00", "2020-01-02T12:00", "reserved_from")])
def test_reservation_rejects_invalid_or_past_datetimes(client, start, end, field):
    assert _login(client).status_code == 302
    response = client.post("/rooms/101/reserve", data={"csrf_token": _token(client, "/rooms/101/reserve"), **_reservation_data(start=datetime(2026,10,10,12), end=datetime(2026,10,12,12)), "reserved_from": start, "reserved_until": end})
    assert response.status_code == 400 and f'name="{field}"' in response.get_data(as_text=True)


@pytest.mark.parametrize("kind", ["inside", "contained", "contains", "tail"])
def test_booked_reservation_intervals_reject_every_overlap_shape(client, app, kind):
    assert _login(client).status_code == 302
    room_id = _room(app)
    now = _now_minute()
    old_start, old_end = now + timedelta(days=3), now + timedelta(days=5)
    _add_reservation(app, room_id, old_start, old_end)
    intervals = {"inside": (old_start+timedelta(hours=1), old_end+timedelta(hours=1)), "contained": (old_start+timedelta(hours=1), old_end-timedelta(hours=1)), "contains": (old_start-timedelta(hours=1), old_end+timedelta(hours=1)), "tail": (old_start-timedelta(hours=1), old_start+timedelta(hours=1))}
    response = _create_reservation(client, start=intervals[kind][0], end=intervals[kind][1])
    assert response.status_code == 400 and "60 phút" in response.get_data(as_text=True)


def test_adjacent_and_multiple_room_reservations_are_allowed(client, app):
    assert _login(client).status_code == 302
    first_id = _room(app, "101")
    second_id = _room(app, "102")
    now = _now_minute()
    start = now + timedelta(days=4)
    _add_reservation(app, first_id, start, start+timedelta(days=1))
    response = _create_reservation(client, start=start+timedelta(days=1, minutes=60), end=start+timedelta(days=2))
    assert response.status_code == 302
    response = _create_reservation(client, "102", start=start, end=start+timedelta(days=1))
    assert response.status_code == 302
    with app.app_context():
        assert db.session.execute(db.select(RoomReservation).where(RoomReservation.room_id == first_id)).scalars().all().__len__() == 2
        assert db.session.execute(db.select(RoomReservation).where(RoomReservation.room_id == second_id)).scalars().all().__len__() == 1


@pytest.mark.parametrize("status", ["cancelled", "completed"])
def test_cancelled_and_completed_reservations_do_not_block(client, app, status):
    assert _login(client).status_code == 302
    room_id = _room(app)
    start = _now_minute()+timedelta(days=3)
    _add_reservation(app, room_id, start, start+timedelta(days=1), status=status)
    response = _create_reservation(client, start=start, end=start+timedelta(hours=12))
    assert response.status_code == 302


def test_create_and_edit_refresh_rate_snapshot_and_cancel_frees_schedule(client, app):
    assert _login(client).status_code == 302
    room_id = _room(app)
    start = _now_minute()+timedelta(days=7)
    response = _create_reservation(client, start=start, end=start+timedelta(days=1))
    assert response.status_code == 302
    with app.app_context():
        reservation = db.session.execute(db.select(RoomReservation)).scalar_one()
        reservation_id = reservation.id
        room = db.session.get(Room, room_id)
        room.price = 750000
        db.session.commit()
    response = client.post(f"/rooms/101/reservations/{reservation_id}/edit", data={"csrf_token": _token(client, f"/rooms/101/reservations/{reservation_id}/edit"), **_reservation_data(start=start, end=start+timedelta(days=1), guest_name="Edited guest")})
    assert response.status_code == 302
    with app.app_context():
        reservation = db.session.get(RoomReservation, reservation_id)
        assert reservation.guest_name == "Edited guest" and reservation.nightly_rate == 750000 and reservation.total_price == 750000
    response = client.post(f"/rooms/101/reservations/{reservation_id}/cancel", data={"csrf_token": _token(client, "/rooms/101/reserve")})
    assert response.status_code == 302
    response = _create_reservation(client, start=start, end=start+timedelta(days=1))
    assert response.status_code == 302
    with app.app_context():
        assert db.session.get(RoomReservation, reservation_id).status == "cancelled"


def test_reservation_post_requires_auth_and_csrf(client):
    response = client.get("/rooms/101/reserve")
    assert response.status_code == 302 and response.headers["Location"].endswith("/login")
    assert _login(client).status_code == 302
    response = client.post("/rooms/101/reserve", data=_reservation_data())
    assert response.status_code == 400


def test_reservation_database_failure_rolls_back_without_room_mutation(client, app, monkeypatch):
    assert _login(client).status_code == 302
    room_id = _room(app)
    with app.app_context():
        room = db.session.get(Room, room_id)
        before = (room.status, room.state, room.check_in, room.check_out)
    def fail_commit(_session):
        raise SQLAlchemyError("simulated reservation failure")
    monkeypatch.setattr(Session, "commit", fail_commit)
    response = client.post("/rooms/101/reserve", data={"csrf_token": _token(client, "/rooms/101/reserve"), **_reservation_data()})
    assert response.status_code == 503
    with app.app_context():
        assert db.session.execute(db.select(RoomReservation)).scalars().all() == []
        room = db.session.get(Room, room_id)
        assert (room.status, room.state, room.check_in, room.check_out) == before


def test_immediate_rental_may_end_before_booking_but_not_overlap(client, app):
    assert _login(client).status_code == 302
    room_id = _room(app)
    now = _now_minute()
    booking_start = now + timedelta(hours=2)
    _add_reservation(app, room_id, booking_start, booking_start+timedelta(days=1))
    other_room_id = _room(app, "102")
    _add_reservation(app, other_room_id, booking_start, booking_start+timedelta(days=1))
    response = client.post("/rooms/101/rent", data={"csrf_token": _token(client, "/rooms/101/rent"), "expected_checkout": _local(now+timedelta(hours=1))})
    assert response.status_code == 302
    response = client.post("/rooms/102/rent", data={"csrf_token": _token(client, "/rooms/102/rent"), "expected_checkout": _local(now+timedelta(hours=3))})
    assert response.status_code == 400 and "60 phút" in response.get_data(as_text=True)
    with app.app_context():
        assert db.session.execute(db.select(RoomRental).where(RoomRental.room_id == room_id)).scalar_one_or_none() is not None
        assert db.session.execute(db.select(RoomRental).where(RoomRental.room_id == other_room_id)).scalar_one_or_none() is None


def test_rental_extension_cannot_overlap_future_booking_and_rejection_is_atomic(client, app):
    assert _login(client).status_code == 302
    now = _now_minute()
    room_id, rental_id = _set_active_rental(app, checkout=now+timedelta(hours=1))
    booking_start = now+timedelta(hours=4)
    _add_reservation(app, room_id, booking_start, booking_start+timedelta(days=1))
    with app.app_context():
        before = db.session.get(RoomRental, rental_id)
        values = (before.expected_checkout, before.duration_minutes, before.total_price, db.session.get(Room, room_id).check_out)
    response = client.post("/rooms/101/rent/edit", data={"csrf_token": _token(client, "/rooms/101/rent/edit"), "expected_checkout": _local(booking_start+timedelta(hours=1))})
    assert response.status_code == 400 and "60 phút" in response.get_data(as_text=True)
    with app.app_context():
        rental = db.session.get(RoomRental, rental_id)
        assert (rental.expected_checkout, rental.duration_minutes, rental.total_price, db.session.get(Room, room_id).check_out) == values
    response = client.post("/rooms/101/rent/edit", data={"csrf_token": _token(client, "/rooms/101/rent/edit"), "expected_checkout": _local(booking_start-timedelta(minutes=60))})
    assert response.status_code == 302


def test_early_checkout_keeps_booked_reservation_unchanged(client, app):
    assert _login(client).status_code == 302
    room_id, _rental_id = _set_active_rental(app)
    with app.app_context():
        current = db.session.execute(db.select(RoomRental).where(RoomRental.room_id == room_id)).scalar_one()
        start = current.expected_checkout+timedelta(days=1)
    reservation_id = _add_reservation(app, room_id, start, start+timedelta(days=1))
    response = client.post("/rooms/101/checkout", data={"csrf_token": _token(client, "/rooms")})
    assert response.status_code == 302
    with app.app_context():
        room = db.session.get(Room, room_id)
        reservation = db.session.get(RoomReservation, reservation_id)
        assert (room.status, room.state, room.check_in, room.check_out) == ("Dọn dẹp", "cleaning", None, None)
        assert reservation.status == "booked" and reservation.reserved_from == start
    completed = client.post("/rooms/101/cleaning/complete", data={"csrf_token": _token(client, "/rooms")})
    assert completed.status_code == 302
    with app.app_context():
        room = db.session.get(Room, room_id)
        reservation = db.session.get(RoomReservation, reservation_id)
        assert (room.status, room.state) == ("Phòng trống", "empty")
        assert reservation.status == "booked" and reservation.reserved_from == start


def test_nearest_booked_reservation_summary_ignores_cancelled_and_other_rooms(client, app):
    assert _login(client).status_code == 302
    first_id, second_id = _room(app, "101"), _room(app, "102")
    now = _now_minute()
    _add_reservation(app, first_id, now+timedelta(days=4), now+timedelta(days=5), status="cancelled")
    _add_reservation(app, first_id, now+timedelta(days=6), now+timedelta(days=7))
    _add_reservation(app, first_id, now+timedelta(days=8), now+timedelta(days=9))
    _add_reservation(app, second_id, now+timedelta(days=2), now+timedelta(days=3))
    html = client.get("/rooms").get_data(as_text=True)
    card101 = re.search(r'aria-label="Phòng 101, [^"]+"[^>]*>(.*?)</article>', html, re.S).group(1)
    card102 = re.search(r'aria-label="Phòng 102, [^"]+"[^>]*>(.*?)</article>', html, re.S).group(1)
    assert (now+timedelta(days=6)).strftime("%d/%m/%Y %H:%M") in card101
    assert (now+timedelta(days=8)).strftime("%d/%m/%Y %H:%M") not in card101
    assert (now+timedelta(days=2)).strftime("%d/%m/%Y %H:%M") in card102


def test_occupied_card_actions_are_ordered_and_image_is_not_dimmed(client, app):
    assert _login(client).status_code == 302
    _set_active_rental(app)
    html = client.get("/rooms").get_data(as_text=True)
    card = re.search(r'<article\s+class="room-card[^"]+"\s+aria-label="Phòng 101, Đang thuê"[^>]*>(.*?)</article>', html, re.S).group(1)
    checkout, reserve, adjust = card.index("Trả phòng"), card.index("Đặt trước"), card.index("Điều chỉnh thuê")
    assert checkout < reserve < adjust
    assert 'method="post"' in card and "csrf_token" in card
    assert 'href="/rooms/101/rent/edit"' in card
    assert 'href="/rooms/101/reserve"' in card
    css = (Path(__file__).resolve().parents[1] / "src/hotel_app/static/css/hotel.css").read_text(encoding="utf-8")
    assert ".room-card--occupied .room-image" not in css
    assert "grayscale" not in css and "saturate(0.25)" not in css
    assert ".room-card--occupied {" in css and "var(--red-soft)" in css
    assert ".room-card--empty {" in css and "var(--green-soft)" in css
    assert ".room-actions { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr))" in css
    assert ".room-actions__full { grid-column: 1 / -1; }" in css
    assert "room-status--occupied" in card and "Đang thuê" in card


def test_booked_reservation_prevents_room_delete_and_history_detaches(client, app):
    assert _login(client).status_code == 302
    room_id = _room(app)
    now = _now_minute()
    booked_id = _add_reservation(app, room_id, now+timedelta(days=2), now+timedelta(days=3))
    response = client.post("/rooms/101/delete", data={"csrf_token": _token(client, "/rooms")})
    assert response.status_code == 302 and "lịch đặt trước đang hiệu lực" in client.get("/rooms").get_data(as_text=True)
    with app.app_context():
        assert db.session.get(Room, room_id) is not None and db.session.get(RoomReservation, booked_id).status == "booked"
        db.session.get(RoomReservation, booked_id).status = "cancelled"
        db.session.commit()
    response = client.post("/rooms/101/delete", data={"csrf_token": _token(client, "/rooms")})
    assert response.status_code == 302
    with app.app_context():
        history = db.session.get(RoomReservation, booked_id)
        assert history is not None and history.status == "cancelled" and history.room_id is None and history.room_number == "101"


def test_selective_room_type_transfer_keeps_reservation_link_and_history(client, app):
    assert _login(client).status_code == 302
    with app.app_context():
        room = db.session.execute(db.select(Room).where(Room.number == "101")).scalar_one()
        room_id = room.id
        source_name = room.type
    now = _now_minute()
    reservation_id = _add_reservation(app, room_id, now+timedelta(days=2), now+timedelta(days=3))
    with app.app_context():
        source_type = RoomType(name="Source transfer test", price=0, quantity=0, capacity="", description="", status="active")
        target_type = RoomType(name="Target transfer test", price=0, quantity=0, capacity="", description="", status="active")
        db.session.add_all([source_type, target_type])
        db.session.commit()
        source_type_id, target_type_id = source_type.id, target_type.id
        db.session.get(Room, room_id).type = "Source transfer test"
        db.session.commit()
    html = client.get("/room-types").get_data(as_text=True)
    token = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', html).group(1)
    response = client.post(f"/room-types/{source_type_id}/transfer", data={"csrf_token": token, "target_room_type_id": str(target_type_id), "selected_room_ids": [str(room_id)]})
    assert response.status_code == 302
    with app.app_context():
        reservation = db.session.get(RoomReservation, reservation_id)
        assert reservation.room_id == room_id and reservation.room_number == "101" and reservation.status == "booked"



def test_additive_app_recreation_preserves_existing_tables_and_rows(app):
    database_uri = app.config["SQLALCHEMY_DATABASE_URI"]
    with app.app_context():
        user_count = db.session.execute(db.select(db.func.count(User.id))).scalar_one()
        room_id = db.session.execute(db.select(Room.id).where(Room.number == "101")).scalar_one()
        now = _now_minute()
        rental = RoomRental(room_id=room_id, room_number="101", rented_at=now-timedelta(days=2), expected_checkout=now-timedelta(days=1), duration_minutes=1440, nightly_rate=500000, total_price=500000)
        db.session.add(rental)
        db.session.commit()
        rental_id = rental.id
        reservation_id = _add_reservation(app, room_id, now+timedelta(days=2), now+timedelta(days=3))
    with app.app_context():
        db.session.remove()
        db.engine.dispose()
    restarted = create_app({"APP_ENV": "testing", "TESTING": True, "SECRET_KEY": "test-only-secret-key", "SQLALCHEMY_DATABASE_URI": database_uri, "SESSION_COOKIE_SECURE": False})
    with restarted.app_context():
        assert inspect(db.engine).has_table("room_reservations")
        assert db.session.execute(db.select(db.func.count(User.id))).scalar_one() == user_count
        assert db.session.get(Room, room_id) is not None
        assert db.session.get(RoomRental, rental_id).room_number == "101"
        assert db.session.get(RoomReservation, reservation_id).room_id == room_id


def test_reservation_on_empty_room_preserves_empty_state(client, app):
    assert _login(client).status_code == 302
    room_id = _room(app)
    with app.app_context():
        room = db.session.get(Room, room_id)
        before = (room.status, room.state, room.check_in, room.check_out)
    response = _create_reservation(client, start=_now_minute()+timedelta(days=2), end=_now_minute()+timedelta(days=3))
    assert response.status_code == 302
    with app.app_context():
        room = db.session.get(Room, room_id)
        assert (room.status, room.state, room.check_in, room.check_out) == before == ("Phòng trống", "empty", None, None)


def test_invalid_room_is_handled_safely(client):
    assert _login(client).status_code == 302
    response = client.post("/rooms/UNKNOWN/reserve", data={"csrf_token": _token(client, "/rooms"), **_reservation_data()})
    assert response.status_code == 302
    assert "Không tìm thấy phòng cần đặt trước." in client.get("/rooms").get_data(as_text=True)


def test_csrf_rejection_keeps_authenticated_session(client):
    assert _login(client).status_code == 302
    response = client.post("/rooms/101/reserve", data=_reservation_data())
    assert response.status_code == 400
    assert client.get("/rooms").status_code == 200



def test_guest_phone_and_name_validation_are_server_side(client):
    assert _login(client).status_code == 302
    data = _reservation_data(guest_name="   ", guest_phone="12345")
    response = client.post("/rooms/101/reserve", data={"csrf_token": _token(client, "/rooms/101/reserve"), **data})
    html = response.get_data(as_text=True)
    assert response.status_code == 400
    assert "Vui lòng nhập tên khách hàng." in html and "Số điện thoại không hợp lệ." in html


def test_occupied_room_without_current_rental_cannot_be_reserved(client, app):
    assert _login(client).status_code == 302
    room_id = _room(app)
    with app.app_context():
        room = db.session.get(Room, room_id)
        room.status = "Đang thuê"
        room.state = "occupied"
        db.session.commit()
    response = _create_reservation(client)
    assert response.status_code == 400 and "Không thể xác định lượt thuê hiện tại" in response.get_data(as_text=True)
    with app.app_context():
        assert db.session.execute(db.select(RoomReservation)).scalars().all() == []


def test_editing_booking_into_another_booking_is_rejected_without_mutation(client, app):
    assert _login(client).status_code == 302
    room_id = _room(app)
    now = _now_minute()
    first_start = now+timedelta(days=4)
    second_start = now+timedelta(days=8)
    first_id = _add_reservation(app, room_id, first_start, first_start+timedelta(days=1))
    second_id = _add_reservation(app, room_id, second_start, second_start+timedelta(days=1))
    response = client.post(f"/rooms/101/reservations/{first_id}/edit", data={
        "csrf_token": _token(client, f"/rooms/101/reservations/{first_id}/edit"),
        **_reservation_data(start=second_start, end=second_start+timedelta(hours=12)),
    })
    assert response.status_code == 400 and "60 phút" in response.get_data(as_text=True)
    with app.app_context():
        first, second = db.session.get(RoomReservation, first_id), db.session.get(RoomReservation, second_id)
        assert first.reserved_from == first_start and first.reserved_until == first_start+timedelta(days=1)
        assert second.reserved_from == second_start


def test_failed_cancel_rolls_back_booked_status(client, app, monkeypatch):
    assert _login(client).status_code == 302
    room_id = _room(app)
    now = _now_minute()
    reservation_id = _add_reservation(app, room_id, now+timedelta(days=4), now+timedelta(days=5))
    def fail_commit(_session):
        raise SQLAlchemyError("simulated cancel failure")
    monkeypatch.setattr(Session, "commit", fail_commit)
    response = client.post(f"/rooms/101/reservations/{reservation_id}/cancel", data={"csrf_token": _token(client, "/rooms/101/reserve")})
    assert response.status_code == 302
    with app.app_context():
        assert db.session.get(RoomReservation, reservation_id).status == "booked"


def test_no_upcoming_reservation_adds_no_empty_summary(client):
    assert _login(client).status_code == 302
    html = client.get("/rooms").get_data(as_text=True)
    assert "Đặt trước tiếp theo:" not in html


def test_completed_history_detaches_when_room_is_deleted(client, app):
    assert _login(client).status_code == 302
    room_id = _room(app, "102")
    now = _now_minute()
    reservation_id = _add_reservation(app, room_id, now+timedelta(days=2), now+timedelta(days=3), status="completed")
    response = client.post("/rooms/102/delete", data={"csrf_token": _token(client, "/rooms")})
    assert response.status_code == 302
    with app.app_context():
        history = db.session.get(RoomReservation, reservation_id)
        assert db.session.get(Room, room_id) is None
        assert history is not None and history.status == "completed" and history.room_id is None and history.room_number == "102"
