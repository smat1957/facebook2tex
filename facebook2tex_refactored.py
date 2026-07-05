#!/usr/bin/env python3
r"""
facebook2tex.py

Facebook の JSON バックアップを、書籍風の LaTeX 日記に変換する。

使用例:
    python facebook2tex.py ~/facebook_backup
    python facebook2tex.py ~/facebook_backup --capture-youtube
    python facebook2tex.py ~/facebook_backup --capture-links
    python facebook2tex.py ~/facebook_backup --capture-links --capture-youtube

Playwright を使う場合:
    python -m pip install playwright
    python -m playwright install chromium

# ① とにかく連続したら省略
python facebook2tex.py ~/facebook_backup --dedupe-scope consecutive

# ② 同じ月で出力済みなら省略
python facebook2tex.py ~/facebook_backup --dedupe-scope month

# ③ 同じ年で出力済みなら省略
python facebook2tex.py ~/facebook_backup --dedupe-scope year

# 重複省略しない
python facebook2tex.py ~/facebook_backup --dedupe-scope none

"""

import argparse
import hashlib
import json
import re
import shutil
import ssl
import urllib.request
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None


IMAGE_EXTS = {".jpg", ".jpeg", ".png"}
URL_RE = re.compile(r'https?://[^\s<>"\]\}）)。,、]+')

DEFAULT_OUTPUT_DIR = "facebook_diary"
DEFAULT_MAIN_TEX = "facebook_diary.tex"

SKIP_CAPTURE_DOMAINS = {
    "facebook.com", "fb.watch", "fb.me", "messenger.com",
    "instagram.com", "threads.net", "x.com", "twitter.com",
    "asahi.com", "sankei.com", "yomiuri.co.jp", "fujitv.co.jp",
    "jst.go.jp", "ehgdae.ru", "lamoncloa.gob.es", "fnn.jp",
    "kyoto.travel",
}


