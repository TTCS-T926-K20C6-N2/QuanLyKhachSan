# Hệ thống Quản lý Khách sạn — Login

Login slice cho SCRUM-21 / PB-01, dùng Flask, SQLAlchemy, SQLite, Jinja và Flask Session.

## Prerequisites(Chuẩn bị trước)

- Python 3.x
- VS Code
- VS Code Python extension và Python Debugger extension

## First setup(Bước cài đặt đầu)

Trong PowerShell tại project root:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

F5 tự tạo `instance/hotel.db`, schema và Demo User trong Development;
không cần sửa SQLite hoặc chạy lệnh seed riêng.

Nếu cần tùy chỉnh hoặc tắt Demo seed, tạo `.env` từ file mẫu:

```powershell
Copy-Item .env.example .env
```

Các biến Development tùy chọn:

```text
APP_ENV=development
SEED_DEMO_USER=true
DEMO_USER_EMAIL=demo@example.test
DEMO_USER_PASSWORD=Demo1@Hotel2026
```

`.env` và SQLite runtime database đã được loại khỏi Git.

## Daily run

1. Mở project root trong VS Code.
2. Chọn interpreter `.venv` bằng **Python: Select Interpreter**.
3. Nhấn **F5** với cấu hình **Python Debugger: Hotel Login**.
4. Flask chạy tại `http://127.0.0.1:5000`; browser tự mở `http://127.0.0.1:5000/login`.

Không cần chạy `python app.py`.

## Demo account

- Email: `demo@example.test`
- Password: `Demo1@Hotel2026`
- Chỉ dùng cho Development/Demo; không phải production credential và không thay thế Register.

## Tests

```powershell
python -m pytest
```
