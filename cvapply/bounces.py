"""Learned bounce blocklist.

Guessed `careers@<company>` addresses are the main source of 550 bounces. The
bounce notice Gmail receives names the dead address exactly, so every failure is
a free, authoritative fact. This module reads those notices and remembers the
addresses permanently, so the same dead mailbox is never tried twice.

Before this, bounced addresses were hand-copied into the BLOCKED_EMAILS literal
in apply_email.py, which meant the system re-sent to dead addresses forever.
"""

from __future__ import annotations

import email
import imaplib
import json
import re
from pathlib import Path

from .config import settings

STORE = Path(__file__).resolve().parent.parent / ".bounced_emails.json"

# Addresses appear in bounce bodies as "<foo@bar.com>" or "to foo@bar.com".
_EMAIL_RX = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")

_BOUNCE_SENDERS = (
    "mailer-daemon",
    "postmaster",
    "mail delivery subsystem",
    "microsoftexchange",
)
_BOUNCE_SUBJECTS = (
    "undeliverable",
    "delivery status notification",
    "delivery has failed",
    "returned mail",
    "mail delivery failed",
    "failure notice",
    "delivery incomplete",
)
# Permanent-failure signals. A full mailbox or a greylist is temporary and must
# not poison the address forever.
_HARD_FAIL = (
    "550",
    "551",
    "553",
    "no such user",
    "user unknown",
    "recipient not found",
    "address not found",
    "does not exist",
    "unknown recipient",
    "recipient rejected",
    "mailbox unavailable",
    "no mailbox",
)


_CACHE: set[str] | None = None


def _local() -> set[str]:
    try:
        return {e.lower() for e in json.loads(STORE.read_text(encoding="utf-8"))}
    except Exception:
        return set()


def _write_local(addrs: set[str]) -> None:
    try:
        STORE.write_text(json.dumps(sorted(addrs), indent=2), encoding="utf-8")
    except Exception:
        pass


def load_bounced(refresh: bool = False) -> set[str]:
    """Dead addresses, authoritative copy in Convex.

    The 24/7 GitHub Actions runner gets a fresh filesystem every run, so a local
    file alone would forget every bounce and re-send to the same dead mailbox
    forever. Convex is the store; the file is an offline cache for when the
    network is down. Cached per process -- this is called on every send.
    """
    global _CACHE
    if _CACHE is not None and not refresh:
        return _CACHE

    known = _local()
    try:
        from .convex_api import ConvexClient

        remote = ConvexClient().query("queries:deadEmails", {}) or []
        if remote:
            known |= {str(a).lower() for a in remote}
            _write_local(known)
    except Exception:
        pass  # offline: the cached file still blocks known-dead addresses

    _CACHE = known
    return known


def record_bounce(addr: str, reason: str = "", source: str = "gmail-bounce") -> bool:
    """Remember one dead address, in Convex and on disk. True if it was new."""
    addr = (addr or "").lower().strip()
    if not addr or "@" not in addr:
        return False
    known = load_bounced()
    if addr in known:
        return False

    known.add(addr)
    _write_local(known)
    if _CACHE is not None:
        _CACHE.add(addr)
    try:
        from .convex_api import ConvexClient

        ConvexClient().mutation(
            "mutations:markDeadEmail",
            {"address": addr, "reason": reason[:300], "source": source},
        )
    except Exception as exc:
        print(f"  [bounces] {addr} saved locally only: {str(exc)[:90]}")
    return True


def _failed_recipients(msg: email.message.Message) -> set[str]:
    """Pull the dead address out of a bounce notice."""
    found: set[str] = set()

    # Preferred: the RFC 3464 delivery-status part states it explicitly.
    for part in msg.walk():
        if part.get_content_type() == "message/delivery-status":
            text = part.as_string()
            for m in re.finditer(r"Final-Recipient:\s*[^;]*;\s*([^\s]+)", text, re.I):
                found.add(m.group(1).strip().lower())

    if found:
        return found

    # Fallback: scan the body, minus our own address and the bounce reporter.
    body = ""
    for part in msg.walk():
        if part.get_content_type() == "text/plain":
            try:
                body += part.get_payload(decode=True).decode("utf-8", "replace")
            except Exception:
                continue
    ours = (settings.email_user or "").lower()
    for addr in _EMAIL_RX.findall(body):
        low = addr.lower()
        if low == ours or any(s in low for s in _BOUNCE_SENDERS):
            continue
        found.add(low)
    return found


def _is_hard_bounce(msg: email.message.Message) -> bool:
    blob = str(msg.get("Subject", "")).lower()
    for part in msg.walk():
        if part.get_content_type() in ("text/plain", "message/delivery-status"):
            try:
                blob += part.as_string().lower()
            except Exception:
                continue
    return any(sig in blob for sig in _HARD_FAIL)


def scan_bounces(limit: int = 40) -> list[str]:
    """Scan recent mail for bounce notices. Returns newly blocked addresses."""
    if not settings.email_user or not settings.email_app_password:
        return []

    newly: list[str] = []
    mail = None
    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(settings.email_user, settings.email_app_password)
        mail.select("INBOX")

        ids: list[bytes] = []
        for term in ('(FROM "mailer-daemon")', '(FROM "postmaster")', '(SUBJECT "Undeliverable")'):
            status, data = mail.search(None, term)
            if status == "OK" and data and data[0]:
                ids.extend(data[0].split())

        for msg_id in list(dict.fromkeys(ids))[-limit:]:
            status, msg_data = mail.fetch(msg_id, "(RFC822)")
            if status != "OK" or not msg_data or not msg_data[0]:
                continue
            raw = msg_data[0][1]
            if isinstance(raw, tuple):
                raw = raw[1]
            msg = email.message_from_bytes(raw)

            sender = str(msg.get("From", "")).lower()
            subject = str(msg.get("Subject", "")).lower()
            looks_like_bounce = any(s in sender for s in _BOUNCE_SENDERS) or any(
                s in subject for s in _BOUNCE_SUBJECTS
            )
            if not looks_like_bounce or not _is_hard_bounce(msg):
                continue

            for addr in _failed_recipients(msg):
                if record_bounce(addr, reason=str(msg.get("Subject", ""))[:200]):
                    newly.append(addr)
    except Exception as exc:
        print(f"  [bounces] scan skipped: {str(exc)[:160]}")
    finally:
        if mail is not None:
            try:
                mail.logout()
            except Exception:
                pass

    if newly:
        print(f"  [bounces] blocked {len(newly)} dead address(es): {', '.join(newly[:5])}")
    return newly