class FacebookDiaryBuilder:
    """
    Facebook バックアップから TeX 一式を生成するクラス。

    本文処理中に URL 表示・YouTube サムネイル・Web キャプチャをまとめて処理し、
    本文中 URL とリンク欄 URL の二重出力を避ける。
    """

    def __init__(
        self,
        archive_root,
        output_dir,
        main_tex_name=DEFAULT_MAIN_TEX,
        capture_links=False,
        capture_youtube=False,
        copy_videos=False,
        dedupe_scope="consecutive",
    ):
        self.archive_root = Path(archive_root).expanduser().resolve()
        self.output_dir = Path(output_dir).expanduser().resolve()
        self.main_tex_name = main_tex_name
        self.capture_links = capture_links
        self.capture_youtube = capture_youtube
        self.copy_videos = copy_videos
        self.activity_dir = self.archive_root / "your_facebook_activity"
        self.browser = None
        self.current_post_link_images = set()
        self.dedupe_scope = dedupe_scope
        self.last_output_key = None
        self.month_output_keys = set()
        self.year_output_keys = set()
        self.current_year = None
        self.current_month = None

    # ------------------------------------------------------------------
    # 文字列・TeX処理
    # ------------------------------------------------------------------

    @staticmethod
    def fix_facebook_text(s):
        """Facebook JSON に含まれる文字列を可能な範囲で補正する。"""
        if not isinstance(s, str):
            return ""
        try:
            s = s.encode("latin1").decode("utf-8")
        except Exception:
            pass
        return s.replace("\ufe0f", "")

    @classmethod
    def escape_tex(cls, s):
        """通常テキストを TeX 用にエスケープする。"""
        s = cls.fix_facebook_text(s)
        repl = {
            "\\": r"\textbackslash{}",
            "&": r"\&",
            "%": r"\%",
            "$": r"\$",
            "#": r"\#",
            "_": r"\_",
            "{": r"\{",
            "}": r"\}",
            "~": r"\textasciitilde{}",
            "^": r"\textasciicircum{}",
        }
        for k, v in repl.items():
            s = s.replace(k, v)
        return s

    @classmethod
    def escape_url_for_tex(cls, url):
        """URLをTeX用に最低限エスケープする。"""
        url = cls.fix_facebook_text(url).strip()
        url = url.replace("\\", r"\textbackslash{}")
        url = url.replace("&", r"\&")
        url = url.replace("%", r"\%")
        url = url.replace("#", r"\#")
        url = url.replace("{", r"\{")
        url = url.replace("}", r"\}")
        return url

    @staticmethod
    def dt_from_ts(ts):
        return datetime.fromtimestamp(ts)

    @staticmethod
    def sha1_short(s, length=10):
        return hashlib.sha1(s.encode("utf-8")).hexdigest()[:length]

    # ------------------------------------------------------------------
    # URL / YouTube処理
    # ------------------------------------------------------------------

    @staticmethod
    def get_youtube_video_id(url):
        """YouTube URL から動画IDを取り出す。"""
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

    @classmethod
    def normalize_display_url(cls, url):
        """
        TeXへ表示するURLを正規化する。

        - YouTube は https://youtu.be/動画ID に統一
        - ただし ?t=123 など意味のあるクエリは残す
        - 末尾の余分な ? や & だけ削る
        """
        url = cls.fix_facebook_text(url).strip()
        youtube_id = cls.get_youtube_video_id(url)

        if youtube_id:
            p = urlparse(url)
            qs = parse_qs(p.query)

            new_url = f"https://youtu.be/{youtube_id}"

            keep_params = []

            # 開始位置は残す
            if "t" in qs and qs["t"]:
                keep_params.append(("t", qs["t"][0]))

            # YouTube共有URLで start= がある場合も残す
            if "start" in qs and qs["start"]:
                keep_params.append(("t", qs["start"][0]))

            if keep_params:
                query = "&".join(
                    f"{k}={v}" for k, v in keep_params
                )
                new_url += "?" + query

            return new_url

        return url.rstrip("?&")

    @classmethod
    def normalize_url_for_dedupe(cls, url):
        """重複判定用URLを正規化する。"""
        url = cls.fix_facebook_text(url).strip()
        youtube_id = cls.get_youtube_video_id(url)
        if youtube_id:
            return f"youtube:{youtube_id}"
        return cls.normalize_display_url(url)

    @staticmethod
    def is_skip_capture_filetype(url):
        """HTML / PDF は Playwright キャプチャ対象外にする。"""
        try:
            path = urlparse(url).path.lower()
        except Exception:
            return True
        return path.endswith((".html", ".htm", ".pdf"))

    @classmethod
    def is_capture_target(cls, url):
        """Playwright によるWebページキャプチャ対象かどうかを判定する。"""
        try:
            host = urlparse(url).hostname
            if host is None:
                return False
            host = host.lower()
            for domain in SKIP_CAPTURE_DOMAINS:
                if host == domain or host.endswith("." + domain):
                    return False
            if cls.is_skip_capture_filetype(url):
                return False
            if cls.get_youtube_video_id(url):
                return False
            return True
        except Exception:
            return False

    @staticmethod
    def open_url_bytes(url, timeout=15):
        """URLからバイナリを取得する。SSL証明書エラー時は検証なしで再試行する。"""
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except ssl.SSLCertVerificationError:
            print(f"[ssl warning] 証明書検証に失敗したため、検証なしで再試行します: {url}")
            context = ssl._create_unverified_context()
            with urllib.request.urlopen(req, timeout=timeout, context=context) as r:
                return r.read()

    def download_youtube_thumbnail(self, url, dest_dir, prefix, index):
        """YouTubeサムネイル画像を保存し、Path または None を返す。"""
        video_id = self.get_youtube_video_id(url)
        if not video_id:
            return None

        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f"{prefix}_youtube_{index:03d}_{video_id}.jpg"
        if dest.exists():
            return dest

        thumb_urls = [
            f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg",
            f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg",
            f"https://img.youtube.com/vi/{video_id}/mqdefault.jpg",
        ]

        for thumb_url in thumb_urls:
            try:
                data = self.open_url_bytes(thumb_url, timeout=15)
                if len(data) < 1000:
                    continue
                dest.write_bytes(data)
                return dest
            except Exception as e:
                print(f"[youtube thumbnail failed] {thumb_url}")
                print(e)
        return None

    def capture_link_screenshot(self, url, dest_dir, prefix, index):
        """Playwright でリンク先ページのスクリーンショットを保存する。"""
        dest_dir.mkdir(parents=True, exist_ok=True)
        url_hash = self.sha1_short(url)
        dest = dest_dir / f"{prefix}_link_{index:03d}_{url_hash}.png"

        if dest.exists():
            return dest
        if self.browser is None:
            return None

        page = self.browser.new_page(viewport={"width": 1280, "height": 900})
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(3000)
            page.screenshot(path=str(dest), full_page=False)
            return dest
        except Exception as e:
            print(f"[capture failed] {url}")
            print(e)
            return None
        finally:
            page.close()

    # ------------------------------------------------------------------
    # JSON読み込み・データ抽出
    # ------------------------------------------------------------------

    def find_posts_json(self):
        """投稿JSONファイルを探す。"""
        posts_dir = self.archive_root / "your_facebook_activity" / "posts"
        candidates = [
            posts_dir / "your_posts__check_ins__photos_and_videos_1.json",
            posts_dir / "your_posts_1.json",
        ]
        for c in candidates:
            if c.exists():
                return c
        found = list(posts_dir.glob("*posts*.json"))
        if found:
            return found[0]
        raise FileNotFoundError("投稿JSONが見つかりません。")

    def find_comments_json(self):
        """コメントJSONファイルを探す。"""
        p = self.archive_root / "your_facebook_activity" / "comments_and_reactions" / "comments.json"
        return p if p.exists() else None

    @staticmethod
    def load_json(path):
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)

    def source_path_from_uri(self, uri):
        if uri.startswith("your_facebook_activity/"):
            return self.archive_root / uri
        return self.activity_dir / uri

    def find_texts(self, post):
        """投稿本文・添付説明文などからテキストを集める。

        ここではTeX出力は行わず、Facebook JSONから文字列だけを抽出する。
        """
        texts = []

        for item in post.get("data", []):
            for key in ("post", "text", "description", "comment"):
                value = item.get(key)
                if value:
                    texts.append(self.fix_facebook_text(value).strip())

        for att in post.get("attachments", []):
            for item in att.get("data", []):
                for key in ("description", "text"):
                    value = item.get(key)
                    if value:
                        texts.append(self.fix_facebook_text(value).strip())

                ext = item.get("external_context", {})
                for key in ("description", "title"):
                    value = ext.get(key)
                    if value:
                        texts.append(self.fix_facebook_text(value).strip())

        result = []
        seen = set()
        for t in texts:
            if t and t not in seen:
                result.append(t)
                seen.add(t)
        return result

    def collect_texts(self, post):
        """互換用ラッパー。新しいコードでは find_texts() を使う。"""
        return self.find_texts(post)

    def find_external_links(self, post):
        """external_context の URL だけを集める。本文中URLはここでは拾わない。"""
        links = []
        seen = set()

        def add(url):
            url = self.normalize_display_url(url)
            if not url:
                return
            key = self.normalize_url_for_dedupe(url)
            if key in seen:
                return
            seen.add(key)
            links.append(url)

        for att in post.get("attachments", []):
            for item in att.get("data", []):
                ext = item.get("external_context", {})
                add(ext.get("url", ""))

        return links

    def collect_external_links(self, post):
        """互換用ラッパー。新しいコードでは find_external_links() を使う。"""
        return self.find_external_links(post)

    def find_text_links(self, texts):
        """本文中に直接書かれているURLを集める。"""
        links = []
        seen = set()

        for text in texts:
            text = self.fix_facebook_text(text)
            for m in URL_RE.finditer(text):
                url = self.normalize_display_url(m.group(0))
                key = self.normalize_url_for_dedupe(url)
                if key not in seen:
                    seen.add(key)
                    links.append(url)

        return links

    def collect_urls_from_texts(self, texts):
        """互換用ラッパー。新しいコードでは find_text_links() を使う。"""
        return self.find_text_links(texts)

    def find_media_uris(self, post):
        """投稿中の画像URI一覧を返す。

        ・画像以外(PDF, mp4など)は除外
        ・重複URIは除外
        ・順序はFacebook JSONの出現順を保持
        ・ここではファイルコピーを行わない
        """
        found_uris = []

        def add_uri(uri):
            uri = self.fix_facebook_text(uri).strip()
            if not uri:
                return

            suffix = Path(uri).suffix.lower()
            if suffix not in IMAGE_EXTS:
                return

            src = self.source_path_from_uri(uri)
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

    def count_media(self, post):
        """投稿に含まれる画像数を返す。ファイルコピーは行わない。"""
        return len(self.find_media_uris(post))

    def collect_media(self, post):
        """投稿画像を pictures/YYYY/MM/ へコピーし、TeX用相対パスを返す。"""
        media_files = []
        ts = post.get("timestamp")
        if not ts:
            return media_files

        dt = self.dt_from_ts(ts)
        year = f"{dt.year:04d}"
        month = f"{dt.month:02d}"
        prefix = dt.strftime("%Y%m%d_%H%M%S")

        dest_dir = self.output_dir / "pictures" / year / month
        dest_dir.mkdir(parents=True, exist_ok=True)

        for i, uri in enumerate(self.find_media_uris(post), start=1):
            src = self.source_path_from_uri(uri)
            suffix = src.suffix.lower()
            dest_name = f"{prefix}_{i:03d}{suffix}"
            dest = dest_dir / dest_name

            if not dest.exists():
                shutil.copy2(src, dest)

            media_files.append(f"pictures/{year}/{month}/{dest_name}")

        return media_files

    # ------------------------------------------------------------------
    # コメント処理
    # ------------------------------------------------------------------

    @staticmethod
    def iter_comment_items(raw):
        if isinstance(raw, list):
            for item in raw:
                if isinstance(item, dict):
                    yield item
        elif isinstance(raw, dict):
            for value in raw.values():
                if isinstance(value, list):
                    for item in value:
                        if isinstance(item, dict):
                            yield item

    def extract_comment_record(self, item):
        ts = item.get("timestamp")
        title = self.fix_facebook_text(item.get("title", "")).strip()
        texts = []

        for d in item.get("data", []):
            c = d.get("comment")
            if isinstance(c, dict):
                value = c.get("comment", "")
                if value:
                    texts.append(self.fix_facebook_text(value).strip())
            elif isinstance(c, str):
                texts.append(self.fix_facebook_text(c).strip())

        text = "\n\n".join(t for t in texts if t)

        if not ts or not text:
            return None

        return {
            "timestamp": ts,
            "datetime": self.dt_from_ts(ts),
            "title": title,
            "text": text,
            "raw": item,   # コメント添付画像などを後で拾うために保持
        }


    def load_comments(self):
        comments_json = self.find_comments_json()
        if not comments_json:
            return [], []

        raw = self.load_json(comments_json)
        own_related = []
        other_related = []

        for item in self.iter_comment_items(raw):
            rec = self.extract_comment_record(item)
            if not rec:
                continue
            title = rec["title"]
            if "自分の投稿" in title or "自分の写真" in title or "自分の動画" in title:
                own_related.append(rec)
            else:
                other_related.append(rec)

        own_related.sort(key=lambda x: x["timestamp"])
        other_related.sort(key=lambda x: x["timestamp"])
        return own_related, other_related

    # ------------------------------------------------------------------
    # TeX出力
    # ------------------------------------------------------------------

    def write_subfile_header(self, out):
        out.write(rf"\documentclass[{self.main_tex_name}]{{subfiles}}" + "\n\n")
        out.write(r"\begin{document}" + "\n\n")

    @staticmethod
    def write_subfile_footer(out):
        out.write("\n" + r"\end{document}" + "\n")

    def make_run_path(self, tex_path):
        return "../" + tex_path

    def write_media_grid(self, out, media):
        """画像を横2枚ずつ並べる。"""
        if not media:
            return

        out.write(r"\paragraph{写真}" + "\n")
        for i in range(0, len(media), 2):
            pair = media[i:i + 2]
            out.write(r"\begin{center}" + "\n")
            if len(pair) == 2:
                for index, m in enumerate(pair):
                    run_path = self.make_run_path(m)
                    out.write(r"\begin{minipage}{0.48\linewidth}" + "\n")
                    out.write(r"\centering" + "\n")
                    #out.write(r"\href{run:" + m + "}{" + "\n")
                    out.write(
                        r"\href{run:"
                        + self.escape_url_for_tex(run_path)
                        + "}{" + "\n"
                    )
                    out.write(rf"\includegraphics[width=\linewidth]{{{m}}}" + "\n")
                    out.write("}\n")
                    out.write(r"\end{minipage}" + "\n")
                    #out.write(r"\begin{minipage}{0.48\linewidth}" + "\n")
                    #out.write(r"\centering" + "\n")
                    #out.write(rf"\includegraphics[width=\linewidth]{{{m}}}" + "\n")
                    #out.write(r"\end{minipage}" + "\n")
                    if index == 0:
                        out.write(r"\hfill" + "\n")
            else:
                m = pair[0]
                run_path = self.make_run_path(m)
                out.write(r"\begin{minipage}{0.48\linewidth}" + "\n")
                out.write(r"\centering" + "\n")
                #out.write(r"\href{run:" + m + "}{" + "\n")
                out.write(
                    r"\href{run:"
                    + self.escape_url_for_tex(run_path)
                    + "}{" + "\n"
                )
                out.write(rf"\includegraphics[width=\linewidth]{{{m}}}" + "\n")
                out.write("}\n")
                out.write(r"\end{minipage}" + "\n")
                #out.write(r"\begin{minipage}{0.70\linewidth}" + "\n")
                #out.write(r"\begin{minipage}{0.48\linewidth}" + "\n")
                #out.write(r"\centering" + "\n")
                #out.write(rf"\includegraphics[width=\linewidth]{{{m}}}" + "\n")
                #out.write(r"\end{minipage}" + "\n")
            out.write(r"\end{center}" + "\n\n")

    def write_link_image(self, out, img, url=None):
        """リンク画像を出力する。url があれば画像をクリック可能にする。"""
        if not img:
            return
        tex_path = img.relative_to(self.output_dir).as_posix()
        out.write(r"\begin{center}" + "\n")
        if url:
            out.write(r"\href{" + self.escape_url_for_tex(url) + "}{" + "\n")
        #out.write(rf"\includegraphics[width=0.9\linewidth]{{{tex_path}}}" + "\n")
        out.write(rf"\includegraphics[width=0.48\linewidth]{{{tex_path}}}" + "\n")
        if url:
            out.write("}\n")
        out.write(r"\end{center}" + "\n\n")

    def write_url_and_optional_image(self, out, url, dt, image_index):
        """URLを出力し、必要ならYouTubeサムネイルまたはWebキャプチャを続けて出す。"""
        url = self.normalize_display_url(url)
        if not url:
            return image_index

        out.write(r"\url{" + self.escape_url_for_tex(url) + "}" + "\n\n")

        key = self.normalize_url_for_dedupe(url)
        if key in self.current_post_link_images:
            return image_index

        year = f"{dt.year:04d}"
        month = f"{dt.month:02d}"
        prefix = dt.strftime("%Y%m%d_%H%M%S")
        img = None
        youtube_id = self.get_youtube_video_id(url)

        if youtube_id:
            if self.capture_youtube:
                print("YouTube detected:", url, youtube_id)
                youtube_thumb_dir = self.output_dir / "pictures" / "youtube" / year / month
                img = self.download_youtube_thumbnail(url, youtube_thumb_dir, prefix, image_index)
        else:
            if self.capture_links and self.is_capture_target(url):
                link_capture_dir = self.output_dir / "pictures" / "links" / year / month
                img = self.capture_link_screenshot(url, link_capture_dir, prefix, image_index)

        if img:
            self.write_link_image(out, img, url=url)
            self.current_post_link_images.add(key)
            image_index += 1
        return image_index

    def write_text_with_links(self, out, text, dt, image_index):
        """本文を出力する。本文中URLの直後にサムネイル/キャプチャも出力する。"""
        text = self.fix_facebook_text(text).strip()
        if not text:
            return image_index

        for raw_line in text.split("\n"):
            line = raw_line.strip()
            if not line:
                out.write("\n")
                continue

            pos = 0
            for m in URL_RE.finditer(line):
                before = line[pos:m.start()]
                if before:
                    out.write(self.escape_tex(before))
                    out.write("\n\n")

                url = self.normalize_display_url(m.group(0))
                image_index = self.write_url_and_optional_image(out, url, dt, image_index)
                pos = m.end()

            rest = line[pos:]
            if rest:
                out.write(self.escape_tex(rest))
            out.write("\n\n")
        return image_index


    def write_comment_record(self, out, rec):
        """
        コメント1件を出力する。
        コメント本文・リンク画像・添付画像を quote 内にまとめて表示する。
        """
        dt = rec["datetime"]
        date_line = dt.strftime("%Y年%m月%d日 %H:%M")

        out.write(rf"\subsection*{{{self.escape_tex(date_line)}}}" + "\n")
        out.write(
            rf"\addcontentsline{{toc}}{{subsection}}{{{self.escape_tex(date_line)}}}"
            + "\n\n"
        )

        if rec["title"]:
            out.write(r"\textbf{" + self.escape_tex(rec["title"]) + "}\n\n")

        self.current_post_link_images = set()

        out.write(r"\begin{quote}" + "\n")

        image_index = 1

        image_index = self.write_text_with_links(
            out,
            rec["text"],
            dt,
            image_index,
        )

        media = self.collect_media(rec.get("raw", {}))

        if media:
            self.write_media_grid(out, media)

        out.write(r"\end{quote}" + "\n\n")

    # ------------------------------------------------------------------
    # 重複除去
    # ------------------------------------------------------------------

    def post_links_for_dedupe(self, post):
        """重複判定用に、本文中URLと external_context URL の両方を集める。"""
        texts = self.find_texts(post)
        links = self.find_text_links(texts) + self.find_external_links(post)

        keys = set()
        for url in links:
            key = self.normalize_url_for_dedupe(url)
            if key:
                keys.add(key)

        return tuple(sorted(keys))

    def post_quality_score(self, post):
        """リンク重複時に、どちらの投稿を優先するか決める評価値。

        本文が長い投稿、画像が多い投稿を優先する。
        同点なら古い投稿を優先する。
        """
        texts = self.find_texts(post)
        text_len = sum(len(t.strip()) for t in texts)
        media_count = self.count_media(post)
        ts = post.get("timestamp", 0)
        return (text_len, media_count, -ts)

    def remove_duplicate_posts(self, posts):
        """
        Facebookバックアップ内の重複投稿を除去する。

        - 同じリンク集合なら、本文が長い投稿を残す
        - リンクだけ投稿のリンクが、本文付き投稿のリンク集合に含まれる場合、
          リンクだけ投稿は捨てる
        """
        posts = sorted(posts, key=lambda p: p.get("timestamp", 0))

        kept = []

        for post in posts:
            texts = self.find_texts(post)
            links = self.post_links_for_dedupe(post)
            media_count = self.count_media(post)

            text_len = sum(len(t.strip()) for t in texts)
            is_link_only = (text_len == 0 and media_count == 0 and links)

            if is_link_only:
                duplicated_by_later_full_post = False

                for other in posts:
                    if other is post:
                        continue

                    other_ts = other.get("timestamp", 0)
                    post_ts = post.get("timestamp", 0)

                    # 近い時刻の後続投稿だけを見る。ここでは10分以内。
                    if other_ts < post_ts:
                        continue
                    if other_ts - post_ts > 10 * 60:
                        continue

                    other_texts = self.find_texts(other)
                    other_text_len = sum(len(t.strip()) for t in other_texts)

                    if other_text_len == 0:
                        continue

                    other_links = self.post_links_for_dedupe(other)

                    # リンクだけ投稿のリンクが、本文付き投稿に含まれていれば重複扱い
                    if set(links).issubset(set(other_links)):
                        duplicated_by_later_full_post = True
                        break

                if duplicated_by_later_full_post:
                    continue

            kept.append(post)

        return kept

    def post_dedupe_key(self, post):
        """should_skip_duplicate() 用の出力内容キーを作る。"""
        texts = self.find_texts(post)
        text_links = self.find_text_links(texts)
        external_links = self.find_external_links(post)
        text_link_keys = {self.normalize_url_for_dedupe(url) for url in text_links}
        extra_links = [
            url
            for url in external_links
            if self.normalize_url_for_dedupe(url) not in text_link_keys
        ]

        return (
            tuple(texts),
            tuple(self.find_media_uris(post)),
            tuple(self.normalize_url_for_dedupe(url) for url in extra_links),
        )

    def group_posts_by_year_month(self, posts):
        """投稿を年月ごとに分類する。重複除去は別メソッドで行う。"""
        by_year_month = defaultdict(list)
        for post in posts:
            ts = post.get("timestamp")
            if not ts:
                continue
            dt = self.dt_from_ts(ts)
            by_year_month[(dt.year, dt.month)].append(post)
        return by_year_month

    # ------------------------------------------------------------------
    # ファイル出力
    # ------------------------------------------------------------------

    def write_preamble_file(self):
        path = self.output_dir / "preamble.tex"
        with path.open("w", encoding="utf-8") as out:
            out.write(r"""\usepackage[dvipdfmx]{graphicx}
\usepackage[dvipdfmx]{hyperref}
\usepackage{pxjahyper}
\usepackage{geometry}
\usepackage{url}
\usepackage{subfiles}

\geometry{margin=25mm}

\title{Facebook日記}
\author{}
\date{}
""")

    def write_main_tex(self, years):
        path = self.output_dir / self.main_tex_name
        with path.open("w", encoding="utf-8") as out:
            out.write(r"\documentclass[uplatex,openany]{jsbook}" + "\n\n")
            out.write(r"\input{preamble.tex}" + "\n\n")
            out.write(r"\begin{document}" + "\n\n")
            out.write(r"\frontmatter" + "\n")
            out.write(r"\maketitle" + "\n")
            out.write(r"\tableofcontents" + "\n\n")
            out.write(r"\mainmatter" + "\n\n")
            for year in years:
                out.write(rf"\subfile{{year{year}}}" + "\n")
            out.write("\n")
            out.write(r"\appendix" + "\n\n")
            out.write(r"\subfile{appendix_own_comments}" + "\n")
            out.write(r"\subfile{appendix_other_comments}" + "\n\n")
            out.write(r"\end{document}" + "\n")

    def should_skip_duplicate(self, output_key, dt):
        """
        重複投稿を省略するか判定する。

        none        : 重複省略しない
        consecutive : 直前に出力したものと同じなら省略
        month       : 同じ月で出力済みなら省略
        year        : 同じ年で出力済みなら省略
        """

        if self.dedupe_scope == "none":
            return False

        if self.dedupe_scope == "consecutive":
            if output_key == self.last_output_key:
                return True

            self.last_output_key = output_key
            return False

        if self.dedupe_scope == "month":
            ym = (dt.year, dt.month)

            if self.current_month != ym:
                self.current_month = ym
                self.month_output_keys = set()

            if output_key in self.month_output_keys:
                return True

            self.month_output_keys.add(output_key)
            return False

        if self.dedupe_scope == "year":
            year = dt.year

            if self.current_year != year:
                self.current_year = year
                self.year_output_keys = set()

            if output_key in self.year_output_keys:
                return True

            self.year_output_keys.add(output_key)
            return False

        return False

    def write_post(self, out, post):
        """投稿1件をTeX出力する。"""
        ts = post.get("timestamp")
        if not ts:
            return

        dt = self.dt_from_ts(ts)
        date_line = dt.strftime("%Y年%m月%d日 %H:%M")

        texts = self.find_texts(post)
        media = self.collect_media(post)

        text_links = self.find_text_links(texts)
        external_links = self.find_external_links(post)

        text_link_keys = {
            self.normalize_url_for_dedupe(url)
            for url in text_links
        }

        extra_links = [
            url
            for url in external_links
            if self.normalize_url_for_dedupe(url) not in text_link_keys
        ]

        # 本文・画像・追加リンクがすべて空なら出力しない。
        if not texts and not media and not extra_links:
            return

        # 直前に出力した投稿と内容が同じなら出力しない。
        # 日時は比較に含めない。
        output_key = (
            tuple(texts),
            tuple(self.find_media_uris(post)),
            tuple(self.normalize_url_for_dedupe(url) for url in extra_links),
        )

        if self.should_skip_duplicate(output_key, dt):
            return

        self.last_output_key = output_key

        self.current_post_link_images = set()

        out.write(rf"\subsection*{{{self.escape_tex(date_line)}}}" + "\n")
        out.write(
            rf"\addcontentsline{{toc}}{{subsection}}{{{self.escape_tex(date_line)}}}"
            + "\n\n"
        )

        image_index = 1

        for text in texts:
            image_index = self.write_text_with_links(
                out,
                text,
                dt,
                image_index,
            )

        if media:
            self.write_media_grid(out, media)

        if extra_links:
            out.write(r"\paragraph{リンク}" + "\n")

            for url in extra_links:
                image_index = self.write_url_and_optional_image(
                    out,
                    url,
                    dt,
                    image_index,
                )

    def write_year_file(self, year, by_year_month):
        path = self.output_dir / f"year{year}.tex"
        months = sorted(month for y, month in by_year_month.keys() if y == year)
        with path.open("w", encoding="utf-8") as out:
            self.write_subfile_header(out)
            out.write(rf"\chapter{{{year}年}}" + "\n\n")
            for month in months:
                out.write(rf"\section{{{month}月}}" + "\n\n")
                month_posts = sorted(by_year_month[(year, month)], key=lambda p: p.get("timestamp", 0))
                for post in month_posts:
                    self.write_post(out, post)
            self.write_subfile_footer(out)

    def write_year_files(self, by_year_month):
        years = sorted({year for year, month in by_year_month.keys()})
        for year in years:
            self.write_year_file(year, by_year_month)
        return years

    def write_appendix_file(self, path, title, records):
        with path.open("w", encoding="utf-8") as out:
            self.write_subfile_header(out)
            out.write(rf"\chapter{{{title}}}" + "\n\n")
            for rec in records:
                self.write_comment_record(out, rec)
            self.write_subfile_footer(out)

    def write_appendix_files(self, own_comments, other_comments):
        self.write_appendix_file(
            self.output_dir / "appendix_own_comments.tex",
            "自分の投稿へのコメント",
            own_comments,
        )
        self.write_appendix_file(
            self.output_dir / "appendix_other_comments.tex",
            "他人へのコメント",
            other_comments,
        )

    def build(self):
        """Facebook アーカイブから TeX 一式を生成する。"""
        if not self.activity_dir.exists():
            raise FileNotFoundError(f"見つかりません: {self.activity_dir}")

        self.output_dir.mkdir(parents=True, exist_ok=True)
        posts_json = self.find_posts_json()
        posts = self.load_json(posts_json)
        posts = self.remove_duplicate_posts(posts)
        own_comments, other_comments = self.load_comments()
        by_year_month = self.group_posts_by_year_month(posts)
        self.write_preamble_file()

        if self.capture_links:
            if sync_playwright is None:
                raise RuntimeError(
                    "playwright がインストールされていません。\n"
                    "次を実行してください:\n"
                    "  python -m pip install playwright\n"
                    "  python -m playwright install chromium"
                )
            with sync_playwright() as p:
                self.browser = p.chromium.launch(headless=True)
                years = self.write_year_files(by_year_month)
                self.browser.close()
                self.browser = None
        else:
            years = self.write_year_files(by_year_month)

        self.write_appendix_files(own_comments, other_comments)
        self.write_main_tex(years)
        return {
            "posts_json": posts_json,
            "own_comment_count": len(own_comments),
            "other_comment_count": len(other_comments),
            "output_dir": self.output_dir,
            "main_tex": self.output_dir / self.main_tex_name,
            "years": years,
        }


