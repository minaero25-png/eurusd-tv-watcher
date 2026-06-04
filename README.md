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

## News enrichment (ทำไม TA ถึงพลิก) — optional

เพิ่มชั้นวิเคราะห์: เวลา TA พลิก → ดึงข่าว Financial Juice ล่าสุด → ให้ **Groq** ประเมินว่า
ข่าวไหนน่าจะเป็นตัวขับ + **รุนแรง**แค่ไหน + **น่าเชื่อถือ**แค่ไหน → แปะท้าย alert.

> **Best-effort เสมอ** — ถ้า secret ไม่ครบ / Telethon ล่ม / Groq ล่ม → alert TA ธรรมดายังส่งปกติ
> ไม่กิน Anthropic / Agent SDK credit (ใช้ Groq ล้วน — ถูกมาก รันบน cloud)

### ⚠️ ใช้ BURNER account เท่านั้น — ห้ามใช้บัญชี Telegram ส่วนตัว

`FJ_SESSION_STRING` = กุญแจล็อกอินเข้าบัญชี Telegram **เต็ม**. ถ้าใช้บัญชีส่วนตัวแล้วหลุด =
คนร้ายอ่านแชทส่วนตัว + แอบอ้างเป็นเราได้. **วิธีถูก:** สมัครบัญชี Telegram ใหม่ (เบอร์ใหม่/เสมือน)
ที่ว่างเปล่า → join channel สาธารณะ `financialjuicelive` → ใช้บัญชีนี้เท่านั้น. ถ้า session burner หลุด
แย่ที่สุด = อ่าน channel สาธารณะ + แอบอ้างบัญชีเปล่าที่ไม่มีใครรู้จัก = เสียหายเกือบศูนย์.

> เก็บ repo เป็น **private** เมื่อใช้ enrichment (secret มากขึ้น).

### ขั้นตอน (ครั้งเดียว)

1. **สร้าง burner account** — เบอร์ใหม่ → ติดตั้ง Telegram → join `financialjuicelive`
2. **ขอ API creds** — [my.telegram.org](https://my.telegram.org) (ล็อกอินด้วย burner) → API development tools → ได้ `api_id` + `api_hash`
3. **สร้าง session string** (รันในเครื่อง ครั้งเดียว):
   ```powershell
   cd C:\Users\ELLE\eurusd-trading\tv-signal-watcher
   pip install telethon groq
   python gen_session.py
   # ใส่ api_id / api_hash / เบอร์ burner → Telegram ส่ง code มา → ใส่ code
   # copy บรรทัด SESSION STRING ที่ปริ้นออกมา
   ```
4. **(มี Groq key อยู่แล้ว)** — `GROQ_API_KEY` ตัวเดียวกับที่ news_aggregator ใช้ (`automation/news_aggregator/.env`)
5. **ตั้ง GitHub Secrets เพิ่ม** (Settings → Secrets → Actions):

   | Name | Value |
   |---|---|
   | `TG_API_ID` | api_id จาก my.telegram.org |
   | `TG_API_HASH` | api_hash จาก my.telegram.org |
   | `FJ_SESSION_STRING` | บรรทัดที่ `gen_session.py` ปริ้น |
   | `GROQ_API_KEY` | key เดียวกับ news_aggregator |

6. กด **Run workflow** ทดสอบ — ครั้งที่ reco เปลี่ยน จะเห็นบล็อก 🤖 ต่อท้าย

### เปลี่ยนเบอร์ burner รายปี (number lifecycle)

burner ผูกกับ **ซิมเน็ตรายปี** → เบอร์เปลี่ยนตามตารางนี้:

| วันที่ | เกิดอะไร | ต้องทำ |
|---|---|---|
| **11 ก.ย. 2026** | ซิมปัจจุบันหมดอายุ + เริ่มซิมใหม่วันเดียวกัน (เบอร์เปลี่ยน) | Change Number → เบอร์ใหม่ |
| **11 ก.ย. 2027** | ซิมหมดอายุ (เบอร์เปลี่ยน) | Change Number → เบอร์ใหม่ |
| **11 ก.ย. 2028** | เปลี่ยนเป็นซิม**รายเดือน** เบอร์คงที่ถาวร | Change Number ครั้งสุดท้าย → จบ ไม่ต้องทำอีก |

> **session ไม่ผูกกับซิม** — watcher ใช้ `FJ_SESSION_STRING` ที่ gen ไว้ ไม่ต้องใช้เบอร์ในการรันแต่ละครั้ง.
> เบอร์จำเป็นแค่ตอน (ก) สร้างบัญชี+gen session ครั้งแรก (ข) เปลี่ยนเบอร์/กู้บัญชี.

**ขั้นตอน Change Number** (ทำตอนได้ซิมใหม่ ขณะยัง login บัญชี burner อยู่):

1. เอาซิมใหม่เสียบมือถือ (ต้องรับ SMS ได้)
2. Telegram (login burner อยู่) → Settings → Edit profile → แตะเบอร์ → **Change Number** → ใส่เบอร์ใหม่ → รับ code บนซิมใหม่
3. เสร็จ — บัญชี/session เดิมอยู่ครบ **ไม่ต้อง gen session ใหม่ ไม่ต้องแตะ GH secret**

**ถ้าพลาด — เบอร์เก่าหมดอายุไปก่อนเปลี่ยน + login หลุด:** ไม่เป็นไร burner คือของใช้แล้วทิ้ง → สร้างบัญชีใหม่ + `python gen_session.py` + อัปเดต GH secret `FJ_SESSION_STRING` ตัวเดียว (~10 นาที) watcher กลับมาทำงาน.

### ปรับแต่ง

- `FJ_LOOKBACK_MIN` (default 60) — ดึงข่าวกี่นาทีก่อนหน้า flip
- `GROQ_MODEL` (default `llama-3.3-70b-versatile`) — เปลี่ยน model ได้
- `FJ_CHANNEL` (default `financialjuicelive`) — เปลี่ยน channel ได้

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
