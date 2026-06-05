"""
TV Signal Watcher — fetch TradingView Technical Ratings (EURUSD M30 + H1),
compare with last state, send Telegram alert if recommendation changed.

Designed to run on GitHub Actions (cron) so PC can be off.
State persists by committing state.json back to the repo.
"""
import json
import os
import sys
import urllib.request
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

from tradingview_ta import TA_Handler, Interval

STATE_FILE = Path(__file__).parent / "state.json"

SYMBOL = os.environ.get("TV_SYMBOL", "EURUSD")
EXCHANGE = os.environ.get("TV_EXCHANGE", "FX")
SCREENER = os.environ.get("TV_SCREENER", "forex")

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_IDS = [
    x.strip() for x in os.environ.get("TELEGRAM_ALLOWED_CHAT_IDS", "").split(",") if x.strip()
]

INTERVALS = {
    "M30": Interval.INTERVAL_30_MINUTES,
    "H1": Interval.INTERVAL_1_HOUR,
}

# ── News enrichment config (Financial Juice via Telethon + Groq severity) ──
# All best-effort: if any of these are unset/fail, the plain TA alert still sends.
# Use a BURNER Telegram account session (NOT a personal account) — see README "News enrichment".
# .strip() guards against a trailing newline/CR pasted into a GitHub secret —
# urllib rejects header values with control chars ("Invalid header value").
TG_API_ID = os.environ.get("TG_API_ID", "").strip()
TG_API_HASH = os.environ.get("TG_API_HASH", "").strip()
FJ_SESSION_STRING = os.environ.get("FJ_SESSION_STRING", "").strip()
FJ_CHANNEL = os.environ.get("FJ_CHANNEL", "financialjuice").strip()  # real username (fetch_fj uses this)
FJ_LOOKBACK_MIN = int(os.environ.get("FJ_LOOKBACK_MIN", "60"))
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "").strip()
GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
GROQ_TIMEOUT = 30

# Claude (Anthropic API) — primary enrichment reasoner when ANTHROPIC_API_KEY is set;
# Groq stays as the automatic fallback. ANTHROPIC_MODEL must be the current Sonnet id.
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "").strip() or "claude-sonnet-4-6"

# severity: HIGH = big/dangerous move → red ; credibility: HIGH = trustworthy → green
SEV_EMOJI = {"HIGH": "🔴 สูง", "MEDIUM": "🟡 ปานกลาง", "LOW": "🟢 ต่ำ"}
CRED_EMOJI = {"HIGH": "🟢 สูง", "MEDIUM": "🟡 ปานกลาง", "LOW": "🔴 ต่ำ"}

RECO_EMOJI = {
    "STRONG_BUY": "🟢🟢",
    "BUY": "🟢",
    "NEUTRAL": "⚪",
    "SELL": "🔴",
    "STRONG_SELL": "🔴🔴",
}


def is_fx_market_open(now_utc: datetime) -> bool:
    """FX market: Sun 22:00 UTC → Fri 22:00 UTC."""
    weekday = now_utc.weekday()  # Mon=0 ... Sun=6
    hour = now_utc.hour
    if weekday == 5:  # Saturday
        return False
    if weekday == 6 and hour < 22:  # Sunday before 22:00
        return False
    if weekday == 4 and hour >= 22:  # Friday after 22:00
        return False
    return True


def fetch_signal(interval) -> dict:
    handler = TA_Handler(symbol=SYMBOL, screener=SCREENER, exchange=EXCHANGE, interval=interval)
    a = handler.get_analysis()
    summary = a.summary or {}
    osc = a.oscillators or {}
    ma = a.moving_averages or {}
    return {
        "summary_reco": summary.get("RECOMMENDATION", "NEUTRAL"),
        "summary_buy": summary.get("BUY", 0),
        "summary_sell": summary.get("SELL", 0),
        "summary_neutral": summary.get("NEUTRAL", 0),
        "osc_reco": osc.get("RECOMMENDATION", "NEUTRAL"),
        "ma_reco": ma.get("RECOMMENDATION", "NEUTRAL"),
        "close": (a.indicators or {}).get("close"),
    }


