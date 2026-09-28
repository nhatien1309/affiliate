---
description: Chủ dự án duyệt video đã dựng và cho phép lên lịch đăng
argument-hint: <slug> [facebook|tiktok|both] [giờ đăng, ví dụ "20:00 mai"]
---
Chủ dự án duyệt: $ARGUMENTS

1. Kiểm tra `output/<slug>/` có video của nền tảng được duyệt (mặc định `both`).
2. Lên lịch theo mục "Duyệt và đăng" trong CLAUDE.md. Giờ đăng: dùng giờ chủ dự án đưa, nếu không có thì lấy giờ tốt nhất từ Metricool.
3. TikTok khi `TIKTOK_HAS_CART=true`: không lên lịch, nhắc chủ dự án đăng trong app và gắn giỏ hàng, kèm caption để copy.
4. Cập nhật hàng đợi sang `da_len_lich` và báo lại giờ đăng.