def parse_args():
    parser = argparse.ArgumentParser(
        description="Facebookアーカイブを書籍風LaTeX日記に変換します。"
    )
    parser.add_argument("archive_root", help="Facebookアーカイブを展開したフォルダ")
    parser.add_argument(
        "-o", "--output-dir",
        default=DEFAULT_OUTPUT_DIR,
        help=f"出力先フォルダ。省略時は {DEFAULT_OUTPUT_DIR}",
    )
    parser.add_argument(
        "--main-tex",
        default=DEFAULT_MAIN_TEX,
        help=f"メインTeXファイル名。省略時は {DEFAULT_MAIN_TEX}",
    )
    parser.add_argument(
        "--capture-links",
        action="store_true",
        help="外部リンクのWebページをキャプチャします。YouTubeは対象外です。",
    )
    parser.add_argument(
        "--capture-youtube",
        action="store_true",
        help="YouTubeリンクのサムネイル画像を取得します。",
    )
    parser.add_argument(
        "--copy-videos",
        action="store_true",
        help="将来用オプションです。現在は未実装です。",
    )
    parser.add_argument(
        "--dedupe-scope",
        choices=("none", "consecutive", "month", "year"),
        default="consecutive",
        help=(
            "重複投稿の省略範囲。"
            "none=省略しない, "
            "consecutive=直前と同じなら省略, "
            "month=同じ月で出力済みなら省略, "
            "year=同じ年で出力済みなら省略"
        ),
    )
    return parser.parse_args()