def load_state() -> dict:
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def send_telegram(text: str) -> None:
    if not BOT_TOKEN or not CHAT_IDS:
        print("⚠️ TELEGRAM_BOT_TOKEN or TELEGRAM_ALLOWED_CHAT_IDS not set — skip send")
        return
    for chat_id in CHAT_IDS:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        data = urllib.parse.urlencode({
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": "true",
        }).encode()
        req = urllib.request.Request(url, data=data, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                resp.read()
            print(f"✅ Telegram sent → chat_id={chat_id}")
        except Exception as e:
            print(f"❌ Telegram failed chat_id={chat_id}: {e}")


def _html_escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def fetch_recent_fj(minutes: int) -> list:
    """Pull Financial Juice channel messages from the last `minutes` via a Telethon
    StringSession (burner account). Returns ['HH:MM | text', ...] in chronological order.
    Best-effort: returns [] on any missing config / failure — never raises."""
    if not (TG_API_ID and TG_API_HASH and FJ_SESSION_STRING):
        print("ℹ️ FJ enrichment skipped — TG_API_ID/TG_API_HASH/FJ_SESSION_STRING not all set")
        return []
    try:
        from telethon.sync import TelegramClient
        from telethon.sessions import StringSession
    except ImportError:
        print("⚠️ telethon not installed — skip FJ enrichment")
        return []

    from datetime import timedelta
    since = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    out = []
    client = TelegramClient(StringSession(FJ_SESSION_STRING), int(TG_API_ID), TG_API_HASH)
    try:
        # connect() + auth check instead of start(): start() would fall back to an
        # interactive input() prompt if the session were invalid, hanging the CI runner.
        client.connect()
        if not client.is_user_authorized():
            print("⚠️ FJ session not authorized (expired/invalid) — skip enrichment")
            return []
        entity = client.get_entity(FJ_CHANNEL)
        for msg in client.iter_messages(entity, offset_date=None, reverse=False):
            if msg.date < since:
                break
            if not msg.message:
                continue
            ict = (msg.date + timedelta(hours=7)).strftime("%H:%M")
            text = " ".join(msg.message.split())
            out.append(f"{ict} | {text}")
    except Exception as e:
        print(f"⚠️ FJ fetch failed: {type(e).__name__}: {e}")
        return []
    finally:
        try:
            client.disconnect()
        except Exception:
            pass
    out.reverse()  # API returns newest-first → flip to chronological
    print(f"  FJ: pulled {len(out)} items in last {minutes}m")
    return out


def _groq_chat(prompt: str) -> str:
    """POST to Groq's OpenAI-compatible chat API via urllib + 3 retries.
    The groq SDK (httpx stack) hit APIConnectionError on the CI runner; urllib
    works here — same transport send_telegram() uses successfully.
    Returns the message content string, or '' on failure."""
    body = json.dumps({
        "model": GROQ_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "max_tokens": 700,
        "response_format": {"type": "json_object"},
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.groq.com/openai/v1/chat/completions",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json",
            # Cloudflare in front of api.groq.com returns 403/1010 for the default
            # "Python-urllib" UA — present a normal browser UA to pass.
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
        },
    )
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=GROQ_TIMEOUT) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"]
        except Exception as e:
            detail = ""
            if hasattr(e, "read"):
                try:
                    detail = " | " + e.read().decode("utf-8", "replace")[:200]
                except Exception:
                    pass
            print(f"⚠️ Groq attempt {attempt + 1}/3 failed: {type(e).__name__}: {e}{detail}")
    return ""


