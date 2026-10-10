"""Regression tests for current-year monthly rental income reporting."""

from __future__ import annotations

import importlib
import re
from datetime import datetime

from conftest import DEMO_EMAIL
from hotel_app.app import format_vnd, get_monthly_income
from hotel_app.extensions import db
from hotel_app.models import Room, RoomRental, RoomReservation, RoomServiceLog, User


def _add_rental(rented_at: datetime, total_price: int, *, room_id=None) -> RoomRental:
    rental = RoomRental(
        room_id=room_id,
        room_number="101",
        rented_at=rented_at,
        expected_checkout=rented_at.replace(hour=23, minute=59),
        duration_minutes=60,
        nightly_rate=900_000,
        total_price=total_price,
    )
    db.session.add(rental)
    return rental


def _authenticate(app, client) -> None:
    with app.app_context():
        user_id = db.session.execute(
            db.select(User.id).where(User.email == DEMO_EMAIL)
        ).scalar_one()
    with client.session_transaction() as session:
        session["user_id"] = user_id


def test_monthly_aggregation_sums_saved_rental_totals_once(app):
    with app.app_context():
        _add_rental(datetime(2034, 1, 1, 0, 0), 125_000)
        _add_rental(datetime(2034, 1, 31, 23, 59), 375_000)
        cross_year = _add_rental(datetime(2034, 10, 31, 22, 0), 2_000_000)
        cross_year.expected_checkout = datetime(2035, 11, 2, 12, 0)
        db.session.commit()

        report = get_monthly_income(2034)

        assert report["year"] == 2034
        assert list(report["monthly_totals"]) == list(range(1, 13))
        assert report["monthly_totals"][1] == 500_000
        assert report["monthly_totals"][2] == 0
        assert report["monthly_totals"][3] == 0
        assert report["monthly_totals"][10] == 2_000_000
        assert report["monthly_totals"][11] == 0
        assert report["annual_total"] == sum(report["monthly_totals"].values()) == 2_500_000


def test_empty_year_contains_twelve_zero_months(app):
    with app.app_context():
        report = get_monthly_income(2034)
    assert report["monthly_totals"] == {month: 0 for month in range(1, 13)}
    assert report["annual_total"] == 0
    assert format_vnd(0) == "0 VNĐ"
    assert format_vnd(500_000) == "500.000 VNĐ"
    assert format_vnd(1_500_000) == "1.500.000 VNĐ"
    assert format_vnd(12_345_678) == "12.345.678 VNĐ"


def test_year_boundaries_are_inclusive_at_start_and_exclusive_at_end(app):
    with app.app_context():
        _add_rental(datetime(2033, 12, 31, 23, 59), 11)
        _add_rental(datetime(2034, 1, 1, 0, 0), 100)
        _add_rental(datetime(2034, 12, 31, 23, 59), 200)
        _add_rental(datetime(2035, 1, 1, 0, 0), 22)
        db.session.commit()
        report = get_monthly_income(2034)
    assert report["monthly_totals"][1] == 100
    assert report["monthly_totals"][12] == 200
    assert report["annual_total"] == 300


def test_detached_rental_and_adjusted_saved_total_are_counted_once(app):
    with app.app_context():
        rental = _add_rental(datetime(2034, 7, 31, 23, 45), 123_000, room_id=None)
        db.session.commit()
        rental_id = rental.id
        rental = db.session.get(RoomRental, rental_id)
        rental.total_price = 456_000
        db.session.commit()
        report = get_monthly_income(2034)
    assert report["monthly_totals"][7] == 456_000
    assert report["annual_total"] == 456_000


def test_reservations_and_service_logs_are_not_income(app):
    with app.app_context():
        for status in ("booked", "cancelled", "completed"):
            db.session.add(RoomReservation(
                room_id=None,
                room_number="101",
                guest_name="Test guest",
                guest_phone="0123456789",
                reserved_from=datetime(2034, 3, 1),
                reserved_until=datetime(2034, 3, 2),
                duration_minutes=1440,
                nightly_rate=1_000_000,
                total_price=1_000_000,
                status=status,
                created_at=datetime(2034, 2, 1),
            ))
        db.session.add(RoomServiceLog(
            room_id=None,
            room_number="101",
            service_type="cleaning",
            started_at=datetime(2034, 3, 1),
            ended_at=datetime(2034, 3, 1, 1),
        ))
        _add_rental(datetime(2034, 3, 1), 250_000)
        db.session.commit()
        report = get_monthly_income(2034)
    assert report["monthly_totals"][3] == 250_000
    assert report["annual_total"] == 250_000


