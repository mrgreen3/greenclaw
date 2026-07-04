"""Email task — polls IMAP inbox and sends responses via SMTP.

A task is an always-on connector: it owns one interface (here, Email) and
speaks one tiny protocol with the core:

    start(on_message)                    called once, in a dedicated thread; loop forever
    on_message(text, reply, chat_id)     call this per incoming message;
                                         reply(text) sends the answer back

Config (in .env):
    EMAIL_IMAP_HOST           IMAP server hostname
    EMAIL_IMAP_PORT           IMAP port (usually 993)
    EMAIL_SMTP_HOST           SMTP server hostname
    EMAIL_SMTP_PORT           SMTP port (usually 587)
    EMAIL_ADDRESS             Email address (greenclaw@archbang.org)
    EMAIL_PASSWORD            Email password
    EMAIL_TRUSTED_SENDERS     Comma-separated list of trusted senders (required, no default)
"""

import os
import re
import threading
import time
import imaplib
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.parser import Parser
from email.utils import parseaddr

NAME = "email"
DESCRIPTION = "Email task via IMAP/SMTP"


def start(on_message):
    imap_host = os.environ.get("EMAIL_IMAP_HOST", "").strip()
    imap_port = int(os.environ.get("EMAIL_IMAP_PORT", "993"))
    smtp_host = os.environ.get("EMAIL_SMTP_HOST", "").strip()
    smtp_port = int(os.environ.get("EMAIL_SMTP_PORT", "587"))
    email_addr = os.environ.get("EMAIL_ADDRESS", "").strip()
    email_pass = os.environ.get("EMAIL_PASSWORD", "").strip()
    trusted_senders = os.environ.get("EMAIL_TRUSTED_SENDERS", "").strip().split(",")
    trusted_senders = [s.strip().lower() for s in trusted_senders if s.strip()]

    if not all([imap_host, smtp_host, email_addr, email_pass, trusted_senders]):
        print("[email] EMAIL_IMAP_HOST, EMAIL_SMTP_HOST, EMAIL_ADDRESS, EMAIL_PASSWORD, "
              "and EMAIL_TRUSTED_SENDERS required — task not started")
        return

    print(f"[email] running — listening on {email_addr} (trusted senders: {', '.join(trusted_senders)})")

    def send_reply(recipient, subject, body):
        """Send an email reply via SMTP. Returns True on success, False on failure."""
        try:
            stripped = body.strip()
            if stripped.startswith("<"):
                plain = "\n".join(
                    line for line in re.sub(r"<[^>]+>", "", stripped).splitlines() if line.strip()
                )
                msg = MIMEMultipart("alternative")
                msg.attach(MIMEText(plain, "plain"))
                msg.attach(MIMEText(stripped, "html"))
            else:
                msg = MIMEMultipart("alternative")
                msg.attach(MIMEText(body, "plain"))
            msg["Subject"] = subject
            msg["From"] = email_addr
            msg["To"] = recipient

            # Port 465 = SMTPS (implicit TLS); port 587 = SMTP + STARTTLS
            if smtp_port == 465:
                with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=30) as smtp:
                    smtp.login(email_addr, email_pass)
                    smtp.sendmail(email_addr, recipient, msg.as_string())
            else:
                with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as smtp:
                    smtp.starttls()
                    smtp.login(email_addr, email_pass)
                    smtp.sendmail(email_addr, recipient, msg.as_string())
            print(f"[email] reply sent to {recipient}")
            return True
        except Exception as e:  # noqa: BLE001
            print(f"[email send error] {e}")
            return False

    def delete_message(msg_uid):
        """Permanently remove a message from INBOX by UID, once its reply has
        been sent. Runs on its own short-lived IMAP connection since the main
        poll connection is closed by the time a reply (which goes through the
        model) comes back. UID (not sequence number) survives across
        connections and is unaffected by other messages being expunged.
        """
        try:
            m = imaplib.IMAP4_SSL(imap_host, imap_port, timeout=30)
            m.login(email_addr, email_pass)
            m.select("INBOX")
            m.uid("STORE", msg_uid, "+FLAGS", "(\\Deleted)")
            m.expunge()
            m.close()
            m.logout()
            print(f"[email] deleted uid {msg_uid.decode() if isinstance(msg_uid, bytes) else msg_uid} after reply")
        except Exception as e:  # noqa: BLE001
            print(f"[email] delete error: {e}")

    while True:
        try:
            # Connect to IMAP
            mail = imaplib.IMAP4_SSL(imap_host, imap_port, timeout=30)
            mail.login(email_addr, email_pass)
            mail.select("INBOX")

            # Search for unread messages. UID (not sequence number) is used
            # throughout so delete_message() can reference the same message
            # later from a fresh connection, after other messages in this
            # batch may have shifted sequence numbers via expunge.
            status, msg_ids = mail.uid("SEARCH", None, "UNSEEN")
            if status != "OK":
                print("[email] IMAP search failed")
                mail.close()
                mail.logout()
                time.sleep(30)
                continue

            msg_list = msg_ids[0].split()
            if not msg_list:
                # No new messages, sleep and retry
                mail.close()
                mail.logout()
                time.sleep(30)
                continue

            # Process each message
            for msg_uid in msg_list:
                try:
                    status, msg_data = mail.uid("FETCH", msg_uid, "(RFC822)")
                    if status != "OK":
                        continue

                    # Mark as seen as soon as we have the message, before parsing
                    # it. A malformed message that throws mid-parse must not stay
                    # \Unseen — otherwise it gets refetched and re-crashes on every
                    # 30s poll forever. Losing one malformed message to a rare
                    # mark-then-crash race is a far better failure mode than that.
                    mail.uid("STORE", msg_uid, "+FLAGS", "\\Seen")

                    # Parse email
                    msg_bytes = msg_data[0][1]
                    parser = Parser()
                    email_msg = parser.parsestr(msg_bytes.decode("utf-8", errors="ignore"))

                    sender = email_msg.get("From", "")
                    subject = email_msg.get("Subject", "(no subject)").strip()
                    reply_to_raw = email_msg.get("Reply-To", "")

                    # parseaddr handles "Name <addr@x>" and bare addresses.
                    from_addr = parseaddr(sender)[1].lower()
                    reply_to_addr = parseaddr(reply_to_raw)[1].lower() if reply_to_raw else from_addr

                    # Trust is decided on the From address. Reply only to a trusted
                    # address: if Reply-To points elsewhere, ignore it (defeats a
                    # foreign-Reply-To exfil). From is a forged header — for real
                    # sender verification enable DKIM/SPF checking at the MTA.
                    if from_addr not in trusted_senders:
                        print(f"[email] blocked — untrusted sender: {from_addr}")
                        continue
                    reply_to = reply_to_addr if reply_to_addr in trusted_senders else from_addr

                    # Extract body (plain text preferred)
                    body = ""
                    if email_msg.is_multipart():
                        for part in email_msg.walk():
                            if part.get_content_type() == "text/plain":
                                body = part.get_payload(decode=True).decode("utf-8", errors="ignore")
                                break
                    else:
                        body = email_msg.get_payload(decode=True).decode("utf-8", errors="ignore")

                    body = body.strip()
                    if not body:
                        print(f"[email] empty body from {from_addr}, skipping")
                        continue

                    # Build text for routing (include subject for context)
                    text = f"[email subject: {subject}]\n{body}"

                    print(f"[email] from {from_addr}: {subject[:50]}")

                    # Dispatch in a worker thread to keep IMAP connection free
                    def _dispatch(text=text, subject=subject, reply_to_addr=reply_to, msg_uid=msg_uid):
                        try:
                            def _reply(response_text):
                                if send_reply(reply_to_addr, f"Re: {subject}", response_text):
                                    # Only remove the message once the reply
                                    # actually went out — a failed send should
                                    # leave it in the mailbox to retry/notice.
                                    delete_message(msg_uid)
                            on_message(text, _reply, "email")
                        except Exception as e:  # noqa: BLE001
                            print(f"[email dispatch error] {e}")

                    # Already marked \Seen right after fetch, above (claim-before-
                    # execute, same pattern as tasks/github_inbox.py) — dispatch is
                    # the last step now.
                    threading.Thread(target=_dispatch, daemon=True).start()

                except Exception as e:  # noqa: BLE001
                    print(f"[email] message processing error: {e}")
                    continue

            mail.close()
            mail.logout()
            time.sleep(30)  # Poll every 30 seconds

        except imaplib.IMAP4.error as e:
            print(f"[email] IMAP error: {e}")
            time.sleep(30)
        except Exception as e:  # noqa: BLE001
            print(f"[email] connection error: {e}")
            time.sleep(30)
