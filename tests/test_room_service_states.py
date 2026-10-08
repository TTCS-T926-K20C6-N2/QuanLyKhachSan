"""Acceptance tests for the room cleaning and maintenance lifecycle."""

from __future__ import annotations

import re
from datetime import datetime, timedelta

import pytest
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from conftest import DEMO_EMAIL, DEMO_PASSWORD
from hotel_app.extensions import db
from hotel_app.models import Room, RoomReservation, RoomServiceLog


def _token(client, path):
    html = client.get(path).get_data(as_text=True)
    match = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', html)
    assert match is not None
    return match.group(1)


def _login(client):
    return client.post("/login", data={"csrf_token": _token(client, "/login"), "email": DEMO_EMAIL, "password": DEMO_PASSWORD})


def _room(app, number="101"):
    with app.app_context():
        return db.session.execute(db.select(Room).where(Room.number == number)).scalar_one().id


def _edit_data(client, number, status, **extra):
    path = f"/rooms/{number}/edit"
    html = client.get(path).get_data(as_text=True)
    room_type = re.search(r'<option value="([^"]+)" selected', html)
    assert room_type is not None
    return {"csrf_token": _token(client, path), "room_number": number, "description": "Service state test", "price": "500000", "room_type": room_type.group(1), "status": status, **extra}


def _active_log(app, room_id):
    with app.app_context():
        return db.session.execute(db.select(RoomServiceLog).where(RoomServiceLog.room_id == room_id, RoomServiceLog.ended_at.is_(None))).scalars().all()


