# Hệ thống Quản lý Khách sạn — Login

Login slice cho SCRUM-21 / PB-01, dùng Flask, SQLAlchemy, SQLite, Jinja và Flask Session.

## Thiết lập lần đầu trên máy mới

Cài Python 3.x, VS Code, VS Code Python extension và Python Debugger
extension. Mở PowerShell và chạy:

```powershell
git clone https://github.com/TTCS-T926-K20C6-N2/QuanLyKhachSan.git
cd QuanLyKhachSan

py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

`.env` là cấu hình riêng trên máy và không được commit lên Git.
`.env.example` là file mẫu an toàn được chia sẻ qua Git; không ghi thông tin
đăng nhập thật vào đó. Các tính năng thông thường vẫn chạy khi chưa cấu hình
Gmail. Chỉ gửi email Forgot Password thật mới cần cấu hình tài khoản gửi Gmail.

Ví dụ cấu hình an toàn trong `.env`:

```text
MAIL_SERVER=smtp.gmail.com
MAIL_PORT=587
MAIL_USE_TLS=true
MAIL_USERNAME=
MAIL_PASSWORD=
MAIL_FROM=
APP_BASE_URL=http://127.0.0.1:5000
```

`MAIL_USERNAME` là tài khoản Gmail mà project dùng để gửi email.
`MAIL_PASSWORD` là Google App Password của tài khoản gửi, không phải mật khẩu
Gmail thông thường. `MAIL_FROM` thường là cùng địa chỉ Gmail gửi đó.

**Bảo mật thông tin gửi mail:**

- Không commit `.env` hoặc Gmail App Password.
- Không ghi credential thật vào `.env.example`.
- Không gửi App Password qua GitHub.
- Nếu nhóm dùng chung một Gmail sender, chỉ chia sẻ App Password riêng tư với
  thành viên cần kiểm tra gửi email thật.
- Thành viên chỉ làm Rooms, UI hoặc phần khác không cần Gmail credentials.

Cấu hình Development tùy chọn khác có thể được chỉnh trong `.env`:

```text
APP_ENV=development
SEED_DEMO_USER=true
DEMO_USER_EMAIL=demo@example.test
DEMO_USER_PASSWORD=Demo1@Hotel2026
```

`.env` và SQLite runtime database đã được loại khỏi Git.

F5 tự tạo `instance/hotel.db`, schema và Demo User trong Development; không cần
sửa SQLite hoặc chạy lệnh seed riêng.

Sau lần setup đầu tiên, không cần cài lại package hoặc tạo lại `.env` mỗi lần.
Thông thường chỉ cần mở project (và activate `.venv` nếu dùng terminal mới),
rồi nhấn F5.

### Khởi động hằng ngày

1. Mở project root trong VS Code.
2. Chọn interpreter `.venv` bằng **Python: Select Interpreter**.
3. Nhấn **F5** với cấu hình **Python Debugger: Hotel Login**.
4. Flask chạy tại `http://127.0.0.1:5000`; browser tự mở `http://127.0.0.1:5000/login`.

Không cần chạy `python app.py`.

## Cho thuê phòng

1. Đăng nhập và mở **Danh sách phòng**.
2. Chọn **Cho thuê** trên thẻ của một phòng trống.
3. Chọn thời gian trả phòng; thời gian bắt đầu được lấy từ máy chủ.
4. Xem thời lượng và tổng tiền dự kiến rồi chọn **Lưu thuê phòng**.

Giá được tính theo tỷ lệ thời gian thực tế: `giá/đêm × số phút thuê / 1.440`,
làm tròn đến đồng. Khi lưu thành công, lượt thuê được ghi vào SQLite và phòng
chuyển sang trạng thái **Đang thuê**.

Khi cần đổi lịch, chọn **Tùy chọn cho thuê** trên phòng đang thuê. Giờ bắt đầu
được giữ nguyên; giờ trả mới phải sau thời điểm hiện tại và tổng tiền sẽ được
tính lại trước khi lưu.

## Demo account

- Email: `demo@example.test`
- Password: `Demo1@Hotel2026`
- Chỉ dùng cho Development/Demo; không phải production credential và không thay thế Register.

## Tests

```powershell
python -m pytest
```
