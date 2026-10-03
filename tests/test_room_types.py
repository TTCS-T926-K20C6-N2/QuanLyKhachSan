"""Acceptance tests for the room type search page."""

from __future__ import annotations

import re
from copy import deepcopy
from html import unescape
from io import BytesIO

import pytest
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from conftest import DEMO_EMAIL, DEMO_PASSWORD, create_app
from hotel_app.app import ROOM_FLOORS, ROOM_TYPE_CATALOG
from hotel_app.extensions import db
from hotel_app.models import Room, RoomType, User


def _csrf_token(client) -> str:
    response = client.get("/login")
    match = re.search(
        r'name="csrf_token"[^>]*value="([^"]+)"',
        response.get_data(as_text=True),
    )
    assert match is not None
    return match.group(1)


def _room_type_count(html: str, name: str) -> int:
    match = re.search(
        rf'<tr>\s*<td>\d+</td>\s*<td><strong>{re.escape(name)}</strong></td>'
        rf'\s*<td class="room-type-count">(\d+)</td>',
        html,
        re.DOTALL,
    )
    assert match is not None
    return int(match.group(1))


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


def _login(client):
    return client.post(
        "/login",
        data={
            "csrf_token": _csrf_token(client),
            "email": DEMO_EMAIL,
            "password": DEMO_PASSWORD,
        },
    )


def _create_room(client, room_number: str):
    form_html = client.get("/rooms/new").get_data(as_text=True)
    csrf_token = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', form_html)
    assert csrf_token is not None
    return client.post(
        "/rooms/new",
        data={
            "csrf_token": csrf_token.group(1),
            "room_number": room_number,
            "description": "Phòng kiểm thử lưu trữ",
            "price": "750000",
            "room_type": "1",
            "image": (BytesIO(b"\x89PNG\r\n\x1a\nroom image"), "room.png"),
        },
        content_type="multipart/form-data",
    )


def _add_test_room_type(app, name: str) -> int:
    with app.app_context():
        room_type = RoomType(
            name=name,
            price=0,
            quantity=0,
            capacity="",
            description="",
            status="active",
        )
        db.session.add(room_type)
        db.session.commit()
        return room_type.id


def _add_test_room(
    app,
    number: str,
    room_type: str,
    *,
    status: str = "Phòng trống",
    state: str = "empty",
    check_in: str | None = None,
    check_out: str | None = None,
) -> int:
    with app.app_context():
        room = Room(
            number=number,
            floor="Tầng kiểm thử",
            position=1,
            type=room_type,
            description=f"Mô tả {number}",
            price=825000,
            image=f"{number}.png",
            status=status,
            state=state,
            check_in=check_in,
            check_out=check_out,
            is_demo=False,
        )
        db.session.add(room)
        db.session.commit()
        return room.id


def _restart_app(app):
    return create_app(
        {
            "APP_ENV": "testing",
            "TESTING": True,
            "SECRET_KEY": "test-only-secret-key",
            "SQLALCHEMY_DATABASE_URI": app.config["SQLALCHEMY_DATABASE_URI"],
            "ROOM_UPLOAD_FOLDER": app.config["ROOM_UPLOAD_FOLDER"],
        }
    )


def test_room_types_requires_login(client):
    response = client.get("/room-types")

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/login")

    edit_response = client.get("/room-types/1/edit")
    assert edit_response.status_code == 302
    assert edit_response.headers["Location"].endswith("/login")


def test_room_management_requires_login(client):
    response = client.get("/rooms")

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/login")


def test_create_room_requires_login(client):
    response = client.get("/rooms/new")

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/login")


def test_edit_room_requires_login(client):
    response = client.get("/rooms/101/edit")

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/login")


def test_create_room_form_has_required_fields_and_room_type_dropdown(client):
    assert _login(client).status_code == 302

    html = client.get("/rooms/new").get_data(as_text=True)

    assert "Thêm phòng mới" in html
    assert "Thêm mới" not in html
    assert 'href="/rooms" aria-current="page"' in html
    assert 'enctype="multipart/form-data"' in html
    assert 'name="room_number"' in html and " required" in html
    assert 'name="description"' in html
    assert 'name="price"' in html
    assert '<select id="room-type" name="room_type" required' in html
    assert html.count('<option value="') >= 4
    assert '<option value="">Chọn thể loại phòng</option>' in html
    assert 'type="checkbox" name="room_type"' not in html
    assert 'class="form-field room-type-options"' in html
    assert 'roomTypeOptions' not in html
    assert "Phòng đơn" in html
    assert "Phòng đôi" in html
    assert "Phòng VIP" in html
    assert 'name="check_in" type="time"' not in html
    assert 'name="check_out" type="time"' not in html
    assert 'name="image" type="file"' in html


def test_room_list_opens_add_form_as_modal(client):
    assert _login(client).status_code == 302

    html = client.get("/rooms").get_data(as_text=True)

    assert html.count('class="room-image"') == 12
    assert 'images/room-single.jpg' in html
    assert 'images/room-double.jpg' in html
    assert 'images/room-vip.jpg' in html
    assert 'id="open-room-dialog"' in html
    assert 'class="page-heading"' not in html
    assert "Đăng nhập thành công" not in html
    assert re.search(
        r'<header class="panel-header">.*?id="open-room-dialog".*?</header>',
        html,
        re.DOTALL,
    )
    panel_header = html.split('<header class="panel-header">', 1)[1].split(
        "</header>", 1
    )[0]
    assert panel_header.index('class="room-legend"') < panel_header.index(
        'id="open-room-dialog"'
    )
    assert panel_header.count('id="open-room-dialog"') == 1
    assert 'class="panel-header__actions"' in panel_header
    assert '<dialog class="room-dialog" id="room-dialog"' in html
    assert 'id="room-dialog-title">Thêm phòng mới</h2>' in html
    assert 'href="/rooms/new"' in html


def test_room_list_is_flat_complete_unique_and_sorted(client, app):
    assert _login(client).status_code == 302
    _add_test_room(app, "015", "Phòng đơn")
    _add_test_room(app, "402", "Phòng VIP")

    with app.app_context():
        stored_rooms = db.session.execute(db.select(Room)).scalars().all()
        expected_numbers = sorted(room.number for room in stored_rooms)
        floors_before = {room.number: room.floor for room in stored_rooms}

    html = client.get("/rooms").get_data(as_text=True)
    rendered_numbers = re.findall(
        r'<strong class="room-number">([^<]+)</strong>', html
    )

    assert rendered_numbers == expected_numbers
    assert len(rendered_numbers) == len(set(rendered_numbers)) == 14
    assert f"{len(stored_rooms)} phòng" in html
    assert not any(floor in html for floor in ("Tầng 1", "Tầng 2", "Tầng 3", "Phòng mới"))
    assert html.count('class="action-button action-button--edit"') == 14
    assert html.count('class="room-card__delete"') == 14
    with app.app_context():
        floors_after = {
            room.number: room.floor
            for room in db.session.execute(db.select(Room)).scalars()
        }
    assert floors_after == floors_before


def test_modal_validation_keeps_room_list_visible_and_reopens_dialog(client):
    assert _login(client).status_code == 302
    html = client.get("/rooms").get_data(as_text=True)
    csrf_token = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', html)
    assert csrf_token is not None

    response = client.post(
        "/rooms/new",
        data={
            "csrf_token": csrf_token.group(1),
            "modal_form": "1",
            "room_number": "407",
            "description": "",
            "price": "0",
            "room_type": [],
        },
        content_type="multipart/form-data",
    )
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'data-open-on-load' in html
    assert 'id="room-list"' in html
    assert "Vui lòng nhập mô tả ngắn." in html
    assert "Vui lòng chọn hình ảnh phòng." in html
    assert "Vui lòng chọn đúng một thể loại phòng." in html


def test_room_types_page_shows_type_management_table(client):
    assert _login(client).status_code == 302

    response = client.get("/room-types")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Quản lý Thể loại phòng" not in html
    assert re.search(
        r'<header class="panel-header">.*?room-type-add.*?</header>',
        html,
        re.DOTALL,
    )
    assert "Danh sách thể loại phòng" in html
    assert "Tên thể loại phòng" in html
    assert "Phòng đơn" in html
    assert "Phòng đôi" in html
    assert "Phòng VIP" in html
    table_html = html.split('<table class="room-type-table">', 1)[1].split("</table>", 1)[0]
    assert table_html.count("<th scope=") == 4
    assert re.findall(r'<th scope="col">(.*?)</th>', table_html) == [
        "STT",
        "Tên thể loại phòng",
        "Số phòng",
        "Hành động",
    ]
    assert "Số phòng" in table_html
    assert "Đơn giá" not in table_html
    assert "Số lượng" not in table_html
    assert "Sức chứa" not in table_html
    assert "Trạng thái" not in table_html
    assert "Mô tả" not in table_html
    assert html.count('class="action-button action-button--edit room-type-edit-trigger"') == 3
    assert 'class="room-type-stats"' not in html
    assert 'data-stat=' not in html
    assert 'role="search"' not in html
    assert 'placeholder="Tìm kiếm tên thể loại phòng..."' not in html
    assert 'id="room-type-edit-dialog"' in html
    assert 'name="room_type"' not in html


