---
description: Chạy hằng ngày, xử lý các link mới trong hàng đợi
---
Chạy phiên hằng ngày:

1. `python -m agent doctor`. Nếu thiếu mục bắt buộc thì dừng và ghi lý do vào tóm tắt.
2. `python -m agent queue list --status moi`. Lấy tối đa `MAX_PER_DAY` link cũ nhất (đọc bằng `python -c "from agent.config import env; print(env('MAX_PER_DAY','2'))"`).
   Nếu không có link `moi` và Shopee Open API đã cấu hình: làm mục "Tìm deal" trong CLAUDE.md với `--top` bằng `MAX_PER_DAY`, rồi xử lý các link vừa thêm.
3. Với từng link, làm "Quy trình cho một link" trong CLAUDE.md. Một link lỗi không được làm dừng các link còn lại.
4. Nếu chế độ duyệt là `tu_dang_facebook`, lên lịch các Reels đã qua kiểm duyệt.
5. Ghi tóm tắt phiên vào `output/nhat-ky/<yyyy-mm-dd>.md`: mỗi link một dòng (sản phẩm, trạng thái, việc chủ dự án cần làm). In tóm tắt đó ra cuối cùng.
