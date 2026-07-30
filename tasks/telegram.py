"""Telegram task — long-polls the Bot API and hands messages to the router.

A task is an always-on connector: it owns one interface (here, Telegram) and
speaks one tiny protocol with the core:

    start(on_message)                    called once, in a dedicated thread; loop forever
    on_message(text, reply, chat_id)     call this per incoming message;
                                         reply(text) sends the answer back

Config (in .env):
    TELEGRAM_BOT_TOKEN    bot token from @BotFather
    TELEGRAM_CHAT_ID      the single chat allowed to talk to the bot
"""

import os
import threading
import time

import httpx

NAME = "telegram"
DESCRIPTION = "Telegram bot via long-polling"


def start(on_message):
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        print("[telegram] TELEGRAM_BOT_TOKEN not set — task not started")
        return
    allowed = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    api = f"https://api.telegram.org/bot{token}"
    offset = None

    def send(chat, text):
        text = text or "(empty)"
        for i in range(0, len(text), 4000):
            try:
                httpx.post(f"{api}/sendMessage",
                           json={"chat_id": chat, "text": text[i:i + 4000]}, timeout=30)
            except Exception as e:  # noqa: BLE001
                print(f"[telegram send error] {e}")

    if allowed:
        print(f"[telegram] running — locked to chat {allowed}")
    else:
        print("[telegram] running — UNLOCKED: reports chat ids only, executes nothing. "
              "Message it, set TELEGRAM_CHAT_ID in .env, restart.")

    # Escalating backoff on persistent poll errors (revoked token, network
    # down) — 5s, 10s, 20s, ... capped at 60s, reset once polling recovers.
    # Only logs when the backoff interval changes, so a long outage doesn't
    # spam the journal with an identical line every few seconds.
    backoff = 5
    logged_backoff = None

    while True:
        try:
            r = httpx.get(f"{api}/getUpdates", params={"timeout": 30, "offset": offset}, timeout=40)
            data = r.json()
            if not data.get("ok", True):
                # Telegram returns {"ok": false, "description": ...} on auth
                # failure (revoked token) or a conflicting long-poll (409) —
                # this was previously swallowed as "no updates" forever.
                if backoff != logged_backoff:
                    print(f"[telegram poll error] Telegram API: {data.get('description', 'unknown error')} "
                          f"— backing off to {backoff}s")
                    logged_backoff = backoff
                time.sleep(backoff)
                backoff = min(backoff * 2, 60)
                continue
            updates = data.get("result", [])
        except Exception as e:  # noqa: BLE001
            if backoff != logged_backoff:
                print(f"[telegram poll error] {e} — backing off to {backoff}s")
                logged_backoff = backoff
            time.sleep(backoff)
            backoff = min(backoff * 2, 60)
            continue

        backoff = 5
        logged_backoff = None

        for upd in updates:
            offset = upd["update_id"] + 1
            msg = upd.get("message") or upd.get("edited_message") or {}
            text = (msg.get("text") or "").strip()
            chat = msg.get("chat", {}).get("id")
            if not text or chat is None:
                continue
            if not allowed:
                send(chat, f"Bot unlocked. Your chat id is {chat}. "
                           f"Set TELEGRAM_CHAT_ID={chat} in .env and restart to enable.")
                print(f"[telegram unlocked] chat {chat} said: {text!r}")
                continue
            if str(chat) != allowed:
                send(chat, "unauthorized")
                print(f"[telegram blocked] chat {chat}: {text!r}")
                continue
            print(f"[tg {chat}] {text}")
            # Dispatch in a worker thread so the poll loop keeps running. A CC call
            # can take up to 15 min; blocking here freezes incoming messages and the
            # offset, so a restart would replay them.
            def _dispatch(text=text, chat=chat):
                try:
                    httpx.post(f"{api}/sendChatAction",
                               json={"chat_id": chat, "action": "typing"}, timeout=5)
                except Exception:  # noqa: BLE001
                    pass
                on_message(text, lambda reply_text, _chat=chat: send(_chat, reply_text), str(chat))
            threading.Thread(target=_dispatch, daemon=True).start()
