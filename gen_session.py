"""One-time helper — generate a Telethon StringSession for the FJ BURNER account.

Run this LOCALLY once, signed in as the burner Telegram account (NOT your personal
account). It prints a session string → store that as the GitHub secret
FJ_SESSION_STRING so the cloud watcher can read the public Financial Juice channel.

Usage:
    pip install telethon
    python gen_session.py
    # enter TG_API_ID / TG_API_HASH (from https://my.telegram.org) + burner phone
    # Telegram sends a login code to the burner → enter it
    # copy the printed SESSION STRING into the GH secret

The session string logs in AS the burner account. Keep it secret, but because the
burner only ever joins the public FJ channel, a leak exposes ~nothing (see README).
"""
import os

from telethon.sync import TelegramClient
from telethon.sessions import StringSession

api_id = int(os.environ.get("TG_API_ID") or input("TG_API_ID: ").strip())
api_hash = os.environ.get("TG_API_HASH") or input("TG_API_HASH: ").strip()
phone = os.environ.get("TG_PHONE") or input("Burner phone (+countrycode...): ").strip()

with TelegramClient(StringSession(), api_id, api_hash) as client:
    client.start(phone=phone)
    me = client.get_me()
    print(f"\n✅ Logged in as: {me.first_name} (@{me.username}) id={me.id}")
    print("\n=== FJ_SESSION_STRING (store as GitHub secret — keep private) ===\n")
    print(client.session.save())
    print("\n=== end — paste the line above into the GH secret FJ_SESSION_STRING ===")
