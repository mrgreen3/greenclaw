"""Telegram task — long-polls the Bot API and hands messages to the router.

A task is an always-on connector: it owns one interface (here, Telegram) and
speaks one tiny protocol with the core:

    start(on_message)              called once, in a dedicated thread; loop forever
    on_message(text, reply)        call this per incoming message;
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

    while True:
        try:
            r = httpx.get(f"{api}/getUpdates", params={"timeout": 30, "offset": offset}, timeout=40)
            updates = r.json().get("result", [])
        except Exception as e:  # noqa: BLE001
            print(f"[telegram poll error] {e}")
            time.sleep(5)
            continue

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
            threading.Thread(
                target=on_message,
                args=(text, lambda reply_text, _chat=chat: send(_chat, reply_text)),
                daemon=True,
            ).start()
