---
description: Làm trọn quy trình cho một sản phẩm, từ link đến video và caption
argument-hint: <link hoặc id trong hàng đợi>
---
Làm video cho: $ARGUMENTS

1. Nếu là link chưa có trong `queue.csv`, thêm vào hàng đợi trước. Nếu là id, lấy link từ hàng đợi.
2. Làm đúng "Quy trình cho một link" trong CLAUDE.md, gồm cả bước gọi subagent `kiem-duyet`.
3. Kết thúc bằng tóm tắt ngắn: tên sản phẩm, giá, độ dài từng video, câu móc đã chọn, đường dẫn `output/<slug>/`, và trạng thái mới trong hàng đợi. Nếu còn thiếu gì từ chủ dự án (ảnh, link affiliate), nói rõ trong một dòng.
