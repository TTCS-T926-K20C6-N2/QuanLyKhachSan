// Dữ liệu danh sách phòng khách sạn (Dữ liệu mẫu)
const rooms = [
    {
        id: 101,
        name: "Phòng Deluxe Hướng Biển",
        type: "Deluxe",
        price: 1200000,
        image: "https://images.unsplash.com/photo-1611892440504-42a792e24d32?w=500",
        description: "35m² - 1 Giường đôi - Wifi, Điều hòa, Ban công"
    },
    {
        id: 102,
        name: "Phòng Standard Tiêu Chuẩn",
        type: "Standard",
        price: 700000,
        image: "https://images.unsplash.com/photo-1590490360182-c33d57733427?w=500",
        description: "25m² - 2 Giường đơn - View thành phố"
    },
    {
        id: 103,
        name: "Phòng VIP Hoàng Gia",
        type: "VIP",
        price: 2500000,
        image: "https://images.unsplash.com/photo-1582719478250-c89cae4dc85b?w=500",
        description: "60m² - Ban công riêng - Bể bơi riêng"
    },
    {
        id: 104,
        name: "Phòng Deluxe Gia Đình",
        type: "Deluxe",
        price: 1800000,
        image: "https://images.unsplash.com/photo-1566665797739-1674de7a421a?w=500",
        description: "45m² - 2 Giường đôi - Phù hợp 4 người"
    }
];

// Hàm hiển thị danh sách phòng ra màn hình
function renderRooms(data) {
    const container = document.getElementById("roomContainer");
    container.innerHTML = ""; 

    if (data.length === 0) {
        container.innerHTML = "<p>Không tìm thấy phòng phù hợp với yêu cầu của bạn.</p>";
        return;
    }

    data.forEach(room => {
        const card = `
            <div class="room-card">
                <div>
                    <img src="${room.image}" alt="${room.name}">
                    <h3>${room.name}</h3>
                    <p class="room-desc">${room.description}</p>
                </div>
                <div>
                    <p class="room-price">${room.price.toLocaleString('vi-VN')} VNĐ / đêm</p>
                    <button class="btn-detail" onclick="viewDetail(${room.id})">Xem Chi Tiết</button>
                </div>
            </div>
        `;
        container.innerHTML += card;
    });
}

// Hàm lọc phòng theo loại phòng và khoảng giá
function filterRooms() {
    const maxPrice = parseFloat(document.getElementById("maxPrice").value);
    
    // Lấy danh sách loại phòng được tích chọn
    const selectedTypes = [];
    if (document.getElementById("deluxe").checked) selectedTypes.push("Deluxe");
    if (document.getElementById("standard").checked) selectedTypes.push("Standard");
    if (document.getElementById("vip").checked) selectedTypes.push("VIP");

    const filtered = rooms.filter(room => {
        const matchPrice = isNaN(maxPrice) || room.price <= maxPrice;
        const matchType = selectedTypes.length === 0 || selectedTypes.includes(room.type);
        return matchPrice && matchType;
    });

    renderRooms(filtered);
}

// Hàm xem chi tiết phòng
function viewDetail(roomId) {
    alert("Bạn chọn xem chi tiết phòng ID: " + roomId);
}

// Gọi hiển thị danh sách ngay khi tải trang
renderRooms(rooms);