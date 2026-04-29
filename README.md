# TV Signal Watcher

Cloud-based watcher ที่ fetch TradingView Technical Ratings สำหรับ EURUSD M30 + H1 ทุก 30 นาที
ถ้า Summary recommendation เปลี่ยน → ส่ง Telegram alert ทันที.

รันบน **GitHub Actions** — PC ปิดได้ ไม่ต้องลุ้น.

## Setup (ครั้งเดียว)

### 1. สร้าง GitHub repo (private)

```bash
cd C:\Users\ELLE\eurusd-trading\tv-signal-watcher
git init -b main
git add .
git commit -m "init tv-signal-watcher"

# สร้าง private repo บน GitHub ก่อน เช่น https://github.com/USER/eurusd-tv-watcher
git remote add origin https://github.com/USER/eurusd-tv-watcher.git
git push -u origin main
```

หรือใช้ `gh` CLI:

```bash
gh repo create eurusd-tv-watcher --private --source=. --push
```

### 2. ตั้ง GitHub Secrets

ไปที่ repo → **Settings → Secrets and variables → Actions → New repository secret**

| Name | Value |
|---|---|
| `TELEGRAM_BOT_TOKEN` | token เดียวกับ Brain2 bot (จาก `start.ps1`) |
| `TELEGRAM_ALLOWED_CHAT_IDS` | chat_id ของป่าน (เลขเดียว หรือคั่นจุลภาคถ้ามีหลาย) |

> ใช้ bot เดิมได้เลย หรือสร้างใหม่ผ่าน @BotFather ถ้าอยากแยก

### 3. เปิด Actions

- ไปที่ tab **Actions** ของ repo → ถ้าถูก disabled → กด enable
- กด **Run workflow** ครั้งแรก manual เพื่อ test:
  - ครั้งแรก = no alert (saves baseline)
  - ครั้งที่ 2+ = ถ้า reco เปลี่ยน → Telegram มา

หลังจากนั้น cron จะรันเองทุก 30 นาที (`:02` และ `:32` UTC)

## Behavior

- ตรวจ EURUSD บน FX_IDC (TV default forex aggregate) — ตรงกับที่ `ta` script ใช้
- Track Summary RECOMMENDATION ของ M30 + H1
- Alert เมื่อ reco เปลี่ยน (เช่น `SELL` → `STRONG_SELL`, `BUY` → `NEUTRAL`)
- ข้ามเสาร์/อาทิตย์ (FX ปิด)
- State เก็บใน `state.json` (commit กลับ repo อัตโนมัติ)

## Customize

แก้ `watch.py`:

- `INTERVALS` — เพิ่ม/ลด timeframe (เช่นเอา H4 ด้วย)
- `format_alert()` — แก้ format ข้อความ
- `is_fx_market_open()` — ปรับ window

แก้ workflow `.github/workflows/watch.yml`:

- `cron` — `'2,17,32,47 * * * *'` ถ้าอยากเช็คทุก 15 นาที
- หมายเหตุ: GitHub Actions cron อาจ delay 5-15 นาที ตอน peak — ไม่แม่นนาที

## Test ในเครื่อง

```powershell
cd C:\Users\ELLE\eurusd-trading\tv-signal-watcher
pip install -r requirements.txt
$env:TELEGRAM_BOT_TOKEN = "..."
$env:TELEGRAM_ALLOWED_CHAT_IDS = "..."
python watch.py
```

## Cost

GitHub Actions free tier: **2,000 minutes/month** สำหรับ private repo.
Watcher แต่ละครั้ง ~30 วินาที × 48 รัน/วัน × 30 วัน = ~720 นาที/เดือน → ฟรีหมด

หรือทำ repo เป็น public → free Actions ไม่จำกัด (แต่ state.json จะ public — ไม่มี secret อยู่ในนั้น OK)
