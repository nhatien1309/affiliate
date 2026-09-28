# Agent tiếp thị liên kết (VS Code + Claude Code)

Agent nhận link sản phẩm Shopee / TikTok Shop, viết kịch bản, dựng video dọc 9:16 có giọng đọc AI và phụ đề, chuẩn bị caption, rồi lên lịch đăng Facebook Reels / TikTok qua Metricool khi bạn duyệt.

- **Claude Code** (trong VS Code) là bộ não: đọc hàng đợi, viết kịch bản, kiểm duyệt, điều phối.
- **Mã Python** trong `agent/` là đôi tay: lấy dữ liệu Shopee, tạo giọng đọc, dựng video bằng ffmpeg.
- **Metricool** (kết nối MCP) đăng bài và lấy số liệu.

Bạn vẫn tự làm 3 việc: dán link, duyệt video, và gắn giỏ hàng TikTok trong app khi đủ 1.000 follower.

---

## 1. Cài đặt (một lần, khoảng 30 phút)

### Windows

Mở **PowerShell** và chạy lần lượt:

```powershell
winget install Microsoft.VisualStudioCode
winget install Python.Python.3.12
winget install Gyan.FFmpeg
winget install OpenJS.NodeJS.LTS   # chỉ cần nếu dùng engine hyperframes (mục 5)
irm https://claude.ai/install.ps1 | iex
```

Đóng rồi mở lại PowerShell, kiểm tra: `python --version`, `ffmpeg -version`, `claude --version`.

### macOS

```bash
brew install python ffmpeg
brew install node   # chỉ cần nếu dùng engine hyperframes (mục 5)
brew install --cask visual-studio-code
curl -fsSL https://claude.ai/install.sh | bash
```

### Mở dự án