def test_room_type_counts_use_live_normalized_data_without_stats_or_search(
    client, app
):
    assert _login(client).status_code == 302
    unused_type_id = _add_test_room_type(app, "Thể loại chưa sử dụng")
    _add_test_room(app, "COUNT-1", "  PHÒNG ĐƠN ")
    _add_test_room(app, "COUNT-2", "phòng đơn")
    _add_test_room(app, "COUNT-3", " Phòng VIP ")

    with app.app_context():
        stored_rooms = db.session.execute(db.select(Room)).scalars().all()
        expected_room_count = len(stored_rooms)
        single_room_count = sum(
            room.type.strip().casefold() == "phòng đơn" for room in stored_rooms
        )
        vip_room_count = sum(
            room.type.strip().casefold() == "phòng vip" for room in stored_rooms
        )

    html = client.get("/room-types").get_data(as_text=True)

    assert 'data-stat=' not in html
    assert 'role="search"' not in html
    assert _room_type_count(html, "Phòng đơn") == single_room_count
    assert _room_type_count(html, "Phòng VIP") == vip_room_count
    assert _room_type_count(html, "Thể loại chưa sử dụng") == 0
    assert _room_type_count(
        client.get("/room-types").get_data(as_text=True), "Phòng đơn"
    ) == single_room_count
    with app.app_context():
        assert db.session.get(RoomType, unused_type_id) is not None
        assert db.session.execute(db.select(db.func.count(Room.id))).scalar_one() == expected_room_count


def test_room_type_counts_update_when_rooms_are_added_and_deleted(client, app):
    assert _login(client).status_code == 302
    initial_html = client.get("/room-types").get_data(as_text=True)
    initial_single_count = _room_type_count(initial_html, "Phòng đơn")

    assert _create_room(client, "COUNT-CRUD").status_code == 302
    after_create = client.get("/room-types").get_data(as_text=True)
    assert _room_type_count(after_create, "Phòng đơn") == initial_single_count + 1

    room_list = client.get("/rooms").get_data(as_text=True)
    csrf_token = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', room_list)
    assert csrf_token is not None
    delete_response = client.post(
        "/rooms/COUNT-CRUD/delete", data={"csrf_token": csrf_token.group(1)}
    )
    assert delete_response.status_code == 302

    after_delete = client.get("/room-types").get_data(as_text=True)
    assert _room_type_count(after_delete, "Phòng đơn") == initial_single_count


def test_room_type_counts_remain_live_when_types_are_created_and_deleted(client, app):
    assert _login(client).status_code == 302
    create_form = client.get("/room-types/new").get_data(as_text=True)
    csrf_token = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', create_form)
    assert csrf_token is not None

    response = client.post(
        "/room-types/new",
        data={"csrf_token": csrf_token.group(1), "name": "Thể loại mới"},
    )
    assert response.status_code == 302
    with app.app_context():
        created_type = db.session.execute(
            db.select(RoomType).where(RoomType.name == "Thể loại mới")
        ).scalar_one()
        created_type_id = created_type.id

    after_create = client.get("/room-types").get_data(as_text=True)
    assert _room_type_count(after_create, "Thể loại mới") == 0
    csrf_token = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', after_create)
    assert csrf_token is not None

    response = client.post(
        f"/room-types/{created_type_id}/delete",
        data={"csrf_token": csrf_token.group(1)},
    )
    assert response.status_code == 302
    after_delete = client.get("/room-types").get_data(as_text=True)
    assert 'data-source-name="Thể loại mới"' not in after_delete


def test_initial_room_type_catalog_has_single_double_and_vip(app):
    with app.app_context():
        room_types = db.session.execute(
            db.select(RoomType.name).order_by(RoomType.id)
        ).scalars().all()

    assert room_types == ["Phòng đơn", "Phòng đôi", "Phòng VIP"]


def test_repeated_initialization_does_not_duplicate_demo_rooms(app):
    with app.app_context():
        initial_numbers = db.session.execute(
            db.select(Room.number).where(Room.is_demo.is_(True))
        ).scalars().all()
        initial_user_count = db.session.execute(
            db.select(db.func.count(User.id))
        ).scalar_one()
        initial_room_type_count = db.session.execute(
            db.select(db.func.count(RoomType.id))
        ).scalar_one()

    restarted_app = _restart_app(app)
    with restarted_app.app_context():
        restarted_numbers = db.session.execute(
            db.select(Room.number).where(Room.is_demo.is_(True))
        ).scalars().all()
        assert db.session.execute(
            db.select(db.func.count(User.id))
        ).scalar_one() == initial_user_count
        assert db.session.execute(
            db.select(db.func.count(RoomType.id))
        ).scalar_one() == initial_room_type_count

    assert len(initial_numbers) == 12
    assert set(restarted_numbers) == set(initial_numbers)


def test_startup_migrates_legacy_room_type_seed_without_dropping_custom_types(app):
    with app.app_context():
        db.session.get(RoomType, 1).name = "Phòng tiêu chuẩn"
        db.session.delete(db.session.get(RoomType, 2))
        db.session.add(
            RoomType(
                name="Phòng gia đình",
                price=950000,
                quantity=2,
                capacity="5 người",
                description="Loại phòng tùy chỉnh",
                status="active",
            )
        )
        db.session.commit()

    restarted_app = create_app(
        {
            "APP_ENV": "testing",
            "TESTING": True,
            "SECRET_KEY": "test-only-secret-key",
            "SQLALCHEMY_DATABASE_URI": app.config["SQLALCHEMY_DATABASE_URI"],
        }
    )
    with restarted_app.app_context():
        room_types = db.session.execute(
            db.select(RoomType.name).order_by(RoomType.name)
        ).scalars().all()

    assert set(room_types) == {
        "Phòng đôi",
        "Phòng đơn",
        "Phòng gia đình",
        "Phòng VIP",
    }


def test_room_type_management_exposes_edit_and_delete_actions(client):
    assert _login(client).status_code == 302

    html = client.get("/room-types").get_data(as_text=True)

    assert 'class="action-button action-button--primary room-type-add" href="/room-types/new"' in html
    assert html.count('class="action-button action-button--edit room-type-edit-trigger"') == 3
    assert html.count('class="action-button action-button--delete" type="submit"') == 3
    assert html.count('name="csrf_token"') == 5
    assert "window.confirm(this.dataset.confirm)" in html
    assert 'data-confirm="Bạn có chắc chắn muốn xóa thể loại phòng: Phòng đơn?"' in html
    assert 'data-confirm="Bạn có chắc chắn muốn xóa thể loại phòng: Phòng đôi?"' in html
    assert 'data-confirm="Bạn có chắc chắn muốn xóa thể loại phòng: Phòng VIP?"' in html


def test_create_room_type_form_is_available_to_logged_in_user(client):
    assert _login(client).status_code == 302

    response = client.get("/room-types/new")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'action="/room-types/new"' in html
    assert '<dialog class="room-dialog" id="room-type-dialog"' in html
    assert 'id="close-room-type-dialog"' in html
    assert 'data-open-on-load' in html
    assert 'name="csrf_token"' in html
    create_form = html.split('<form class="room-form"', 1)[1].split("</form>", 1)[0]
    assert create_form.count("<input") == 2
    assert 'name="name" type="text" maxlength="120"' in create_form
    assert 'name="price"' not in create_form
    assert 'name="quantity"' not in create_form
    assert 'name="capacity"' not in create_form
    assert 'name="status"' not in create_form
    assert 'name="description"' not in create_form
    assert "Thêm thể loại phòng" in html