def main():
    args = parse_args()
    builder = FacebookDiaryBuilder(
        archive_root=args.archive_root,
        output_dir=args.output_dir,
        main_tex_name=args.main_tex,
        capture_links=args.capture_links,
        capture_youtube=args.capture_youtube,
        copy_videos=args.copy_videos,
        dedupe_scope=args.dedupe_scope,
    )
    info = builder.build()

    print(f"投稿JSON: {info['posts_json']}")
    print(f"自分の投稿へのコメント: {info['own_comment_count']} 件")
    print(f"他人へのコメント: {info['other_comment_count']} 件")
    print(f"作成フォルダ: {info['output_dir']}")
    print(f"メインTeX: {info['main_tex']}")
    print("年別ファイル:", ", ".join(f"year{y}.tex" for y in info["years"]))
    print("画像コピー先: pictures/YYYY/MM/")
    if args.capture_links:
        print("リンク画像コピー先: pictures/links/YYYY/MM/")
    if args.capture_youtube:
        print("YouTubeサムネイルコピー先: pictures/youtube/YYYY/MM/")
    print("付録ファイル: appendix_own_comments.tex, appendix_other_comments.tex")
    print()
    print("全体PDF作成例:")
    print(f"  cd {info['output_dir']}")
    print(f"  uplatex {args.main_tex}")
    print(f"  dvipdfmx {Path(args.main_tex).with_suffix('.dvi')}")
    print()
    print("年別PDF作成例:")
    print("  uplatex year2024.tex")
    print("  dvipdfmx year2024.dvi")


if __name__ == "__main__":
    main()
