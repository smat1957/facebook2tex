import hashlib
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse

IMAGE_EXTS = {".jpg", ".jpeg", ".png"}
URL_RE = re.compile(r'https?://[^\s<>"\]\}）)。,、]+')


def fix_facebook_text(s):
    if not isinstance(s, str):
        return ""

    try:
        s = s.encode("latin1").decode("utf-8")
    except Exception:
        pass

    return s.replace("\ufe0f", "")


def dt_from_ts(ts):
    return datetime.fromtimestamp(ts)


def sha1_short(s, length=10):
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:length]


def get_youtube_video_id(url):
    try:
        p = urlparse(url)
        host = (p.hostname or "").lower()
        path = p.path.strip("/")

        if host == "youtu.be" or host.endswith(".youtu.be"):
            return path.split("/")[0] if path else None

        if host == "youtube.com" or host.endswith(".youtube.com"):
            if path == "watch":
                qs = parse_qs(p.query)
                return qs.get("v", [None])[0]

            for prefix in ("shorts/", "embed/", "live/"):
                if path.startswith(prefix):
                    parts = path.split("/")
                    return parts[1] if len(parts) > 1 else None

    except Exception:
        pass

    return None


def normalize_display_url(url):
    url = fix_facebook_text(url).strip()

    youtube_id = get_youtube_video_id(url)
    if youtube_id:
        p = urlparse(url)
        qs = parse_qs(p.query)

        new_url = f"https://youtu.be/{youtube_id}"
        keep_params = []

        if "t" in qs and qs["t"]:
            keep_params.append(("t", qs["t"][0]))

        if "start" in qs and qs["start"]:
            keep_params.append(("t", qs["start"][0]))

        if keep_params:
            query = "&".join(f"{k}={v}" for k, v in keep_params)
            new_url += "?" + query

        return new_url

    return url.rstrip("?&")


def normalize_url_for_dedupe(url):
    url = fix_facebook_text(url).strip()
    youtube_id = get_youtube_video_id(url)

    if youtube_id:
        return f"youtube:{youtube_id}"

    return normalize_display_url(url)


def source_path_from_uri(uri, archive_root, activity_dir):
    if uri.startswith("your_facebook_activity/"):
        return archive_root / uri
    return activity_dir / uri


def find_media_uris(post, archive_root, activity_dir):
    found_uris = []

    def add_uri(uri):
        uri = fix_facebook_text(uri).strip()
        if not uri:
            return

        suffix = Path(uri).suffix.lower()
        if suffix not in IMAGE_EXTS:
            return

        src = source_path_from_uri(uri, archive_root, activity_dir)
        if not src.exists():
            return

        if uri not in found_uris:
            found_uris.append(uri)

    def walk(obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k == "uri":
                    add_uri(v)
                else:
                    walk(v)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)

    walk(post)
    return found_uris


def find_texts(post):
    texts = []

    for item in post.get("data", []):
        for key in ("post", "text", "description", "comment"):
            value = item.get(key)
            if value:
                texts.append(fix_facebook_text(value).strip())

    for att in post.get("attachments", []):
        for item in att.get("data", []):
            for key in ("description", "text"):
                value = item.get(key)
                if value:
                    texts.append(fix_facebook_text(value).strip())

            ext = item.get("external_context", {})
            for key in ("description", "title"):
                value = ext.get(key)
                if value:
                    texts.append(fix_facebook_text(value).strip())

    result = []
    seen = set()

    for t in texts:
        if t and t not in seen:
            result.append(t)
            seen.add(t)

    return result


def find_text_links(texts):
    links = []
    seen = set()

    for text in texts:
        text = fix_facebook_text(text)
        for m in URL_RE.finditer(text):
            url = normalize_display_url(m.group(0))
            key = normalize_url_for_dedupe(url)

            if key not in seen:
                seen.add(key)
                links.append(url)

    return links


def find_external_links(post):
    links = []
    seen = set()

    def add(url):
        url = normalize_display_url(url)
        if not url:
            return

        key = normalize_url_for_dedupe(url)
        if key in seen:
            return

        seen.add(key)
        links.append(url)

    for att in post.get("attachments", []):
        for item in att.get("data", []):
            ext = item.get("external_context", {})
            add(ext.get("url", ""))

    return links