def test_statistics_route_is_authenticated_and_renders_current_year_only(app, client, monkeypatch):
    app_module = importlib.import_module("hotel_app.app")

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2034, 6, 15, 12, 0, 0, tzinfo=tz)

    monkeypatch.setattr(app_module, "datetime", FrozenDateTime)
    anonymous = client.get("/income-statistics")
    assert anonymous.status_code == 302
    assert anonymous.headers["Location"].endswith("/login")

    with app.app_context():
        _add_rental(datetime(2034, 6, 1, 10), 500_000)
        _add_rental(datetime(2033, 6, 1, 10), 900_000)
        db.session.commit()
    _authenticate(app, client)
    response = client.get("/income-statistics?year=2033")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Năm 2034" in html
    assert [int(month) for month in re.findall(r'<th scope="row">Tháng (\d+)</th>', html)] == list(range(1, 13))
    assert "500.000 VNĐ" in html
    assert "900.000 VNĐ" not in html
    table = re.search(r'<table class="income-statistics__table">(.*?)</table>', html, re.S)
    assert table is not None
    table_html = table.group(1)
    tbody = re.search(r"<tbody>(.*?)</tbody>", table_html, re.S)
    assert tbody is not None
    body_rows = re.findall(r"<tr>(.*?)</tr>", tbody.group(1), re.S)
    assert len(body_rows) == 12
    assert all(len(re.findall(r"<(?:th|td)\b", row)) == 2 for row in body_rows)
    assert table_html.count('<th scope="col">') == 2
    assert len(re.findall(r"<table\b", html)) == 1
    footer = re.search(r"<tfoot>(.*?)</tfoot>", table_html, re.S)
    assert footer is not None
    footer_rows = re.findall(r"<tr>(.*?)</tr>", footer.group(1), re.S)
    assert len(footer_rows) == 1
    assert len(re.findall(r"<(?:th|td)\b", footer_rows[0])) == 2
    assert '<tr><th scope="row">Tổng cộng</th><td>500.000 VNĐ</td></tr>' in table_html
    assert 'href="/income-statistics" aria-current="page"' in html
    assert "Thống kê thu nhập" in html
    assert 'class="dashboard-shell"' in html
    assert 'class="topbar"' in html


def test_empty_statistics_page_displays_twelve_zero_rows_and_zero_total(app, client):
    _authenticate(app, client)
    response = client.get("/income-statistics")
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    table = re.search(r'<table class="income-statistics__table">(.*?)</table>', html, re.S)
    assert table is not None
    table_html = table.group(1)
    tbody = re.search(r"<tbody>(.*?)</tbody>", table_html, re.S)
    assert tbody is not None
    assert len(re.findall(r"<tr>", tbody.group(1))) == 12
    assert tbody.group(1).count("0 VNĐ") == 12
    assert '<tr><th scope="row">Tổng cộng</th><td>0 VNĐ</td></tr>' in table_html


def test_income_statistics_pdf_export_is_authenticated_and_downloadable(app, client):
    anonymous = client.get("/income-statistics/export")
    assert anonymous.status_code == 302
    assert anonymous.headers["Location"].endswith("/login")

    _authenticate(app, client)
    response = client.get("/income-statistics/export")

    assert response.status_code == 200
    assert response.mimetype == "application/pdf"
    assert response.headers["Content-Disposition"].startswith(
        f"attachment; filename=thong-ke-thu-nhap-{datetime.now().year}.pdf"
    )
    assert response.data.startswith(b"%PDF-")
    assert b"/Type /Page" in response.data


def test_integrated_2026_report_updates_rental_once_and_ignores_reservation(app):
    with app.app_context():
        room = Room(number="TEST-INCOME-2034", floor="Test", type="Test", price=9_000_000, status="Đang thuê", state="occupied")
        db.session.add(room)
        db.session.flush()
        _add_rental(datetime(2026, 1, 5, 10), 500_000, room_id=room.id)
        _add_rental(datetime(2026, 1, 20, 11), 250_000)
        rental_c = _add_rental(datetime(2026, 3, 15, 12), 1_200_000)
        _add_rental(datetime(2025, 12, 31, 23, 59), 900_000)
        _add_rental(datetime(2027, 1, 1, 0, 0), 700_000)
        db.session.add(RoomReservation(
            room_id=None,
            room_number="101",
            guest_name="Future reservation",
            guest_phone="0123456789",
            reserved_from=datetime(2026, 4, 1),
            reserved_until=datetime(2026, 4, 2),
            duration_minutes=1440,
            nightly_rate=5_000_000,
            total_price=5_000_000,
            status="booked",
            created_at=datetime(2026, 1, 1),
        ))
        db.session.commit()

        report = get_monthly_income(2026)
        assert report["monthly_totals"][1] == 750_000
        assert report["monthly_totals"][2] == 0
        assert report["monthly_totals"][3] == 1_200_000
        assert report["monthly_totals"][4] == 0
        assert report["monthly_totals"][12] == 0
        assert report["annual_total"] == 1_950_000

        rental_c.total_price = 1_500_000
        db.session.commit()
        adjusted = get_monthly_income(2026)

        assert adjusted["monthly_totals"][3] == 1_500_000
        assert adjusted["annual_total"] == 2_250_000
