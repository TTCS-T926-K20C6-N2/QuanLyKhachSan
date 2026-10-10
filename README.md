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

`requirements.txt` đã khai báo ReportLab để xuất PDF. Lệnh cài requirements ở
trên sẽ cài thư viện này; không cần cài package PDF riêng.

`.env` là cấu hình riêng trên máy và không được commit lên Git.
`.env.example` là file mẫu an toàn được chia sẻ qua Git; không ghi thông tin
đăng nhập thật vào đó. Các tính năng thông thường vẫn chạy khi chưa cấu hình
email. Chỉ gửi mã Forgot Password thật mới cần cấu hình Brevo ở backend.

Ví dụ cấu hình an toàn trong `.env`:

```text
EMAIL_PROVIDER=brevo
BREVO_API_KEY=
MAIL_FROM=
MAIL_FROM_NAME=Hotel Management
```

### Gửi mã đặt lại mật khẩu qua Brevo

Người dùng chỉ nhập email đã đăng ký, xác ngit restore .vscode/launch.jsonhận mã gồm 6 chữ số rồi đặt mật
khẩu mới. Mã có hiệu lực trong 5 phút. Người dùng thông thường không cần và
không tự cấu hình Brevo; credential chỉ do người vận hành backend cấu hình.

Để kiểm tra gửi email thật, người vận hành backend cần tạo/cấu hình tài khoản
Brevo, tạo API key và xác minh sender tại Brevo. Đặt API key vào
`BREVO_API_KEY` trong `.env` cục bộ và đặt `MAIL_FROM` thành địa chỉ sender đã
xác minh. `EMAIL_PROVIDER` mặc định là `brevo`; `MAIL_FROM_NAME` là tên hiển thị.
Người dùng thông thường không cần cấu hình credential email. Người nhận có thể
dùng bất kỳ nhà cung cấp email hợp lệ nào; việc provider chấp nhận yêu cầu không
đảm bảo email vào Inbox.

**Bảo mật thông tin gửi mail:**

- Không commit `.env` hoặc Brevo API key.
- Không ghi credential thật vào `.env.example`.
- Không gửi API key qua GitHub.
- Chỉ chia sẻ API key riêng tư với người cần vận hành/kiểm tra gửi email thật.
- Thành viên chỉ làm Rooms, UI hoặc phần khác không cần email credentials.

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
2. Chọn số lượng **Phòng trống** hoặc **Đang thuê** để lọc danh sách; chọn **Tất cả** để xem lại toàn bộ phòng.
3. Chọn **Cho thuê** trên thẻ của một phòng trống.
4. Chọn thời gian trả phòng; thời gian bắt đầu được lấy từ máy chủ.
5. Xem thời lượng và tổng tiền dự kiến rồi chọn **Lưu thuê phòng**.

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