def test_create_room_type_persists_and_updates_listing(client, app):
    assert _login(client).status_code == 302
    form_html = client.get("/room-types/new").get_data(as_text=True)
    csrf_token = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', form_html)
    assert csrf_token is not None

    response = client.post(
        "/room-types/new",
        data={
            "csrf_token": csrf_token.group(1),
            "name": "  Phòng gia đình  ",
        },
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/room-types")
    html = client.get("/room-types").get_data(as_text=True)
    assert "Thêm thể loại phòng thành công." in html
    assert "Phòng gia đình" in html
    with app.app_context():
        created = db.session.execute(
            db.select(RoomType).where(RoomType.name == "Phòng gia đình")
        ).scalar_one()
        assert created.price == 0
        assert created.quantity == 0
        assert created.capacity == ""
        assert created.description == ""
        assert created.status == "active"
    room_form = client.get("/rooms/new").get_data(as_text=True)
    edit_form = client.get("/rooms/101/edit").get_data(as_text=True)
    assert '<option value="4">Phòng gia đình</option>' in room_form
    assert '<option value="4">Phòng gia đình</option>' in edit_form


@pytest.mark.parametrize(
    ("name", "message"),
    [
        ("", "Vui lòng nhập tên thể loại phòng."),
        ("phòng vip", "Tên thể loại phòng đã tồn tại."),
        ("x" * 121, "Tên thể loại phòng không được vượt quá 120 ký tự."),
    ],
)
def test_invalid_room_type_creation_keeps_form_values(client, name, message):
    assert _login(client).status_code == 302
    form_html = client.get("/room-types/new").get_data(as_text=True)
    csrf_token = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', form_html)
    assert csrf_token is not None
    data = {
        "csrf_token": csrf_token.group(1),
        "name": name,
    }

    response = client.post("/room-types/new", data=data)
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert message in html
    assert name in html if name else True


def test_create_room_type_requires_login_and_csrf(client, app):
    response = client.post(
        "/room-types/new",
        data={"csrf_token": _csrf_token(client), "name": "Không được thêm"},
    )
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/login")

    with app.app_context():
        assert db.session.execute(
            db.select(RoomType).where(RoomType.name == "Không được thêm")
        ).scalar_one_or_none() is None

    assert _login(client).status_code == 302
    response = client.post("/room-types/new", data={"name": "Thiếu CSRF"})
    assert response.status_code == 400
    with app.app_context():
        assert db.session.execute(
            db.select(RoomType).where(RoomType.name == "Thiếu CSRF")
        ).scalar_one_or_none() is None


def test_canceling_room_type_delete_keeps_record(client, app):
    assert _login(client).status_code == 302

    listing = client.get("/room-types").get_data(as_text=True)
    assert 'data-confirm="Bạn có chắc chắn muốn xóa thể loại phòng: Phòng đơn?"' in listing

    with app.app_context():
        stored = db.session.get(RoomType, 1)
        assert stored is not None
        assert stored.name == "Phòng đơn"


def test_room_type_delete_removes_record_and_updates_listing(client, app):
    assert _login(client).status_code == 302
    room_type_id = _add_test_room_type(app, "Thể loại chưa sử dụng")
    listing = client.get("/room-types").get_data(as_text=True)
    csrf_token = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', listing)
    assert csrf_token is not None

    response = client.post(
        f"/room-types/{room_type_id}/delete",
        data={"csrf_token": csrf_token.group(1)},
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/room-types")
    html = client.get("/room-types").get_data(as_text=True)
    assert 'Đã xóa thể loại phòng "Thể loại chưa sử dụng" thành công.' in unescape(html)
    assert f'data-source-id="{room_type_id}"' not in html
    assert "Phòng đơn" in html
    assert "Phòng VIP" in html
    assert "Thể loại chưa sử dụng" not in client.get("/rooms/new").get_data(as_text=True)
    assert "Thể loại chưa sử dụng" not in client.get("/rooms/101/edit").get_data(as_text=True)
    with app.app_context():
        assert db.session.get(RoomType, room_type_id) is None
        assert db.session.get(RoomType, 1) is not None
        assert db.session.get(RoomType, 2) is not None


@pytest.mark.parametrize(
    ("status", "state", "check_in", "check_out"),
    [
        ("Phòng trống", "empty", None, None),
        ("Đang thuê", "occupied", "14:00", "12:00"),
    ],
)
def test_room_type_delete_refuses_direct_post_when_room_uses_type(
    client, app, status, state, check_in, check_out
):
    assert _login(client).status_code == 302
    room_id = _add_test_room(
        app,
        "USED-ROOM",
        "PHÒNG ĐƠN",
        status=status,
        state=state,
        check_in=check_in,
        check_out=check_out,
    )
    listing = client.get("/room-types").get_data(as_text=True)
    csrf_token = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', listing)
    assert csrf_token is not None

    response = client.post(
        "/room-types/1/delete",
        data={"csrf_token": csrf_token.group(1)},
    )

    assert response.status_code == 302
    html = client.get("/room-types").get_data(as_text=True)
    assert "Không thể xóa thể loại phòng này vì đang có phòng sử dụng." in html
    with app.app_context():
        stored_type = db.session.get(RoomType, 1)
        stored_room = db.session.get(Room, room_id)
        assert stored_type is not None
        assert stored_type.name == "Phòng đơn"
        assert stored_room is not None
        assert stored_room.type == "PHÒNG ĐƠN"
        assert stored_room.status == status
        assert stored_room.state == state
        assert stored_room.check_in == check_in
        assert stored_room.check_out == check_out


def test_room_type_delete_requires_login(client, app):
    response = client.post(
        "/room-types/1/delete",
        data={"csrf_token": _csrf_token(client)},
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/login")
    with app.app_context():
        assert db.session.get(RoomType, 1) is not None


def test_room_type_delete_reports_missing_record(client, app):
    assert _login(client).status_code == 302
    listing = client.get("/room-types").get_data(as_text=True)
    csrf_token = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', listing)
    assert csrf_token is not None
    response = client.post(
        "/room-types/999/delete",
        data={"csrf_token": csrf_token.group(1)},
    )

    assert response.status_code == 302
    html = client.get("/room-types").get_data(as_text=True)
    assert "Không tìm thấy loại phòng cần xóa." in html
    with app.app_context():
        assert db.session.get(RoomType, 1) is not None


def test_room_type_delete_rejects_get(client, app):
    assert _login(client).status_code == 302

    response = client.get("/room-types/1/delete")

    assert response.status_code == 405
    with app.app_context():
        assert db.session.get(RoomType, 1) is not None


def test_room_type_delete_requires_csrf_and_preserves_login(client, app):
    assert _login(client).status_code == 302

    response = client.post("/room-types/1/delete")

    assert response.status_code == 400
    assert "Phiên biểu mẫu không hợp lệ hoặc đã hết hạn." in response.get_data(as_text=True)
    assert client.get("/room-types").status_code == 200
    with app.app_context():
        assert db.session.get(RoomType, 1) is not None


def test_room_type_delete_rolls_back_on_database_error(client, app, monkeypatch):
    assert _login(client).status_code == 302
    room_type_id = _add_test_room_type(app, "Thể loại lỗi xóa")
    listing = client.get("/room-types").get_data(as_text=True)
    csrf_token = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', listing)
    assert csrf_token is not None

    def fail_commit(_session):
        raise SQLAlchemyError("simulated database failure")

    monkeypatch.setattr(Session, "commit", fail_commit)

    response = client.post(
        f"/room-types/{room_type_id}/delete",
        data={"csrf_token": csrf_token.group(1)},
    )

    assert response.status_code == 302
    html = client.get("/room-types").get_data(as_text=True)
    assert "Hệ thống tạm thời không thể xóa thể loại phòng" in html
    with app.app_context():
        assert db.session.get(RoomType, room_type_id) is not None


def test_deleting_unused_room_type_stays_deleted_after_restart(app, client):
    assert _login(client).status_code == 302
    room_type_id = _add_test_room_type(app, "Thể loại xóa trước khi khởi động lại")
    listing = client.get("/room-types").get_data(as_text=True)
    csrf_token = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', listing)
    assert csrf_token is not None

    response = client.post(
        f"/room-types/{room_type_id}/delete",
        data={"csrf_token": csrf_token.group(1)},
    )
    assert response.status_code == 302

    restarted_app = create_app(
        {
            "APP_ENV": "testing",
            "TESTING": True,
            "SECRET_KEY": "test-only-secret-key",
            "SQLALCHEMY_DATABASE_URI": app.config["SQLALCHEMY_DATABASE_URI"],
        }
    )
    with restarted_app.app_context():
        assert db.session.get(RoomType, room_type_id) is None
        assert db.session.get(RoomType, 1).name == "Phòng đơn"
        assert db.session.get(RoomType, 2).name == "Phòng đôi"
        assert db.session.get(RoomType, 3).name == "Phòng VIP"


def test_room_type_edit_form_contains_current_values(client):
    assert _login(client).status_code == 302

    listing = client.get("/room-types").get_data(as_text=True)
    assert 'data-source-id="1" data-source-name="Phòng đơn"' in listing
    assert listing.count('id="room-type-edit-dialog"') == 1
    assert 'id="room-type-update-form" method="post"' in listing
    assert 'roomTypeUpdateForm.action = `/room-types/${sourceId}/edit`' in listing
    assert 'id="room-type-target" name="target_room_type_id"' in listing
    assert "Không chuyển đổi" in listing
    assert 'new Option("Không chuyển đổi", "")' in listing
    assert 'id="room-type-action"' not in listing
    assert 'id="room-type-update-submit" type="submit" form="room-type-update-form">Cập nhật</button>' in listing
    assert listing.count('id="room-type-update-submit"') == 1
    assert 'Lưu tên mới</button>' not in listing
    assert 'id="room-type-transfer-form"' not in listing
    response = client.get("/room-types/1/edit")

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/room-types")


def test_room_type_update_persists_and_updates_listing(client, app):
    assert _login(client).status_code == 302
    _add_test_room(app, "SYNC-1", "Phòng đơn")
    _add_test_room(
        app,
        "SYNC-2",
        "  PHÒNG ĐƠN ",
        status="Đang thuê",
        state="occupied",
        check_in="14:00",
        check_out="12:00",
    )
    _add_test_room(app, "SYNC-3", "Phòng đôi")
    room_fields = (
        "number",
        "floor",
        "position",
        "type",
        "description",
        "price",
        "image",
        "status",
        "state",
        "check_in",
        "check_out",
        "is_demo",
    )
    with app.app_context():
        before_rooms = {
            room.number: {
                field: getattr(room, field)
                for field in room_fields
            }
            for room in db.session.execute(
                db.select(Room).where(Room.number.in_(("SYNC-1", "SYNC-2", "SYNC-3")))
            ).scalars()
        }

    form_html = client.get("/room-types").get_data(as_text=True)
    csrf_token = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', form_html)
    assert csrf_token is not None

    response = client.post(
        "/room-types/1/edit",
        data={
            "csrf_token": csrf_token.group(1),
            "name": "  Phòng đơn Plus  ",
        },
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/room-types")
    html = client.get("/room-types").get_data(as_text=True)
    assert "Cập nhật tên thể loại phòng thành công." in html
    assert "Phòng đơn Plus" in html

    restarted_app = create_app(
        {
            "APP_ENV": "testing",
            "TESTING": True,
            "SECRET_KEY": "test-only-secret-key",
            "SQLALCHEMY_DATABASE_URI": app.config["SQLALCHEMY_DATABASE_URI"],
        }
    )
    with restarted_app.app_context():
        persisted = db.session.get(RoomType, 1)
        assert persisted is not None
        assert persisted.name == "Phòng đơn Plus"
        assert persisted.price == 500000
        assert persisted.quantity == 0
        assert persisted.description == "Phòng cơ bản đầy đủ tiện nghi"
        assert persisted.status == "active"
        assert persisted.capacity == "2 người"
        updated_rooms = db.session.execute(
            db.select(Room).where(Room.number.in_(before_rooms))
        ).scalars()
        for room in updated_rooms:
            expected_type = (
                "Phòng đơn Plus"
                if before_rooms[room.number]["type"].strip().casefold() == "phòng đơn"
                else before_rooms[room.number]["type"]
            )
            expected = {**before_rooms[room.number], "type": expected_type}
            assert {field: getattr(room, field) for field in room_fields} == expected

        all_rooms = db.session.execute(db.select(Room)).scalars()
        assert all(room.type.strip().casefold() != "phòng đơn" for room in all_rooms)


def test_room_type_update_rolls_back_name_and_rooms_on_database_error(
    client, app, monkeypatch
):
    assert _login(client).status_code == 302
    room_id = _add_test_room(app, "ROLLBACK-1", "Phòng VIP")
    form_html = client.get("/room-types").get_data(as_text=True)
    csrf_token = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', form_html)
    assert csrf_token is not None

    def fail_commit(_session):
        raise SQLAlchemyError("simulated database failure")

    monkeypatch.setattr(Session, "commit", fail_commit)
    response = client.post(
        "/room-types/3/edit",
        data={
            "csrf_token": csrf_token.group(1),
            "name": "Phòng VIP cao cấp",
        },
    )

    assert response.status_code == 503
    assert "Hệ thống tạm thời không thể lưu thay đổi." in response.get_data(as_text=True)
    assert "data-open-on-load" in response.get_data(as_text=True)
    assert 'value="Phòng VIP cao cấp"' in response.get_data(as_text=True)
    with app.app_context():
        room_type = db.session.get(RoomType, 3)
        room = db.session.get(Room, room_id)
        assert room_type is not None
        assert room_type.name == "Phòng VIP"
        assert room is not None
        assert room.type == "Phòng VIP"


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ("   ", "Vui lòng nhập tên thể loại phòng."),
        ("Phòng ĐÔI", "Tên thể loại phòng đã tồn tại."),
        ("n" * 121, "Tên thể loại phòng không được vượt quá 120 ký tự."),
    ],
)
def test_invalid_room_type_update_keeps_input_and_does_not_save(
    client, app, value, message
):
    assert _login(client).status_code == 302
    form_html = client.get("/room-types").get_data(as_text=True)
    csrf_token = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', form_html)
    assert csrf_token is not None
    data = {
        "csrf_token": csrf_token.group(1),
        "name": value,
    }

    response = client.post("/room-types/1/edit", data=data)
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "data-open-on-load" in html
    assert message in html
    assert value in html if value.strip() else True
    with app.app_context():
        stored = db.session.get(RoomType, 1)
        assert stored is not None
        assert stored.name == "Phòng đơn"
        assert stored.price == 500000
        assert stored.quantity == 0
        assert stored.description == "Phòng cơ bản đầy đủ tiện nghi"
        assert stored.status == "active"


def test_unified_room_type_update_only_transfers_when_target_is_selected(
    client, app
):
    assert _login(client).status_code == 302
    source_id = _add_test_room_type(app, "Nguồn chỉ chuyển")
    target_id = _add_test_room_type(app, "Đích chỉ chuyển")
    room_id = _add_test_room(app, "UNIFIED-B", "Nguồn chỉ chuyển")
    listing = client.get("/room-types").get_data(as_text=True)
    csrf_token = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', listing)
    assert csrf_token is not None

    response = client.post(
        f"/room-types/{source_id}/edit",
        data={
            "csrf_token": csrf_token.group(1),
            "name": "Nguồn chỉ chuyển",
            "target_room_type_id": str(target_id),
        },
    )

    assert response.status_code == 302
    html = client.get("/room-types").get_data(as_text=True)
    assert _room_type_count(html, "Nguồn chỉ chuyển") == 0
    assert _room_type_count(html, "Đích chỉ chuyển") == 1
    with app.app_context():
        assert db.session.get(RoomType, source_id).name == "Nguồn chỉ chuyển"
        assert db.session.get(Room, room_id).type == "Đích chỉ chuyển"


def test_unified_room_type_update_can_rename_source_with_no_rooms(client, app):
    assert _login(client).status_code == 302
    source_id = _add_test_room_type(app, "Nguồn chưa có phòng")
    listing = client.get("/room-types").get_data(as_text=True)
    csrf_token = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', listing)
    assert csrf_token is not None

    response = client.post(
        f"/room-types/{source_id}/edit",
        data={
            "csrf_token": csrf_token.group(1),
            "name": "Nguồn rỗng đã đổi tên",
            "target_room_type_id": "",
        },
    )

    assert response.status_code == 302
    html = client.get("/room-types").get_data(as_text=True)
    assert _room_type_count(html, "Nguồn rỗng đã đổi tên") == 0
    with app.app_context():
        source = db.session.get(RoomType, source_id)
        assert source is not None
        assert source.name == "Nguồn rỗng đã đổi tên"


def test_unified_room_type_update_renames_and_transfers_original_rooms_atomically(
    client, app
):
    assert _login(client).status_code == 302
    source_id = _add_test_room_type(app, "Nguồn kết hợp")
    target_id = _add_test_room_type(app, "Đích kết hợp")
    source_room_ids = [
        _add_test_room(app, "UNIFIED-C1", "  NGUỒN KẾT HỢP "),
        _add_test_room(
            app,
            "UNIFIED-C2",
            "nguồn kết hợp",
            status="Đang thuê",
            state="occupied",
            check_in="15:00",
            check_out="11:00",
        ),
    ]
    target_room_id = _add_test_room(app, "UNIFIED-C3", "Đích kết hợp")
    unchanged_fields = (
        "id",
        "number",
        "floor",
        "position",
        "description",
        "price",
        "image",
        "status",
        "state",
        "check_in",
        "check_out",
        "is_demo",
    )
    with app.app_context():
        before = {
            room.id: {field: getattr(room, field) for field in unchanged_fields}
            for room in db.session.execute(
                db.select(Room).where(
                    Room.id.in_([*source_room_ids, target_room_id])
                )
            ).scalars()
        }

    listing = client.get("/room-types").get_data(as_text=True)
    csrf_token = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', listing)
    assert csrf_token is not None
    response = client.post(
        f"/room-types/{source_id}/edit",
        data={
            "csrf_token": csrf_token.group(1),
            "name": "Nguồn đã đổi tên",
            "target_room_type_id": str(target_id),
        },
    )
    with app.app_context():
        source_type = db.session.get(RoomType, source_id)
        assert source_type is not None
        assert source_type.name == "Nguồn đã đổi tên"
        assert db.session.get(RoomType, target_id).name == "Đích kết hợp"
        rooms = db.session.execute(
            db.select(Room).where(
                Room.id.in_([*source_room_ids, target_room_id])
            )
        ).scalars()
        for room in rooms:
            assert room.type == "Đích kết hợp"
            assert {
                field: getattr(room, field) for field in unchanged_fields
            } == before[room.id]


def test_unified_room_type_update_with_no_changes_does_not_commit(
    client, app, monkeypatch
):
    assert _login(client).status_code == 302
    source_id = _add_test_room_type(app, "Không đổi")
    listing = client.get("/room-types").get_data(as_text=True)
    csrf_token = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', listing)
    assert csrf_token is not None

    def reject_commit(_session):
        raise SQLAlchemyError("no-op must not commit")

    monkeypatch.setattr(Session, "commit", reject_commit)
    response = client.post(
        f"/room-types/{source_id}/edit",
        data={"csrf_token": csrf_token.group(1), "name": "Không đổi"},
    )

    assert response.status_code == 302
    assert "Không có thay đổi nào được thực hiện." in client.get(
        "/room-types"
    ).get_data(as_text=True)
    with app.app_context():
        assert db.session.get(RoomType, source_id).name == "Không đổi"


@pytest.mark.parametrize("target_value", ["same", "999999", "not-an-id"])
def test_unified_room_type_update_rejects_invalid_target_ids(
    client, app, target_value
):
    assert _login(client).status_code == 302
    source_id = _add_test_room_type(app, "Nguồn đích sai")
    _add_test_room_type(app, "Đích hợp lệ")
    room_id = _add_test_room(app, "UNIFIED-INVALID", "Nguồn đích sai")
    listing = client.get("/room-types").get_data(as_text=True)
    csrf_token = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', listing)
    assert csrf_token is not None
    if target_value == "same":
        target_value = str(source_id)

    response = client.post(
        f"/room-types/{source_id}/edit",
        data={
            "csrf_token": csrf_token.group(1),
            "name": "Tên người dùng nhập",
            "target_room_type_id": target_value,
        },
    )

    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "data-open-on-load" in html
    assert 'data-target-id="' + target_value + '"' in html
    assert 'value="Tên người dùng nhập"' in html
    assert "phải khác nhau" in html or "đích hợp lệ" in html
    with app.app_context():
        assert db.session.get(RoomType, source_id).name == "Nguồn đích sai"
        assert db.session.get(Room, room_id).type == "Nguồn đích sai"


def test_unified_room_type_update_rolls_back_rename_and_transfer_together(
    client, app, monkeypatch
):
    assert _login(client).status_code == 302
    source_id = _add_test_room_type(app, "Nguồn rollback kết hợp")
    target_id = _add_test_room_type(app, "Đích rollback kết hợp")
    room_id = _add_test_room(
        app, "UNIFIED-ROLLBACK", "Nguồn rollback kết hợp"
    )
    listing = client.get("/room-types").get_data(as_text=True)
    csrf_token = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', listing)
    assert csrf_token is not None

    def fail_commit(_session):
        raise SQLAlchemyError("simulated combined update failure")

    monkeypatch.setattr(Session, "commit", fail_commit)
    response = client.post(
        f"/room-types/{source_id}/edit",
        data={
            "csrf_token": csrf_token.group(1),
            "name": "Tên sau rollback",
            "target_room_type_id": str(target_id),
        },
    )

    assert response.status_code == 503
    assert "data-open-on-load" in response.get_data(as_text=True)
    assert 'value="Tên sau rollback"' in response.get_data(as_text=True)
    assert f'data-target-id="{target_id}"' in response.get_data(as_text=True)
    with app.app_context():
        assert db.session.get(RoomType, source_id).name == "Nguồn rollback kết hợp"
        assert db.session.get(RoomType, target_id).name == "Đích rollback kết hợp"
        assert db.session.get(Room, room_id).type == "Nguồn rollback kết hợp"


def test_unified_room_type_update_requires_login_and_csrf(client, app):
    csrf_token = _csrf_token(client)
    response = client.post(
        "/room-types/1/edit",
        data={"csrf_token": csrf_token, "name": "Không được đổi"},
    )
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/login")

    assert _login(client).status_code == 302
    response = client.post("/room-types/1/edit", data={"name": "Thiếu CSRF"})
    assert response.status_code == 400
    assert "data-open-on-load" in response.get_data(as_text=True)
    with app.app_context():
        assert db.session.get(RoomType, 1).name == "Phòng đơn"


def test_room_type_transfer_moves_rooms_and_preserves_other_room_fields(
    client, app
):
    assert _login(client).status_code == 302
    source_id = _add_test_room_type(app, "Nguồn tùy chỉnh")
    target_id = _add_test_room_type(app, "Đích tùy chỉnh")
    source_room_ids = [
        _add_test_room(app, "TRANSFER-1", "  NGUỒN TÙY CHỈNH "),
        _add_test_room(
            app,
            "TRANSFER-2",
            "nguồn tùy chỉnh",
            status="Đang thuê",
            state="occupied",
            check_in="14:00",
            check_out="12:00",
        ),
    ]
    destination_room_id = _add_test_room(app, "TRANSFER-3", "Đích tùy chỉnh")
    room_fields = (
        "id",
        "number",
        "floor",
        "position",
        "type",
        "description",
        "price",
        "image",
        "status",
        "state",
        "check_in",
        "check_out",
        "is_demo",
    )
    with app.app_context():
        before = {
            room.id: {field: getattr(room, field) for field in room_fields}
            for room in db.session.execute(
                db.select(Room).where(
                    Room.id.in_([*source_room_ids, destination_room_id])
                )
            ).scalars()
        }
        room_total_before = db.session.execute(
            db.select(db.func.count(Room.id))
        ).scalar_one()

    listing = client.get("/room-types").get_data(as_text=True)
    csrf_token = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', listing)
    assert csrf_token is not None
    assert "Đích tùy chỉnh" in listing

    response = client.post(
        f"/room-types/{source_id}/transfer",
        data={
            "csrf_token": csrf_token.group(1),
            "target_room_type_id": str(target_id),
        },
    )

    assert response.status_code == 302
    html = client.get("/room-types").get_data(as_text=True)
    assert 'Đã chuyển 2 phòng từ "Nguồn tùy chỉnh" sang "Đích tùy chỉnh" thành công.' in unescape(html)
    assert _room_type_count(html, "Nguồn tùy chỉnh") == 0
    assert _room_type_count(html, "Đích tùy chỉnh") == 3
    with app.app_context():
        assert db.session.get(RoomType, source_id).name == "Nguồn tùy chỉnh"
        assert db.session.get(RoomType, target_id).name == "Đích tùy chỉnh"
        after_rooms = db.session.execute(
            db.select(Room).where(
                Room.id.in_([*source_room_ids, destination_room_id])
            )
        ).scalars()
        for room in after_rooms:
            expected_type = (
                "Đích tùy chỉnh"
                if room.id in source_room_ids
                else before[room.id]["type"]
            )
            assert {field: getattr(room, field) for field in room_fields} == {
                **before[room.id],
                "type": expected_type,
            }
        assert db.session.execute(
            db.select(db.func.count(Room.id))
        ).scalar_one() == room_total_before
    management_html = client.get("/rooms").get_data(as_text=True)
    assert management_html.count('<p class="room-type">Đích tùy chỉnh</p>') == 3
    assert '<p class="room-type">Nguồn tùy chỉnh</p>' not in management_html


@pytest.mark.parametrize(
    ("target_value", "message"),
    [
        ("same", "Thể loại phòng nguồn và đích phải khác nhau."),
        ("999999", "Vui lòng chọn một thể loại phòng đích hợp lệ."),
        ("", "Vui lòng chọn một thể loại phòng đích hợp lệ."),
        ("not-an-id", "Vui lòng chọn một thể loại phòng đích hợp lệ."),
    ],
)
def test_room_type_transfer_rejects_invalid_targets_and_keeps_dialog_open(
    client, app, target_value, message
):
    assert _login(client).status_code == 302
    source_id = _add_test_room_type(app, "Nguồn kiểm tra")
    _add_test_room_type(app, "Đích kiểm tra")
    room_id = _add_test_room(
        app,
        "TRANSFER-INVALID",
        "Nguồn kiểm tra",
        status="Đang thuê",
        state="occupied",
        check_in="14:00",
        check_out="12:00",
    )
    listing = client.get("/room-types").get_data(as_text=True)
    csrf_token = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', listing)
    assert csrf_token is not None

    if target_value == "same":
        target_value = str(source_id)
    response = client.post(
        f"/room-types/{source_id}/transfer",
        data={
            "csrf_token": csrf_token.group(1),
            "target_room_type_id": target_value,
        },
    )
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert message in html
    assert "data-open-on-load" in html
    assert 'data-occupied-count="1"' in html
    with app.app_context():
        assert db.session.get(Room, room_id).type == "Nguồn kiểm tra"
        assert db.session.get(RoomType, source_id).name == "Nguồn kiểm tra"


def test_room_type_transfer_rejects_empty_source_and_missing_source(client, app):
    assert _login(client).status_code == 302
    source_id = _add_test_room_type(app, "Nguồn trống")
    target_id = _add_test_room_type(app, "Đích trống")
    listing = client.get("/room-types").get_data(as_text=True)
    csrf_token = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', listing)
    assert csrf_token is not None

    response = client.post(
        f"/room-types/{source_id}/transfer",
        data={
            "csrf_token": csrf_token.group(1),
            "target_room_type_id": str(target_id),
        },
    )
    assert response.status_code == 200
    assert "Không có phòng thuộc thể loại này để chuyển." in response.get_data(as_text=True)
    assert "data-open-on-load" in response.get_data(as_text=True)

    response = client.post(
        "/room-types/999999/transfer",
        data={
            "csrf_token": csrf_token.group(1),
            "target_room_type_id": str(target_id),
        },
    )
    assert response.status_code == 302
    assert "Không tìm thấy thể loại phòng nguồn." in client.get(
        "/room-types"
    ).get_data(as_text=True)
    with app.app_context():
        assert db.session.get(RoomType, source_id).name == "Nguồn trống"


def test_room_type_transfer_requires_login_and_csrf(client, app):
    csrf_token = _csrf_token(client)
    response = client.post(
        "/room-types/1/transfer",
        data={"csrf_token": csrf_token, "target_room_type_id": "2"},
    )
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/login")

    assert _login(client).status_code == 302
    response = client.post(
        "/room-types/1/transfer", data={"target_room_type_id": "2"}
    )
    assert response.status_code == 400
    assert "data-open-on-load" in response.get_data(as_text=True)
    assert "Phiên biểu mẫu không hợp lệ hoặc đã hết hạn." in response.get_data(
        as_text=True
    )
    assert client.get("/room-types").status_code == 200
    with app.app_context():
        assert db.session.get(RoomType, 1).name == "Phòng đơn"
        assert db.session.get(RoomType, 2).name == "Phòng đôi"


def test_room_type_transfer_rolls_back_all_rooms_on_database_error(
    client, app, monkeypatch
):
    assert _login(client).status_code == 302
    source_id = _add_test_room_type(app, "Nguồn rollback")
    target_id = _add_test_room_type(app, "Đích rollback")
    room_ids = [
        _add_test_room(app, "TRANSFER-ROLLBACK-1", "Nguồn rollback"),
        _add_test_room(app, "TRANSFER-ROLLBACK-2", "Nguồn rollback"),
    ]
    listing = client.get("/room-types").get_data(as_text=True)
    csrf_token = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', listing)
    assert csrf_token is not None

    def fail_commit(_session):
        raise SQLAlchemyError("simulated database failure")

    monkeypatch.setattr(Session, "commit", fail_commit)
    response = client.post(
        f"/room-types/{source_id}/transfer",
        data={
            "csrf_token": csrf_token.group(1),
            "target_room_type_id": str(target_id),
        },
    )

    assert response.status_code == 503
    assert "Hệ thống tạm thời không thể chuyển phòng." in response.get_data(as_text=True)
    assert "data-open-on-load" in response.get_data(as_text=True)
    with app.app_context():
        assert db.session.get(RoomType, source_id).name == "Nguồn rollback"
        assert db.session.get(RoomType, target_id).name == "Đích rollback"
        rooms = db.session.execute(
            db.select(Room).where(Room.id.in_(room_ids))
        ).scalars()
        assert [room.type for room in rooms] == ["Nguồn rollback", "Nguồn rollback"]


def test_room_cards_stay_on_room_management_page(client):
    assert _login(client).status_code == 302

    room_types_page = client.get("/room-types").get_data(as_text=True)
    room_management_page = client.get("/rooms").get_data(as_text=True)

    assert "Phòng 101" not in room_types_page
    assert 'aria-label="Phòng 101, Phòng trống"' in room_management_page
    assert 'aria-label="Phòng 102, Phòng trống"' in room_management_page
    assert 'href="/rooms" aria-current="page"' in room_management_page
    assert 'class="room-grid"' in room_management_page
    assert "Giờ vào" in room_management_page
    assert "Giờ ra" in room_management_page
    assert room_management_page.count("<dd>—</dd>") == 24
    assert "14:00" not in room_management_page
    assert "room-card--empty" in room_management_page
    assert "room-card--occupied" not in room_management_page
    assert "Tổng quan / Sơ đồ phòng" not in room_management_page
    assert 'href="/" aria-current="page"' not in room_management_page


def test_room_management_status_filters_show_live_counts_and_sorted_rooms(
    client, app
):
    assert _login(client).status_code == 302
    with app.app_context():
        for number in ("102", "202", "302"):
            room = db.session.execute(
                db.select(Room).where(Room.number == number)
            ).scalar_one()
            room.status = "Đang thuê"
            room.state = "occupied"
        db.session.commit()

    all_page = client.get("/rooms").get_data(as_text=True)
    empty_page = client.get("/rooms?status=empty").get_data(as_text=True)
    occupied_page = client.get("/rooms?status=occupied").get_data(as_text=True)

    extract_room_numbers = lambda html: re.findall(
        r'<strong class="room-number">([^<]+)</strong>', html
    )
    assert extract_room_numbers(all_page) == [
        "101", "102", "103", "104", "201", "202",
        "203", "204", "301", "302", "303", "304",
    ]
    assert extract_room_numbers(empty_page) == [
        "101", "103", "104", "201", "203", "204", "301", "303", "304",
    ]
    assert extract_room_numbers(occupied_page) == ["102", "202", "302"]
    assert re.search(r'href="/rooms"[^>]*aria-current="page"', all_page)
    assert re.search(
        r'href="/rooms\?status=empty"[^>]*aria-current="page"', empty_page
    )
    assert re.search(
        r'href="/rooms\?status=occupied"[^>]*aria-current="page"', occupied_page
    )
    assert 'id="room-results" data-filtered' in empty_page
    assert 'id="room-results" data-filtered' in occupied_page
    assert "Phòng trống <strong class=\"room-filter-link__count\">9</strong>" in all_page
    assert "Đang thuê <strong class=\"room-filter-link__count\">3</strong>" in all_page
    assert "Tất cả <strong class=\"room-filter-link__count\">12</strong>" in occupied_page


def test_room_management_status_filter_uses_existing_status_or_state_logic(
    client, app
):
    assert _login(client).status_code == 302
    with app.app_context():
        status_only_occupied = db.session.execute(
            db.select(Room).where(Room.number == "101")
        ).scalar_one()
        status_only_occupied.status = "Đang thuê"

        state_only_occupied = db.session.execute(
            db.select(Room).where(Room.number == "102")
        ).scalar_one()
        state_only_occupied.state = "occupied"
        db.session.commit()

    occupied_page = client.get("/rooms?status=occupied").get_data(as_text=True)
    empty_page = client.get("/rooms?status=empty").get_data(as_text=True)

    assert 'aria-label="Phòng 101, Đang thuê"' in occupied_page
    assert 'aria-label="Phòng 102, Phòng trống"' in occupied_page
    assert 'aria-label="Phòng 101, Đang thuê"' not in empty_page
    assert 'aria-label="Phòng 102, Phòng trống"' not in empty_page
    assert "Đang thuê <strong class=\"room-filter-link__count\">2</strong>" in occupied_page


def test_room_management_status_filter_shows_empty_result_and_all_link(
    client, app
):
    assert _login(client).status_code == 302
    with app.app_context():
        for room in db.session.execute(db.select(Room)).scalars():
            room.status = "Đang thuê"
            room.state = "occupied"
        db.session.commit()

    empty_page = client.get("/rooms?status=empty").get_data(as_text=True)

    assert "Không có phòng trống." in empty_page
    assert 'class="room-card ' not in empty_page
    assert re.search(r'href="/rooms"[^>]*>\s*Tất cả', empty_page)
    assert "Phòng trống <strong class=\"room-filter-link__count\">0</strong>" in empty_page


def test_room_management_shows_all_rooms_when_every_room_is_empty(client):
    assert _login(client).status_code == 302

    all_page = client.get("/rooms").get_data(as_text=True)
    empty_page = client.get("/rooms?status=empty").get_data(as_text=True)
    occupied_page = client.get("/rooms?status=occupied").get_data(as_text=True)

    room_number_pattern = r'<strong class="room-number">([^<]+)</strong>'
    expected_numbers = [
        "101", "102", "103", "104", "201", "202",
        "203", "204", "301", "302", "303", "304",
    ]
    assert re.findall(room_number_pattern, all_page) == expected_numbers
    assert re.findall(room_number_pattern, empty_page) == expected_numbers
    assert "Tất cả <strong class=\"room-filter-link__count\">12</strong>" in all_page
    assert "Phòng trống <strong class=\"room-filter-link__count\">12</strong>" in all_page
    assert "Đang thuê <strong class=\"room-filter-link__count\">0</strong>" in all_page
    assert "Không có phòng đang thuê." in occupied_page
    assert re.findall(room_number_pattern, occupied_page) == []


def test_room_cards_show_saved_times_and_dash_for_empty_times(client, app):
    assert _login(client).status_code == 302
    with app.app_context():
        room = db.session.execute(
            db.select(Room).where(Room.number == "101")
        ).scalar_one()
        room.check_in = "14:30"
        room.check_out = ""
        db.session.commit()

    room_management_page = client.get("/rooms").get_data(as_text=True)

    assert "<dd>14:30</dd>" in room_management_page
    assert "<dd>—</dd>" in room_management_page


def test_room_delete_removes_room_from_management_page(client, app):
    assert _login(client).status_code == 302

    room_management_page = client.get("/rooms").get_data(as_text=True)
    csrf_token = re.search(
        r'name="csrf_token"[^>]*value="([^"]+)"',
        room_management_page,
    )
    assert csrf_token is not None

    response = client.post(
        "/rooms/101/delete",
        data={"csrf_token": csrf_token.group(1)},
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/rooms")

    room_management_page = client.get("/rooms").get_data(as_text=True)
    assert 'aria-label="Phòng 101, Phòng trống"' not in room_management_page
    assert 'aria-label="Phòng 102, Phòng trống"' in room_management_page

    restarted_app = _restart_app(app)
    with restarted_app.app_context():
        assert db.session.execute(
            db.select(Room).where(Room.number == "101")
        ).scalar_one_or_none() is None
        assert db.session.execute(db.select(db.func.count(Room.id))).scalar_one() == 11


def test_room_delete_rejects_occupied_room(client, app):
    assert _login(client).status_code == 302
    room_management_page = client.get("/rooms").get_data(as_text=True)
    csrf_token = re.search(
        r'name="csrf_token"[^>]*value="([^"]+)"',
        room_management_page,
    )
    assert csrf_token is not None

    with app.app_context():
        room = db.session.execute(
            db.select(Room).where(Room.number == "102")
        ).scalar_one()
        room.status = "Đang thuê"
        room.state = "occupied"
        db.session.commit()

    response = client.post(
        "/rooms/102/delete",
        data={"csrf_token": csrf_token.group(1)},
    )

    assert response.status_code == 302
    room_management_page = client.get("/rooms").get_data(as_text=True)
    assert 'aria-label="Phòng 102, Đang thuê"' in room_management_page
    assert "Không thể xóa phòng 102 đang được thuê." in room_management_page


def test_room_list_has_update_link_and_edit_form_is_prefilled(client):
    assert _login(client).status_code == 302

    room_management_page = client.get("/rooms").get_data(as_text=True)
    assert 'href="/rooms/101/edit"' in room_management_page
    assert "Cập nhật" in room_management_page

    edit_page = client.get("/rooms/101/edit").get_data(as_text=True)
    assert "Cập nhật phòng" in edit_page
    assert 'action="/rooms/101/edit"' in edit_page
    assert 'name="room_number" type="text" value="101"' in edit_page
    assert '<option value="1" selected>Phòng đơn</option>' in edit_page
    assert 'name="image" type="file"' in edit_page
    assert 'name="image" type="file" required' not in edit_page

    empty_edit_page = client.get("/rooms/102/edit").get_data(as_text=True)
    assert 'name="check_in" type="time"' not in empty_edit_page
    assert 'name="check_out" type="time"' not in empty_edit_page
    assert '<select id="room-status" name="status"' in empty_edit_page


def test_edit_room_suggests_catalog_defaults_without_saving_them(client, app):
    assert _login(client).status_code == 302
    defaults = next(item for item in ROOM_TYPE_CATALOG if item["name"] == "Phòng đơn")

    edit_page = client.get("/rooms/101/edit").get_data(as_text=True)

    assert f'name="price" type="number" value="{defaults["price"]}"' in edit_page
    assert f'>{defaults["description"]}</textarea>' in edit_page
    with app.app_context():
        room = db.session.execute(
            db.select(Room).where(Room.number == "101")
        ).scalar_one()
        assert room.price == 0
        assert room.description == ""


def test_edit_room_keeps_saved_price_and_description_on_get(client, app):
    assert _login(client).status_code == 302
    description = "Mô tả riêng đã lưu cho phòng 304"
    with app.app_context():
        room = db.session.execute(
            db.select(Room).where(Room.number == "304")
        ).scalar_one()
        room.price = 9999
        room.description = description
        db.session.commit()

    edit_page = client.get("/rooms/304/edit").get_data(as_text=True)

    assert 'name="price" type="number" value="9999"' in edit_page
    assert f">{description}</textarea>" in edit_page
    with app.app_context():
        room = db.session.execute(
            db.select(Room).where(Room.number == "304")
        ).scalar_one()
        assert room.price == 9999
        assert room.description == description


@pytest.mark.parametrize(
    ("room_number", "room_type"),
    [
        ("101", "Phòng đơn"),
        ("102", "Phòng đôi"),
        ("104", "Phòng VIP"),
    ],
)
def test_room_cards_show_catalog_defaults_for_missing_values(
    client, room_number, room_type
):
    assert _login(client).status_code == 302
    defaults = next(item for item in ROOM_TYPE_CATALOG if item["name"] == room_type)

    card = _room_card_html(
        client.get("/rooms").get_data(as_text=True),
        room_number,
    )

    assert defaults["description"] in card
    assert f'{defaults["price"]:,} VNĐ / đêm' in card


def test_room_card_keeps_saved_price_and_description(client, app):
    assert _login(client).status_code == 302
    description = "Mô tả riêng đã lưu cho phòng 304"
    with app.app_context():
        room = db.session.execute(
            db.select(Room).where(Room.number == "304")
        ).scalar_one()
        room.price = 9999
        room.description = description
        db.session.commit()

    card = _room_card_html(
        client.get("/rooms").get_data(as_text=True),
        "304",
    )

    assert description in card
    assert "9,999 VNĐ / đêm" in card
    assert "Phòng cơ bản đầy đủ tiện nghi" not in card
    assert "500,000 VNĐ / đêm" not in card


def test_room_card_only_falls_back_for_missing_price(client, app):
    assert _login(client).status_code == 302
    description = "Mô tả riêng vẫn được giữ"
    with app.app_context():
        room = db.session.execute(
            db.select(Room).where(Room.number == "304")
        ).scalar_one()
        room.price = 0
        room.description = description
        db.session.commit()

    card = _room_card_html(
        client.get("/rooms").get_data(as_text=True),
        "304",
    )

    assert description in card
    assert "500,000 VNĐ / đêm" in card
    assert "Phòng cơ bản đầy đủ tiện nghi" not in card


def test_room_card_only_falls_back_for_missing_description(client, app):
    assert _login(client).status_code == 302
    with app.app_context():
        room = db.session.execute(
            db.select(Room).where(Room.number == "304")
        ).scalar_one()
        room.price = 987654
        room.description = ""
        db.session.commit()

    card = _room_card_html(
        client.get("/rooms").get_data(as_text=True),
        "304",
    )

    assert "Phòng cơ bản đầy đủ tiện nghi" in card
    assert "987,654 VNĐ / đêm" in card
    assert "500,000 VNĐ / đêm" not in card


def test_room_card_does_not_invent_defaults_for_unknown_room_type(client, app):
    assert _login(client).status_code == 302
    _add_test_room_type(app, "Phòng gia đình")
    room_id = _add_test_room(app, "FAMILY-1", "Phòng gia đình")
    with app.app_context():
        room = db.session.get(Room, room_id)
        room.price = 0
        room.description = ""
        db.session.commit()

    card = _room_card_html(
        client.get("/rooms").get_data(as_text=True),
        "FAMILY-1",
    )

    assert '<p class="room-description">—</p>' in card
    assert '<p class="room-price">—</p>' in card


def test_room_list_catalog_defaults_do_not_change_stored_room_data(client, app):
    assert _login(client).status_code == 302

    def stored_room_values():
        with app.app_context():
            return [
                (
                    room.id,
                    room.number,
                    room.floor,
                    room.position,
                    room.type,
                    room.description,
                    room.price,
                    room.image,
                    room.status,
                    room.state,
                    room.check_in,
                    room.check_out,
                    room.is_demo,
                )
                for room in db.session.execute(
                    db.select(Room).order_by(Room.id)
                ).scalars()
            ]

    before = stored_room_values()
    response = client.get("/rooms")
    after = stored_room_values()

    assert response.status_code == 200
    assert before == after
    assert any(room[5] == "" and room[6] == 0 for room in after)


def test_room_card_reflects_saved_edit_values(client):
    assert _login(client).status_code == 302
    edit_page = client.get("/rooms/304/edit").get_data(as_text=True)
    csrf_token = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', edit_page)
    assert csrf_token is not None

    response = client.post(
        "/rooms/304/edit",
        data={
            "csrf_token": csrf_token.group(1),
            "room_number": "304",
            "description": "Giá trị vừa lưu cho phòng 304",
            "price": "1234567",
            "room_type": "1",
            "status": "Phòng trống",
        },
    )

    assert response.status_code == 302
    card = _room_card_html(
        client.get("/rooms").get_data(as_text=True),
        "304",
    )
    assert "Giá trị vừa lưu cho phòng 304" in card
    assert "1,234,567 VNĐ / đêm" in card
    assert "Phòng cơ bản đầy đủ tiện nghi" not in card
    assert "500,000 VNĐ / đêm" not in card


def test_edit_room_can_mark_room_occupied(client):
    assert _login(client).status_code == 302
    form_html = client.get("/rooms/102/edit").get_data(as_text=True)
    csrf_token = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', form_html)
    assert csrf_token is not None

    response = client.post(
        "/rooms/102/edit",
        data={
            "csrf_token": csrf_token.group(1),
            "room_number": "102",
            "description": "Phòng đang thuê",
            "price": "650000",
            "room_type": "1",
            "status": "Đang thuê",
            "check_in": "16:30",
            "check_out": "10:30",
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 302
    html = client.get("/rooms").get_data(as_text=True)
    assert 'aria-label="Phòng 102, Đang thuê"' in html
    assert "<dd>16:30</dd>" in html
    assert "<dd>10:30</dd>" in html
    assert html.count("<dd>—</dd>") == 22


def test_existing_database_rented_rooms_keep_rented_status(client, app):
    assert _login(client).status_code == 302
    with app.app_context():
        room = db.session.execute(
            db.select(Room).where(Room.number == "102")
        ).scalar_one()
        room.status = "Đang thuê"
        room.state = "occupied"
        db.session.commit()

    room_management_page = client.get("/rooms").get_data(as_text=True)

    assert "room-card--occupied" in room_management_page
    assert 'aria-label="Phòng 102, Đang thuê"' in room_management_page
    assert room_management_page.count('aria-label="Phòng ') == 12
    assert room_management_page.count("<dd>—</dd>") == 24


def test_edit_room_validates_required_fields(client):
    assert _login(client).status_code == 302
    form_html = client.get("/rooms/101/edit").get_data(as_text=True)
    csrf_token = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', form_html)
    assert csrf_token is not None

    response = client.post(
        "/rooms/101/edit",
        data={
            "csrf_token": csrf_token.group(1),
            "room_number": "101",
            "description": "",
            "price": "0",
            "room_type": [],
            "image": (BytesIO(b"not an image"), "room.txt"),
        },
        content_type="multipart/form-data",
    )
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Vui lòng nhập mô tả ngắn." in html
    assert "Giá thuê phải là số nguyên lớn hơn 0." in html
    assert "Vui lòng chọn đúng một thể loại phòng." in html
    assert "Ảnh phải có định dạng JPG, PNG hoặc WEBP hợp lệ." in html
    assert 'name="price" type="number" value="0"' in html
    assert '<textarea id="room-description" name="description" rows="3" maxlength="200" required aria-describedby="room-description-error"></textarea>' in html


@pytest.mark.parametrize(
    ("path", "room_number", "selected_types"),
    [
        ("/rooms/new", "408", []),
        ("/rooms/new", "409", ["1", "2"]),
        ("/rooms/new", "410", ["999999"]),
        ("/rooms/101/edit", "101", []),
        ("/rooms/101/edit", "101", ["1", "2"]),
        ("/rooms/101/edit", "101", ["999999"]),
    ],
)
def test_room_forms_reject_invalid_room_type_values(
    client, app, path, room_number, selected_types
):
    assert _login(client).status_code == 302
    form_html = client.get(path).get_data(as_text=True)
    csrf_token = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', form_html)
    assert csrf_token is not None
    response = client.post(
        path,
        data={
            "csrf_token": csrf_token.group(1),
            "room_number": room_number,
            "description": "Phòng kiểm thử thể loại",
            "price": "700000",
            "room_type": selected_types,
            "status": "Phòng trống",
            "image": (BytesIO(b"\x89PNG\r\n\x1a\nvalid image"), "room.png"),
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    assert "Vui lòng chọn đúng một thể loại phòng." in response.get_data(as_text=True)
    with app.app_context():
        if path == "/rooms/new":
            assert db.session.execute(
                db.select(Room).where(Room.number == room_number)
            ).scalar_one_or_none() is None
        else:
            stored = db.session.execute(
                db.select(Room).where(Room.number == room_number)
            ).scalar_one()
            assert stored.type == "Phòng đơn"


def test_edit_room_updates_data_uploads_image_and_flashes_success(client, app):
    assert _login(client).status_code == 302
    form_html = client.get("/rooms/101/edit").get_data(as_text=True)
    csrf_token = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', form_html)
    assert csrf_token is not None

    response = client.post(
        "/rooms/101/edit",
        data={
            "csrf_token": csrf_token.group(1),
            "room_number": "101A",
            "description": "Phòng đã được cập nhật",
            "price": "900000",
            "room_type": "3",
            "image": (BytesIO(b"\x89PNG\r\n\x1a\nupdated image"), "updated.png"),
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/rooms")
    html = client.get("/rooms").get_data(as_text=True)
    assert "Đã cập nhật phòng 101A." in html
    assert 'aria-label="Phòng 101A, Phòng trống"' in html
    assert "Phòng VIP" in html
    assert "Phòng đã được cập nhật" in html
    assert "900,000 VNĐ / đêm" in html
    image_url = re.search(r'src="(/room-images/[^\"]+)" alt="Ảnh phòng 101A"', html)
    assert image_url is not None
    assert client.get(image_url.group(1)).data.startswith(b"\x89PNG\r\n\x1a\n")
    home_page = client.get("/").get_data(as_text=True)
    assert 'aria-label="Phòng 101A, Phòng trống"' in home_page
    assert 'class="room-card room-card--empty home-room-card"' in home_page
    restarted_app = _restart_app(app)
    with restarted_app.app_context():
        updated_room = db.session.execute(
            db.select(Room).where(Room.number == "101A")
        ).scalar_one()
        assert updated_room.floor == "Tầng 1"
        assert updated_room.description == "Phòng đã được cập nhật"
        assert updated_room.price == 900000
        assert updated_room.type == "Phòng VIP"
        assert updated_room.image == image_url.group(1).rsplit("/", 1)[-1]


def test_create_room_uploads_image_and_defaults_to_empty(client, app):
    assert _login(client).status_code == 302
    form_html = client.get("/rooms/new").get_data(as_text=True)
    csrf_token = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', form_html)
    assert csrf_token is not None

    response = client.post(
        "/rooms/new",
        data={
            "csrf_token": csrf_token.group(1),
            "room_number": "405",
            "description": "Phòng có ban công",
            "price": "750000",
            "room_type": "1",
            "image": (BytesIO(b"\x89PNG\r\n\x1a\nroom image"), "room.png"),
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 302
    html = client.get("/rooms").get_data(as_text=True)
    assert 'aria-label="Phòng 405, Phòng trống"' in html
    assert "Phòng đơn" in html
    assert "Phòng có ban công" in html
    assert "750,000 VNĐ / đêm" in html
    image_url = re.search(r'src="(/room-images/[^\"]+)" alt="Ảnh phòng 405"', html)
    assert image_url is not None
    uploaded_image = client.get(image_url.group(1))
    assert uploaded_image.status_code == 200
    assert uploaded_image.data.startswith(b"\x89PNG\r\n\x1a\n")
    home_page = client.get("/").get_data(as_text=True)
    assert home_page.count('class="room-card room-card--') == 13
    assert 'aria-label="Phòng 405, Phòng trống"' in home_page
    with app.app_context():
        created_room = db.session.execute(
            db.select(Room).where(Room.number == "405")
        ).scalar_one()
        assert created_room.floor == "Phòng mới"
        assert created_room.description == "Phòng có ban công"
        assert created_room.price == 750000
        assert created_room.type == "Phòng đơn"
        assert created_room.status == "Phòng trống"
        assert created_room.state == "empty"
        assert created_room.image == image_url.group(1).rsplit("/", 1)[-1]
    restarted_app = _restart_app(app)
    with restarted_app.app_context():
        assert db.session.execute(
            db.select(Room).where(Room.number == "405")
        ).scalar_one().description == "Phòng có ban công"


def test_room_data_survives_logout_and_login(client):
    assert _login(client).status_code == 302
    assert _create_room(client, "406").status_code == 302

    room_page = client.get("/rooms").get_data(as_text=True)
    logout_token = re.search(
        r'<form class="account-menu__form" method="post" action="/logout">.*?'
        r'name="csrf_token" value="([^"]+)"',
        room_page,
        re.DOTALL,
    )
    assert logout_token is not None
    assert client.post(
        "/logout", data={"csrf_token": logout_token.group(1)}
    ).status_code == 302

    with client.session_transaction() as stored_session:
        assert "user_id" not in stored_session
        assert "room_floors" not in stored_session

    assert _login(client).status_code == 302
    room_page = client.get("/rooms").get_data(as_text=True)
    assert 'aria-label="Phòng 406, Phòng trống"' in room_page


def test_room_data_is_shared_between_authenticated_sessions(client, app):
    assert _login(client).status_code == 302
    assert _create_room(client, "407").status_code == 302

    with app.app_context():
        second_user = User(email="second-user@example.test")
        second_user.set_password("TestPass1!")
        db.session.add(second_user)
        db.session.commit()

    second_client = app.test_client()
    login_response = second_client.post(
        "/login",
        data={
            "csrf_token": _csrf_token(second_client),
            "email": "second-user@example.test",
            "password": "TestPass1!",
        },
    )
    assert login_response.status_code == 302
    room_page = second_client.get("/rooms").get_data(as_text=True)
    assert 'aria-label="Phòng 407, Phòng trống"' in room_page


def test_room_creation_rolls_back_and_removes_uploaded_image(
    client, app, tmp_path, monkeypatch
):
    assert _login(client).status_code == 302
    upload_folder = tmp_path / "room-uploads"
    app.config["ROOM_UPLOAD_FOLDER"] = str(upload_folder)

    def fail_commit(_session):
        raise SQLAlchemyError("simulated room insert failure")

    monkeypatch.setattr(Session, "commit", fail_commit)
    response = _create_room(client, "408")

    assert response.status_code == 503
    assert "Không thể lưu phòng" in response.get_data(as_text=True)
    assert list(upload_folder.iterdir()) == []
    with app.app_context():
        assert db.session.execute(
            db.select(Room).where(Room.number == "408")
        ).scalar_one_or_none() is None


def test_room_numbers_are_unique_without_case_sensitivity(client, app):
    assert _login(client).status_code == 302
    assert _create_room(client, "Room-A").status_code == 302

    duplicate_response = _create_room(client, "room-a")

    assert duplicate_response.status_code == 200
    assert "Mã phòng đã tồn tại." in duplicate_response.get_data(as_text=True)
    with app.app_context():
        rooms = db.session.execute(
            db.select(Room).where(Room.number.ilike("room-a"))
        ).scalars().all()
    assert len(rooms) == 1


def test_legacy_room_session_is_imported_once_without_losing_edits(client, app):
    assert _login(client).status_code == 302
    legacy_floors = list(deepcopy(ROOM_FLOORS))
    legacy_floors[0]["rooms"] = [
        dict(room)
        for room in legacy_floors[0]["rooms"]
        if room["number"] != "103"
    ]
    legacy_floors[0]["rooms"][0]["description"] = "Dữ liệu cũ đã chỉnh sửa"
    legacy_floors[0]["rooms"][0]["price"] = 825000
    legacy_floors.append(
        {
            "name": "Phòng mới",
            "rooms": [
                {
                    "number": "LEG-1",
                    "type": "Phòng VIP",
                    "description": "Phòng được tạo trước khi nâng cấp",
                    "price": 1100000,
                    "image": None,
                    "status": "Phòng trống",
                    "state": "empty",
                    "check_in": None,
                    "check_out": None,
                }
            ],
        }
    )
    with client.session_transaction() as stored_session:
        stored_session["room_floors"] = legacy_floors

    room_page = client.get("/rooms").get_data(as_text=True)
    assert 'aria-label="Phòng 103, Phòng trống"' not in room_page
    assert 'aria-label="Phòng LEG-1, Phòng trống"' in room_page
    assert "Dữ liệu cũ đã chỉnh sửa" in room_page
    assert "825,000 VNĐ / đêm" in room_page
    with client.session_transaction() as stored_session:
        assert "room_floors" not in stored_session

    with app.app_context():
        assert db.session.execute(
            db.select(Room).where(Room.number == "103")
        ).scalar_one_or_none() is None
        assert db.session.execute(
            db.select(Room).where(Room.number == "LEG-1")
        ).scalar_one().description == "Phòng được tạo trước khi nâng cấp"

    with client.session_transaction() as stored_session:
        stored_session["room_floors"] = legacy_floors
    room_page = client.get("/rooms").get_data(as_text=True)
    assert 'aria-label="Phòng 103, Phòng trống"' not in room_page
    assert 'aria-label="Phòng LEG-1, Phòng trống"' in room_page


def test_create_room_validates_price_room_type_and_image(client):
    assert _login(client).status_code == 302
    form_html = client.get("/rooms/new").get_data(as_text=True)
    csrf_token = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', form_html)
    assert csrf_token is not None

    response = client.post(
        "/rooms/new",
        data={
            "csrf_token": csrf_token.group(1),
            "room_number": "406",
            "description": "Phòng thử nghiệm",
            "price": "0",
            "room_type": ["1", "2"],
            "image": (BytesIO(b"not an image"), "room.txt"),
        },
        content_type="multipart/form-data",
    )
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Giá thuê phải là số nguyên lớn hơn 0." in html
    assert "Vui lòng chọn đúng một thể loại phòng." in html
    assert "Ảnh phải có định dạng JPG, PNG hoặc WEBP hợp lệ." in html
    assert 'aria-label="Phòng 406, Phòng trống"' not in client.get("/rooms").get_data(as_text=True)


def test_home_renders_room_list_without_management_controls(client):
    assert _login(client).status_code == 302

    response = client.get("/")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Danh sách phòng" in html
    assert html.count('class="room-card room-card--') == 12
    assert "Cập nhật" not in html
    assert "Xóa phòng" not in html