def test_checkout_starts_cleaning_and_completion_closes_service(client, app):
    assert _login(client).status_code == 302
    rent_token = _token(client, "/rooms/101/rent")
    rented = client.post("/rooms/101/rent", data={"csrf_token": rent_token, "expected_checkout": (datetime.now().replace(second=0, microsecond=0) + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M")})
    assert rented.status_code == 302
    checkout = client.get("/rooms").get_data(as_text=True)
    form = re.search(r'<form(?:(?!>).)*class="room-checkout"(?:(?!>).)*action="/rooms/101/checkout"[^>]*>(.*?)</form>', checkout, re.S)
    assert form is not None
    csrf = re.search(r'name="csrf_token" value="([^"]+)"', form.group(1))
    assert csrf is not None
    assert client.post("/rooms/101/checkout", data={"csrf_token": csrf.group(1)}).status_code == 302
    room_id = _room(app)
    with app.app_context():
        room = db.session.get(Room, room_id)
        assert (room.status, room.state, room.check_in, room.check_out) == ("Dọn dẹp", "cleaning", None, None)
    active = _active_log(app, room_id)
    assert len(active) == 1 and active[0].service_type == "cleaning"
    assert client.post("/rooms/101/cleaning/complete", data={"csrf_token": _token(client, "/rooms")}).status_code == 302
    assert _active_log(app, room_id) == []
    with app.app_context():
        room = db.session.get(Room, room_id)
        logs = db.session.execute(db.select(RoomServiceLog).where(RoomServiceLog.room_id == room_id).order_by(RoomServiceLog.id)).scalars().all()
        assert (room.status, room.state) == ("Phòng trống", "empty")
        assert len(logs) == 1 and logs[0].ended_at is not None


def test_empty_room_can_enter_maintenance_then_cleaning(client, app):
    assert _login(client).status_code == 302
    room_id = _room(app)
    response = client.post("/rooms/101/edit", data=_edit_data(client, "101", "Bảo trì", maintenance_note="Kiểm tra điều hòa"), content_type="multipart/form-data")
    assert response.status_code == 302
    active = _active_log(app, room_id)
    assert len(active) == 1 and active[0].service_type == "maintenance" and active[0].note == "Kiểm tra điều hòa"
    page = client.get("/rooms?status=maintenance").get_data(as_text=True)
    assert 'aria-label="Phòng 101, Bảo trì"' in page
    assert "Hoàn tất bảo trì" in page
    assert client.post("/rooms/101/maintenance/complete", data={"csrf_token": _token(client, "/rooms")}).status_code == 302
    active = _active_log(app, room_id)
    assert len(active) == 1 and active[0].service_type == "cleaning"
    with app.app_context():
        logs = db.session.execute(db.select(RoomServiceLog).where(RoomServiceLog.room_id == room_id).order_by(RoomServiceLog.id)).scalars().all()
        assert [log.service_type for log in logs] == ["maintenance", "cleaning"]
        assert logs[0].ended_at == logs[1].started_at


def test_service_completion_rejects_missing_or_duplicate_active_log(client, app):
    assert _login(client).status_code == 302
    room_id = _room(app)
    with app.app_context():
        room = db.session.get(Room, room_id)
        room.status, room.state = "Dọn dẹp", "cleaning"
        db.session.commit()
    response = client.post("/rooms/101/cleaning/complete", data={"csrf_token": _token(client, "/rooms")})
    assert response.status_code == 302
    assert _active_log(app, room_id) == []
    with app.app_context():
        room = db.session.get(Room, room_id)
        assert (room.status, room.state) == ("Dọn dẹp", "cleaning")


def test_service_log_active_room_unique_index(app):
    room_id = _room(app)
    with app.app_context():
        room = db.session.get(Room, room_id)
        now = datetime.now().replace(second=0, microsecond=0)
        db.session.add(RoomServiceLog(room_id=room.id, room_number=room.number, service_type="cleaning", started_at=now))
        db.session.commit()
        db.session.add(RoomServiceLog(room_id=room.id, room_number=room.number, service_type="maintenance", started_at=now))
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


def test_cleaning_can_become_maintenance_without_losing_bookings(client, app):
    assert _login(client).status_code == 302
    room_id = _room(app)
    start = datetime.now().replace(second=0, microsecond=0)
    with app.app_context():
        room = db.session.get(Room, room_id)
        db.session.add(RoomServiceLog(room_id=room.id, room_number=room.number, service_type="cleaning", started_at=start))
        room.status, room.state = "Dọn dẹp", "cleaning"
        reservation = RoomReservation(
            room_id=room.id, room_number=room.number, guest_name="Test Guest", guest_phone="0912345678",
            reserved_from=start.replace(hour=0, minute=0) + timedelta(days=2),
            reserved_until=start.replace(hour=0, minute=0) + __import__("datetime").timedelta(days=3),
            duration_minutes=1440, nightly_rate=500000, total_price=500000, status="booked", created_at=start,
        )
        db.session.add(reservation)
        db.session.commit()
        reservation_id = reservation.id
    before = _active_log(app, room_id)[0].started_at
    response = client.post("/rooms/101/edit", data=_edit_data(client, "101", "Bảo trì", maintenance_note="Sửa máy lạnh"), content_type="multipart/form-data")
    assert response.status_code == 302
    page = client.get("/rooms?status=maintenance").get_data(as_text=True)
    assert "lịch đặt trước đang hiệu lực" in page
    assert client.get("/rooms/101/reserve").status_code == 302
    active = _active_log(app, room_id)
    assert len(active) == 1 and active[0].service_type == "maintenance"
    with app.app_context():
        logs = db.session.execute(db.select(RoomServiceLog).where(RoomServiceLog.room_id == room_id).order_by(RoomServiceLog.id)).scalars().all()
        reservation = db.session.get(RoomReservation, reservation_id)
        assert logs[0].ended_at == logs[1].started_at and logs[0].started_at == before
        assert reservation is not None and reservation.status == "booked"
        assert reservation.room_id == room_id
    assert client.post("/rooms/101/maintenance/complete", data={"csrf_token": _token(client, "/rooms")}).status_code == 302
    with app.app_context():
        reservation = db.session.get(RoomReservation, reservation_id)
        room = db.session.get(Room, room_id)
        assert reservation.status == "booked" and reservation.room_id == room_id
        assert (room.status, room.state) == ("Dọn dẹp", "cleaning")


@pytest.mark.parametrize(("status", "state", "service_type"), [("Dọn dẹp", "cleaning", "cleaning"), ("Bảo trì", "maintenance", "maintenance")])
def test_new_reservation_is_rejected_while_room_is_serviced(client, app, status, state, service_type):
    assert _login(client).status_code == 302
    room_id = _room(app)
    if state == "maintenance":
        assert client.post("/rooms/101/edit", data=_edit_data(client, "101", status), content_type="multipart/form-data").status_code == 302
    else:
        with app.app_context():
            room = db.session.get(Room, room_id)
            room.status, room.state = status, state
            now = datetime.now().replace(second=0, microsecond=0)
            db.session.add(RoomServiceLog(room_id=room_id, room_number=room.number, service_type=service_type, started_at=now))
            db.session.commit()
    response = client.post("/rooms/101/reserve", data={"csrf_token": _token(client, "/rooms"), "guest_name": "Test", "guest_phone": "0912345678"})
    assert response.status_code == 302
    with app.app_context():
        assert db.session.execute(db.select(RoomReservation.id).where(RoomReservation.room_id == room_id)).first() is None


def test_room_type_transfer_preserves_service_state_and_log(client, app):
    assert _login(client).status_code == 302
    room_id = _room(app)
    assert client.post("/rooms/101/edit", data=_edit_data(client, "101", "Bảo trì"), content_type="multipart/form-data").status_code == 302
    csrf = _token(client, "/room-types")
    response = client.post("/room-types/1/transfer", data={"csrf_token": csrf, "target_room_type_id": "2", "selected_room_ids": str(room_id)})
    assert response.status_code == 302
    with app.app_context():
        room = db.session.get(Room, room_id)
        log = db.session.execute(db.select(RoomServiceLog).where(RoomServiceLog.room_id == room_id, RoomServiceLog.ended_at.is_(None))).scalar_one()
        assert (room.status, room.state, room.type) == ("Bảo trì", "maintenance", "Phòng đôi")
        assert log.service_type == "maintenance"


def test_room_delete_detaches_closed_service_history(client, app):
    assert _login(client).status_code == 302
    room_id = _room(app)
    started = datetime.now().replace(second=0, microsecond=0)
    with app.app_context():
        room = db.session.get(Room, room_id)
        db.session.add(RoomServiceLog(room_id=room.id, room_number=room.number, service_type="cleaning", started_at=started, ended_at=started))
        db.session.commit()
    response = client.post("/rooms/101/delete", data={"csrf_token": _token(client, "/rooms")})
    assert response.status_code == 302
    with app.app_context():
        log = db.session.execute(db.select(RoomServiceLog).where(RoomServiceLog.room_number == "101")).scalar_one()
        assert log.room_id is None and log.room_number == "101" and log.ended_at == started


def test_cleaning_to_maintenance_database_failure_rolls_back(client, app, monkeypatch):
    assert _login(client).status_code == 302
    room_id = _room(app)
    started = datetime.now().replace(second=0, microsecond=0)
    with app.app_context():
        room = db.session.get(Room, room_id)
        room.status, room.state = "Dọn dẹp", "cleaning"
        db.session.add(RoomServiceLog(room_id=room_id, room_number=room.number, service_type="cleaning", started_at=started))
        db.session.commit()
    def fail_commit(_session):
        raise SQLAlchemyError("simulated service transition failure")
    monkeypatch.setattr(Session, "commit", fail_commit)
    response = client.post("/rooms/101/edit", data=_edit_data(client, "101", "Bảo trì"), content_type="multipart/form-data")
    assert response.status_code == 503
    with app.app_context():
        room = db.session.get(Room, room_id)
        logs = db.session.execute(db.select(RoomServiceLog).where(RoomServiceLog.room_id == room_id)).scalars().all()
        assert (room.status, room.state) == ("Dọn dẹp", "cleaning")
        assert len(logs) == 1 and logs[0].service_type == "cleaning" and logs[0].ended_at is None


@pytest.mark.parametrize(("status", "state", "service_type"), [("Đang thuê", "occupied", None), ("Dọn dẹp", "cleaning", "cleaning"), ("Bảo trì", "maintenance", "maintenance")])
def test_delete_rejects_occupied_and_active_service_rooms(client, app, status, state, service_type):
    assert _login(client).status_code == 302
    room_id = _room(app)
    with app.app_context():
        room = db.session.get(Room, room_id)
        room.status, room.state = status, state
        if service_type:
            now = datetime.now().replace(second=0, microsecond=0)
            db.session.add(RoomServiceLog(room_id=room_id, room_number=room.number, service_type=service_type, started_at=now))
        db.session.commit()
    response = client.post("/rooms/101/delete", data={"csrf_token": _token(client, "/rooms")})
    assert response.status_code == 302
    with app.app_context():
        assert db.session.get(Room, room_id) is not None


def test_empty_room_with_active_service_log_cannot_be_deleted(client, app):
    assert _login(client).status_code == 302
    room_id = _room(app)
    with app.app_context():
        room = db.session.get(Room, room_id)
        now = datetime.now().replace(second=0, microsecond=0)
        db.session.add(RoomServiceLog(room_id=room_id, room_number=room.number, service_type="cleaning", started_at=now))
        db.session.commit()
    client.post("/rooms/101/delete", data={"csrf_token": _token(client, "/rooms")})
    with app.app_context():
        assert db.session.get(Room, room_id) is not None


@pytest.mark.parametrize(("status", "state", "service_type"), [("Dọn dẹp", "cleaning", "cleaning"), ("Bảo trì", "maintenance", "maintenance")])
def test_type_transfer_preserves_each_active_service_state(client, app, status, state, service_type):
    assert _login(client).status_code == 302
    room_id = _room(app)
    started = datetime.now().replace(second=0, microsecond=0)
    with app.app_context():
        room = db.session.get(Room, room_id)
        room.status, room.state = status, state
        db.session.add(RoomServiceLog(room_id=room_id, room_number=room.number, service_type=service_type, started_at=started))
        db.session.commit()
    response = client.post("/room-types/1/transfer", data={"csrf_token": _token(client, "/room-types"), "target_room_type_id": "2", "selected_room_ids": str(room_id)})
    assert response.status_code == 302
    with app.app_context():
        room = db.session.get(Room, room_id)
        log = db.session.execute(db.select(RoomServiceLog).where(RoomServiceLog.room_id == room_id, RoomServiceLog.ended_at.is_(None))).scalar_one()
        assert (room.type, room.status, room.state) == ("Phòng đôi", status, state)
        assert (log.service_type, log.started_at) == (service_type, started)


@pytest.mark.parametrize(("status", "state"), [("Dọn dẹp", "cleaning"), ("Bảo trì", "maintenance")])
def test_room_rent_get_and_post_reject_service_states(client, app, status, state):
    assert _login(client).status_code == 302
    room_id = _room(app)
    with app.app_context():
        room = db.session.get(Room, room_id)
        room.status, room.state = status, state
        now = datetime.now().replace(second=0, microsecond=0)
        service_type = "cleaning" if state == "cleaning" else "maintenance"
        db.session.add(RoomServiceLog(room_id=room_id, room_number=room.number, service_type=service_type, started_at=now))
        db.session.commit()
    assert client.get("/rooms/101/rent").status_code == 302
    assert client.post("/rooms/101/rent", data={"csrf_token": _token(client, "/rooms"), "expected_checkout": (datetime.now() + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M")}).status_code == 400