1. Giải nén thư mục `affiliate-agent` vào nơi cố định (ví dụ `D:\affiliate-agent`).
2. VS Code → **File → Open Folder** → chọn thư mục đó. Chấp nhận cài 2 tiện ích được gợi ý (**Claude Code** và **Python**).
3. Mở Terminal trong VS Code (**Ctrl + `**) và chạy:

```powershell
python -m venv .venv
.venv\Scripts\activate            # macOS: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env            # macOS: cp .env.example .env
python -m agent doctor
```

4. Mở `.env`, điền khóa API (xem mục 2). Mở `brand/brand.json`, đổi `handle` thành tên kênh của bạn.
5. Chạy thử dựng video mẫu (không cần khóa API):

```powershell
python -m agent render demo-binh-giu-nhiet --platform facebook --tts silent
```

Video nằm ở `output/demo-binh-giu-nhiet/facebook/video.mp4`. Bỏ `--tts silent` để nghe giọng đọc miễn phí (edge).

Thử bản motion graphics (cần Node.js, lần đầu mất vài phút để tải HyperFrames và Chrome):

```powershell
python -m agent render demo-binh-giu-nhiet --platform facebook --tts silent --engine hyperframes
```

6. Mở khung **Claude Code** trong VS Code, đăng nhập tài khoản Claude, gõ `/mcp` → chọn **metricool** → đăng nhập trên trình duyệt. Làm tương tự với **vidiq** nếu bạn có tài khoản vidIQ. Trước đó, trong Metricool, nối Fanpage và tài khoản TikTok của bạn.

## 2. Khóa API trong `.env`

| Mục | Bắt buộc? | Lấy ở đâu |
| --- | --- | --- |
| `TTS_PROVIDER` | Có | `edge` để thử miễn phí; chuyển `elevenlabs` hoặc `fpt` khi đăng thật |
| `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID` | Nếu dùng ElevenLabs | elevenlabs.io → Profile → API Keys; Voice ID trong Voice Library |
| `FPT_API_KEY` | Nếu dùng FPT.AI | console.fpt.ai → Text to Speech |
| `SHOPEE_APP_ID`, `SHOPEE_SECRET` | Không | affiliate.shopee.vn → Open API (cần được Shopee duyệt) |
| `VIDEO_ENGINE` | Có | `ffmpeg` (mặc định) hoặc `hyperframes` (mục 5) |
| `APPROVAL_MODE` | Có | Giữ `duyet_tung_video` trong tháng đầu |
| `TIKTOK_HAS_CART` | Có | Đổi `true` khi TikTok cho gắn giỏ hàng (mốc 1.000 follower) |

Chưa có Shopee Open API vẫn chạy được: tạo link affiliate trên affiliate.shopee.vn, rồi dán cả link sản phẩm lẫn link affiliate cho agent.

**Sao lưu `.env` lên GitHub** (chỉ khi repo để **Private**): sau mỗi lần sửa `.env`, chạy
`powershell -ExecutionPolicy Bypass -File scripts\sao_luu_env.ps1`. Script tự dừng nếu repo đang công khai. Ở máy mới: `copy env.backup .env`.

## 3. Dùng hằng ngày

### Cách dễ nhất: giao diện điều khiển

Nhấp đúp `scripts\mo_giao_dien.cmd` (hoặc chạy `python -m agent ui`). Trình duyệt mở `http://127.0.0.1:8765`, giữ cửa sổ đen mở trong lúc dùng.

| Khu vực | Làm được gì |
| --- | --- |
| Thêm sản phẩm | Dán link → **Thêm và làm video ngay** hoặc **Chỉ thêm vào hàng đợi** |
| Lệnh nhanh | Chạy phiên hằng ngày, báo cáo tuần, kiểm tra cài đặt, tìm deal Shopee |
| Hàng đợi | Lọc theo trạng thái; mỗi link có nút **Làm video**, **Bỏ qua**, **Đưa về "Mới"**, **Xem video** |
| Video đã dựng | Xem video Facebook/TikTok, sao chép caption, **Dựng lại** (chọn kiểu dựng, giọng đọc), **Duyệt và lên lịch**, mở thư mục |
| Theo dõi lệnh | Log từng lệnh theo thời gian thực (Claude đang đọc/ghi gì, lỗi, bị chặn quyền), nút **Dừng**; giờ chạy tự động tiếp theo và nhật ký các buổi sáng |

- Lệnh chạy lần lượt từng cái; bấm nhiều nút thì các lệnh xếp hàng chờ.
- Nút có Claude (làm video, duyệt, chạy hằng ngày, báo cáo, tìm deal) dùng hạn mức gói Claude như khi gõ lệnh. Dựng lại và kiểm tra cài đặt không dùng Claude.
- Giao diện chỉ mở được trên chính máy này. Log mỗi lệnh lưu thêm trong `logs/ui/`.

### Hoặc gõ lệnh trong khung Claude Code

| Lệnh | Làm gì |
| --- | --- |
| `/them-link <link> [ghi chú]` | Thêm sản phẩm vào hàng đợi |
| `/tim-deal [từ khóa] [số lượng]` | Tìm sản phẩm Shopee bán chạy, hoa hồng tốt, đã lọc nhóm cấm, rồi thêm vào hàng đợi (cần Shopee Open API) |
| `/lam-video <link hoặc id>` | Làm trọn một sản phẩm: dữ liệu → kịch bản → kiểm duyệt → video |
| `/chay-hang-ngay` | Xử lý các link mới trong hàng đợi (tối đa `MAX_PER_DAY`) |
| `/duyet <slug> [facebook\|tiktok\|both] [giờ]` | Duyệt video và cho lên lịch đăng |
| `/bao-cao-tuan` | Báo cáo 7 ngày và đề xuất tuần tới |

Với **TikTok Shop**: sau khi thêm link, đặt 3–5 ảnh chụp màn hình trang sản phẩm vào `work/<slug>/images/`. TikTok chặn đọc trang tự động nên agent cần ảnh để biết tên, giá, điểm nổi bật.

Hàng đợi nằm trong `queue.csv`, mở bằng Excel được.

## 4. Tự chạy mỗi sáng

Máy tính phải bật và đã đăng nhập vào giờ chạy. Mỗi lần chạy dùng hạn mức gói Claude của bạn.

**Windows – Task Scheduler**
1. Mở **Task Scheduler** → **Create Basic Task** → đặt tên "Affiliate agent".
2. Trigger: **Daily**, 08:15.
3. Action: **Start a program**
   - Program: `powershell.exe`
   - Arguments: `-ExecutionPolicy Bypass -File "D:\affiliate-agent\scripts\run_daily.ps1"`
4. Nhật ký mỗi ngày nằm trong `logs/`, tóm tắt trong `output/nhat-ky/`.

**macOS – cron**: `crontab -e`, thêm dòng
`15 8 * * * /đường/dẫn/affiliate-agent/scripts/run_daily.sh`

## 5. Hai kiểu dựng video

| | `ffmpeg` (mặc định) | `hyperframes` |
| --- | --- | --- |
| Hình | Ảnh sản phẩm + giá + phụ đề, zoom nhẹ | Motion graphics: câu móc bật ra, thẻ "điểm nổi bật", giá to nhấp nháy, thẻ "Theo dõi", phụ đề sáng theo từng chữ |
| Cần | ffmpeg | ffmpeg + Node.js (npx) |
| Thời gian dựng | vài giây | khoảng 1–2 phút mỗi video |

Đổi mặc định bằng `VIDEO_ENGINE=hyperframes` trong `.env`, hoặc chọn từng lần bằng `--engine`.
Kiểu cảnh được tự chọn; muốn chỉ định thì thêm `visuals` vào kịch bản (xem CLAUDE.md). Giao diện nằm trong
`agent/motion_templates/` (HTML + CSS), đổi màu thì sửa `brand/brand.json`.

Lần đầu dựng, HyperFrames tự tải Chrome để chụp khung hình. Nếu báo lỗi tải Chrome, chạy `npx hyperframes browser ensure`.
HyperFrames gửi số liệu sử dụng ẩn danh cho HeyGen; tắt bằng `npx hyperframes telemetry disable`.

## 6. Tùy chỉnh

- Màu giá, tên kênh, câu khai báo affiliate: `brand/brand.json`.
- Nhạc nền: đặt file vào `assets/music/` (xem README trong đó).
- Quy tắc viết kịch bản và quy trình: `CLAUDE.md`. Sửa file này là sửa cách agent làm việc.
- Tiêu chí kiểm duyệt: `.claude/agents/kiem-duyet.md`.
- Từ khóa tìm deal mặc định: `deal_keywords` trong `brand/brand.json`, ví dụ `["tai nghe bluetooth", "sạc dự phòng"]`.
- Nhãn nhỏ góc trên video: `video_tag` trong `brand/brand.json` (mặc định "Tiếp thị liên kết").

## 7. Giới hạn cần biết

- **Đã chạy thử**: dựng video, hàng đợi, đọc ID sản phẩm Shopee. **Chưa chạy thử với khóa thật**: ElevenLabs, FPT.AI, Shopee Open API, đăng qua Metricool. Lần đầu dùng mỗi dịch vụ, chạy `/lam-video` với 1 sản phẩm và xem kỹ kết quả.
- **Metricool**: agent sẽ đọc mô tả công cụ trước khi đăng. Nếu Metricool cần video ở một đường link công khai, agent dừng lại và nhờ bạn tải video lên Metricool bằng tay (khoảng 1 phút).
- **TikTok gắn giỏ hàng**: chỉ làm được trong app TikTok khi đăng. Agent chuẩn bị video và caption, bạn đăng.
- **Tìm deal** (`/tim-deal`) chỉ dùng Shopee Open API chính thức, đã chạy thử với dữ liệu giả lập, chưa chạy với khóa thật. Bộ lọc nhóm cấm dựa trên từ khóa trong tên sản phẩm nên agent vẫn đọc lại từng cái.
- **edge-tts** là dịch vụ không chính thức, có thể ngừng bất cứ lúc nào. Dùng để thử; khi đăng thật nên chuyển sang ElevenLabs hoặc FPT.AI.
- Font Be Vietnam Pro dùng giấy phép SIL OFL (`assets/fonts/OFL.txt`).
- Engine `hyperframes` chuyển thể từ [auto-video-gen](https://github.com/Cuongyd196/auto-video-gen) (MIT); ý tưởng chấm điểm deal lấy từ [auto-aff](https://github.com/aphuong2k/auto-aff). Chi tiết: `agent/motion_templates/NOTICE.md`.
- Kiểm tra mã: `python -m unittest discover tests`.

## Cấu trúc thư mục

```
affiliate-agent/
├── CLAUDE.md               # sổ tay vận hành của agent
├── .claude/commands/       # các lệnh /them-link, /lam-video, ...
├── .claude/agents/         # subagent kiểm duyệt
├── .mcp.json               # kết nối Metricool, vidIQ
├── agent/                  # mã Python: hàng đợi, Shopee, tìm deal, giọng đọc, dựng video
│   ├── motion_templates/   # giao diện video motion graphics (engine hyperframes)
│   ├── ui.py               # giao diện điều khiển (python -m agent ui)
│   └── ui_static/          # HTML, CSS, JS của giao diện điều khiển
├── brand/brand.json        # nhận diện kênh
├── assets/fonts, music     # font và nhạc nền
├── scripts/run_daily.*     # chạy tự động mỗi sáng
├── scripts/mo_giao_dien.cmd # nhấp đúp để mở giao diện điều khiển
├── work/<slug>/            # dữ liệu, ảnh, kịch bản từng sản phẩm
├── output/<slug>/          # video, ảnh bìa, caption, phụ đề
└── tests/                  # kiểm tra tự động
```
