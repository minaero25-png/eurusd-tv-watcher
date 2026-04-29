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
EXCHANGE = os.environ.get("TV_EXCHANGE", "FX_IDC")
SCREENER = os.environ.get("TV_SCREENER", "forex")

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_IDS = [
    x.strip() for x in os.environ.get("TELEGRAM_ALLOWED_CHAT_IDS", "").split(",") if x.strip()
]

INTERVALS = {
    "M30": Interval.INTERVAL_30_MINUTES,
    "H1": Interval.INTERVAL_1_HOUR,
}

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
