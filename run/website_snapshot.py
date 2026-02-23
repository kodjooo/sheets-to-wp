import hashlib
import re
import time
import asyncio
import logging
from urllib.error import URLError, HTTPError
from urllib.request import Request, urlopen

from url_utils import normalize_http_url


def _fetch_html_with_retries(url: str, retries: int = 2, delay_sec: float = 1.0) -> str:
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
    }
    last_error = None
    for attempt in range(retries + 1):
        try:
            request = Request(url=url, headers=headers)
            with urlopen(request, timeout=20) as response:
                return response.read().decode("utf-8", errors="replace")
        except (URLError, HTTPError, TimeoutError) as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(delay_sec * (2 ** attempt))
    raise last_error


def fetch_website_html(url: str) -> str:
    normalized_url = normalize_http_url(url)
    if not normalized_url:
        return ""
    return _fetch_html_with_retries(normalized_url)


def normalize_html_for_hash(html: str) -> str:
    if not html:
        return ""

    normalized = html

    # Убираем блоки с динамикой, которые часто меняются между запросами.
    normalized = re.sub(r"<!--.*?-->", " ", normalized, flags=re.DOTALL)
    normalized = re.sub(r"<script\b[^>]*>.*?</script>", " ", normalized, flags=re.IGNORECASE | re.DOTALL)
    normalized = re.sub(r"<style\b[^>]*>.*?</style>", " ", normalized, flags=re.IGNORECASE | re.DOTALL)

    # Стабилизируем query-параметры для cache-busting и маркетинговых меток.
    normalized = re.sub(r"([?&])(utm_[a-z_]+|fbclid|gclid|_ga|_gl|v|ver|timestamp|ts)=[^&\"'\\s>]+", r"", normalized, flags=re.IGNORECASE)

    # Убираем типичные volatile-токены (nonce, csrf, timestamp/id-like payloads).
    normalized = re.sub(r"\b(nonce|csrf|token|timestamp|build|cache|hash)\s*[:=]\s*[\"']?[-_a-zA-Z0-9:.]{6,}[\"']?", r"\1=", normalized, flags=re.IGNORECASE)

    # Нормализуем пробелы и регистр.
    normalized = re.sub(r"\s+", " ", normalized).strip().lower()
    return normalized


def compute_website_hash(website_url: str) -> tuple[str, str]:
    html = fetch_website_html(website_url)
    if not html:
        return "", ""
    normalized = normalize_html_for_hash(html)
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return digest, normalized


def has_website_changed(previous_hash: str, website_url: str) -> tuple[bool, str]:
    current_hash, _ = compute_website_hash(website_url)
    if not current_hash:
        return False, ""
    return previous_hash.strip() != current_hash.strip(), current_hash


async def _send_telethon_message(
    api_id: int,
    api_hash: str,
    session_name: str,
    target: str,
    message: str
) -> bool:
    from telethon import TelegramClient
    from telethon.tl.types import PeerChannel, PeerChat

    def _resolve_target(raw_target: str):
        target_text = str(raw_target or "").strip()
        if not target_text:
            return target_text
        if target_text.startswith("@"):
            return target_text
        if target_text.lstrip("-").isdigit():
            chat_id = int(target_text)
            if str(chat_id).startswith("-100"):
                return PeerChannel(abs(chat_id))
            return PeerChat(abs(chat_id))
        return target_text

    client = TelegramClient(session_name, api_id, api_hash)
    await client.connect()
    try:
        if not await client.is_user_authorized():
            logging.warning("⚠️ Telethon session is not authorized. Run init_telethon_session.py for session '%s'.", session_name)
            return False

        target_entity = _resolve_target(target)
        await client.send_message(target_entity, message)
        return True
    finally:
        await client.disconnect()


def send_telegram_notification(api_id: str, api_hash: str, session_name: str, target: str, message: str) -> bool:
    if not api_id or not api_hash or not session_name or not target or not message:
        return False

    try:
        parsed_api_id = int(api_id)
    except ValueError:
        return False

    try:
        return asyncio.run(
            _send_telethon_message(
                api_id=parsed_api_id,
                api_hash=api_hash,
                session_name=session_name,
                target=target,
                message=message,
            )
        )
    except Exception as exc:
        logging.warning("⚠️ Telegram notification failed: %s", exc)
        return False
