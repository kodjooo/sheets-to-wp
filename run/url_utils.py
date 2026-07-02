from urllib.parse import urlparse, parse_qs, unquote


def normalize_http_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""
    if url.startswith("http://") or url.startswith("https://"):
        return url
    return f"https://{url}"


def unwrap_google_viewer_url(url: str) -> str:
    """Разворачивает ссылку Google Docs Viewer в прямой URL файла.

    Google Viewer оборачивает документ так:
        https://docs.google.com/viewer?url=<direct_url>
        https://docs.google.com/viewerng/viewer?url=<direct_url>
    Такая ссылка отдаёт HTML-обёртку, а не сам PDF, поэтому её нужно
    развернуть до значения параметра ?url= перед загрузкой файла.
    Если это не viewer-ссылка, URL возвращается без изменений.
    """
    url = (url or "").strip()
    if not url:
        return ""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if host not in ("docs.google.com", "www.google.com") or "viewer" not in parsed.path:
        return url
    target = parse_qs(parsed.query).get("url", [None])[0]
    if not target:
        return url
    return unquote(target).strip()
