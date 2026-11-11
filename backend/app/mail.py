import email
import hashlib
import imaplib
import logging
import os
import re
from datetime import datetime, timezone
from email.header import decode_header

from . import extract, repo

log = logging.getLogger("openpantry.mail")

IMAP_HOST = os.environ.get("IMAP_HOST", "")
IMAP_USER = os.environ.get("IMAP_USER", "")
IMAP_PASSWORD = os.environ.get("IMAP_PASSWORD", "")
IMAP_FOLDER = os.environ.get("IMAP_FOLDER", "INBOX")
POLL_SECONDS = int(os.environ.get("IMAP_POLL_SECONDS", "60"))

RECEIPT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "receipts")
ATTACHMENT_RE = re.compile(r"\.(pdf|png|jpe?g|heic)$", re.IGNORECASE)


def enabled() -> bool:
    return bool(IMAP_HOST and IMAP_USER and IMAP_PASSWORD)


def decode_subject(raw: str) -> str:
    parts = decode_header(raw or "")
    decoded = ""
    for value, charset in parts:
        decoded += value.decode(charset or "utf-8", errors="replace") if isinstance(value, bytes) else value
    return decoded


def extract_date(msg: email.message.Message) -> str:
    parsed = email.utils.parsedate_to_datetime(msg.get("Date", ""))
    if parsed is None:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return parsed.strftime("%Y-%m-%d")


def save_attachments(msg: email.message.Message) -> list[str]:
    os.makedirs(RECEIPT_DIR, exist_ok=True)
    saved = []
    for part in msg.walk():
        filename = part.get_filename()
        if not filename or not ATTACHMENT_RE.search(filename):
            continue
        payload = part.get_payload(decode=True)
        if not payload:
            continue
        digest = hashlib.sha1(payload).hexdigest()[:12]
        safe_name = f"{digest}_{re.sub(r'[^A-Za-z0-9._-]', '_', filename)}"
        path = os.path.join(RECEIPT_DIR, safe_name)
        if not os.path.exists(path):
            with open(path, "wb") as handle:
                handle.write(payload)
        saved.append(path)
    return saved


def guess_store(msg: email.message.Message, subject: str) -> str:
    sender = msg.get("From", "")
    match = re.search(r"([\w.-]+)\.[a-z]{2,3}[^@]*@", sender, re.IGNORECASE)
    if match:
        return match.group(1).capitalize()
    words = subject.split()
    return words[0] if words else "Unknown"


def process_message(msg: email.message.Message) -> bool:
    message_hash = hashlib.sha1(
        (str(msg.get("Message-ID", "")) + str(msg.get("Date", "")) + str(msg.get("Subject", ""))).encode()
    ).hexdigest()
    subject = decode_subject(msg.get("Subject", ""))
    attachments = save_attachments(msg)
    if not attachments:
        return False

    ocr_text = ""
    for path in attachments:
        text = extract.ocr_receipt_file(path)
        if text and len(text.strip()) > len(ocr_text):
            ocr_text = text

    extracted = extract.llm_receipt_items(ocr_text) if ocr_text else None
    if extracted:
        receipt = repo.create_receipt(
            store=extracted["store"] or guess_store(msg, subject),
            date=extracted["date"] or extract_date(msg),
            total=extracted["total"],
            items=extracted["items"],
            source_file=attachments[0],
            message_hash=message_hash,
        )
    else:
        receipt = repo.create_receipt(
            store=guess_store(msg, subject),
            date=extract_date(msg),
            total=0,
            items=[],
            source_file=attachments[0],
            message_hash=message_hash,
        )
    if receipt:
        log.info("ingested receipt %s (%d items)", receipt["id"], len(receipt["items"]))
    return receipt is not None


def poll_once() -> int:
    if not enabled():
        return 0
    count = 0
    conn = imaplib.IMAP4_SSL(IMAP_HOST)
    try:
        conn.login(IMAP_USER, IMAP_PASSWORD)
        conn.select(IMAP_FOLDER)
        status, data = conn.search(None, "UNSEEN")
        if status != "OK":
            return 0
        for num in data[0].split():
            status, msg_data = conn.fetch(num, "(RFC822)")
            if status != "OK":
                continue
            msg = email.message_from_bytes(msg_data[0][1])
            try:
                if process_message(msg):
                    count += 1
            except Exception:
                log.exception("failed to process message %s", num)
            conn.store(num, "+FLAGS", "\\Seen")
    finally:
        conn.logout()
    return count


async def poll_loop():
    import asyncio
    while True:
        try:
            poll_once()
        except Exception:
            log.exception("mail poll failed")
        await asyncio.sleep(POLL_SECONDS)