def _claude_chat(prompt: str) -> str:
    """POST to the Anthropic Messages API via urllib + 3 retries. Returns reply text or ''."""
    body = json.dumps({
        "model": ANTHROPIC_MODEL,
        "max_tokens": 700,
        "messages": [{"role": "user", "content": prompt}],
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=body, method="POST",
        headers={
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
    )
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=GROQ_TIMEOUT) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            return "".join(
                b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"
            )
        except Exception as e:
            detail = ""
            if hasattr(e, "read"):
                try:
                    detail = " | " + e.read().decode("utf-8", "replace")[:200]
                except Exception:
                    pass
            print(f"⚠️ Claude attempt {attempt + 1}/3 failed: {type(e).__name__}: {e}{detail}")
    return ""


def _extract_json(s: str):
    """Parse the first {...} object out of a model reply (tolerates ```json fences)."""
    i, j = s.find("{"), s.rfind("}")
    if i == -1 or j <= i:
        return None
    try:
        return json.loads(s[i:j + 1])
    except Exception:
        return None


def analyze_flip(changes: list, fj_items: list) -> str:
    """Ask the LLM (Claude if ANTHROPIC_API_KEY set, else Groq; Groq is also the fallback
    if Claude fails) which recent FJ headline most likely drove the TA flip, and rate
    severity + credibility. Returns a Thai HTML block for Telegram, or '' on any failure."""
    if not fj_items or not (ANTHROPIC_API_KEY or GROQ_API_KEY):
        return ""

    flip_desc = ", ".join(f"{c['tf']} {c['old']}→{c['new']}" for c in changes)
    headlines = "\n".join(fj_items[-25:])  # cap to stay cheap
    prompt = (
        "You are a forex macro analyst watching EUR/USD. The TradingView technical rating "
        f"just flipped: {flip_desc}. This flip means price moved. Below are Financial Juice "
        "headlines from the minutes before the flip (ICT time | text):\n\n"
        f"{headlines}\n\n"
        "Pick the headline most likely driving THIS EUR/USD move.\n"
        "Treat as a DRIVER (pick the strongest one) if a headline involves any of: US or "
        "Euro-area economic data (CPI/NFP/PMI/GDP/retail/jobless), Fed or ECB speakers/policy, "
        "the US dollar / euro / DXY / US-Treasury yields, oil prices, or a geopolitics/risk "
        "event that moves the dollar, euro, or oil (e.g. ceasefire, war escalation, energy "
        "supply shock, sanctions).\n"
        "NEVER pick (treat as noise): China domestic capital flows, single-stock or "
        "single-sector news, equity-index moves, crypto (unless an explicit broad risk-off), "
        "Asia/EM-only stories with no clear dollar/euro link.\n"
        "Set driver_th=null ONLY if NO headline fits the DRIVER categories above — then the "
        "flip is just price action / technical.\n"
        "If you do pick a driver, rate:\n"
        "- severity: how market-moving — HIGH (>30 pips potential) / MEDIUM (10-30) / LOW (minor)\n"
        "- credibility: confirmed vs speculative — HIGH (official action/confirmed data) / "
        "MEDIUM (one-sided statement, unconfirmed) / LOW (rumor/speculation)\n\n"
        "Write driver_th and reasoning_th in THAI. reasoning_th MUST be at most 2 short "
        "sentences (it goes straight into a Telegram alert) — be brief, no preamble. "
        "Output strict JSON only, no markdown:\n"
        '{"driver_th": "..." or null, "driver_time": "HH:MM", "severity": "HIGH|MEDIUM|LOW", '
        '"credibility": "HIGH|MEDIUM|LOW", "reasoning_th": "<=2 sentences"}'
    )

    content = provider = ""
    if ANTHROPIC_API_KEY:
        content, provider = _claude_chat(prompt), "claude"
    if not content and GROQ_API_KEY:
        content, provider = _groq_chat(prompt), ("groq-fallback" if ANTHROPIC_API_KEY else "groq")
    if not content:
        return ""
    data = _extract_json(content)
    if data is None:
        print("⚠️ enrichment: could not parse JSON from model reply")
        return ""
    print(f"  enrichment via {provider}")

    driver = data.get("driver_th")
    if not driver:
        return "🤖 <b>TA เปลี่ยน</b> — <i>ไม่พบข่าวที่อธิบายได้ชัด อาจเป็นการเคลื่อนไหวทางเทคนิค/สภาพคล่องบาง</i>"

    t = data.get("driver_time", "")
    sev = SEV_EMOJI.get(str(data.get("severity", "")).upper(), "—")
    cred = CRED_EMOJI.get(str(data.get("credibility", "")).upper(), "—")
    reason = _html_escape(str(data.get("reasoning_th", "")).strip())
    driver_e = _html_escape(str(driver).strip())
    t_str = f" ({t})" if t else ""
    lines = [
        f"🤖 <b>TA เปลี่ยน น่าจะเพราะ:</b> {driver_e}{t_str}",
        f"<b>ความรุนแรง:</b> {sev}",
        f"<b>น่าเชื่อถือ:</b> {cred}",
    ]
    if reason:
        lines.append(reason)
    return "\n".join(lines)


def format_alert(changes: list, current: dict, now_utc: datetime) -> str:
    ict = now_utc.astimezone(timezone.utc).timestamp()
    # ICT = UTC+7
    from datetime import timedelta
    ict_dt = (now_utc + timedelta(hours=7)).strftime("%Y-%m-%d %H:%M")

    lines = ["🔔 <b>TV Signal Change — EURUSD</b>", f"<i>{ict_dt} ICT</i>", ""]
    for ch in changes:
        tf = ch["tf"]
        old = ch["old"]
        new = ch["new"]
        emo_old = RECO_EMOJI.get(old, old)
        emo_new = RECO_EMOJI.get(new, new)
        lines.append(f"<b>{tf}</b>: {emo_old} {old} → {emo_new} {new}")

    lines.append("")
    lines.append("<b>Current state:</b>")
    for tf, sig in current.items():
        emo = RECO_EMOJI.get(sig["summary_reco"], "")
        counts = f"B{sig['summary_buy']}/S{sig['summary_sell']}/N{sig['summary_neutral']}"
        close = sig.get("close")
        close_str = f" @ {close:.5f}" if isinstance(close, (int, float)) else ""
        lines.append(f"  {tf}: {emo} {sig['summary_reco']} ({counts}){close_str}")

    return "\n".join(lines)


def main() -> int:
    now = datetime.now(timezone.utc)
    print(f"⏱️  Run at {now.isoformat()}")

    if not is_fx_market_open(now):
        print("💤 FX market closed (weekend) — skip")
        return 0

    state = load_state()
    last_signals = state.get("signals", {})
    is_first_run = not last_signals

    current = {}
    for tf_name, interval in INTERVALS.items():
        try:
            current[tf_name] = fetch_signal(interval)
            print(f"  {tf_name}: {current[tf_name]['summary_reco']}")
        except Exception as e:
            print(f"❌ Fetch {tf_name} failed: {e}")
            return 1

    changes = []
    for tf_name, sig in current.items():
        old_reco = last_signals.get(tf_name, {}).get("summary_reco")
        new_reco = sig["summary_reco"]
        if old_reco and old_reco != new_reco:
            changes.append({"tf": tf_name, "old": old_reco, "new": new_reco})

    if changes and not is_first_run:
        msg = format_alert(changes, current, now)
        # News enrichment — best-effort. Wrapped so a failure here never blocks the alert.
        try:
            fj_items = fetch_recent_fj(FJ_LOOKBACK_MIN)
            analysis = analyze_flip(changes, fj_items)
            if analysis:
                msg = msg + "\n\n" + analysis
        except Exception as e:
            print(f"⚠️ enrichment failed (sending plain alert): {type(e).__name__}: {e}")
        print(msg)
        send_telegram(msg)
    elif is_first_run:
        print("ℹ️ First run — saving baseline, no alert sent")
    else:
        print("✓ No changes")

    state["signals"] = current
    state["last_check_utc"] = now.isoformat()
    save_state(state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
