import json
from pathlib import Path

from .model import Diary, Entry, Link, Media, Month, Year
from .utils import (
    dt_from_ts,
    find_external_links,
    find_media_uris,
    find_text_links,
    find_texts,
    fix_facebook_text,
    get_youtube_video_id,
    normalize_url_for_dedupe,
    sha1_short,
)



class FacebookReader:
    """
    Facebookバックアップを読み込み、Diary Model を構築する。

    Reader は TeX / JSON / Markdown などの出力形式を知らない。
    Facebook JSON から Diary / Entry / Link / Media を作るだけ。
    """

    def __init__(self, archive_root):
        self.archive_root = Path(archive_root).expanduser().resolve()
        self.activity_dir = self.archive_root / "your_facebook_activity"

    def read(self):
        if not self.activity_dir.exists():
            raise FileNotFoundError(f"見つかりません: {self.activity_dir}")

        diary = Diary()

        posts_json = self.find_posts_json()
        posts = self.load_json(posts_json)
        posts = self.remove_duplicate_posts(posts)

        self.build_posts(diary, posts)
        self.read_comments(diary)

        return diary

    def find_posts_json(self):
        posts_dir = self.activity_dir / "posts"

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
        p = self.activity_dir / "comments_and_reactions" / "comments.json"
        return p if p.exists() else None

    @staticmethod
    def load_json(path):
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)

    def build_posts(self, diary, posts):
        years = {}

        for post in sorted(posts, key=lambda p: p.get("timestamp", 0)):
            entry = self.build_entry(post)
            if entry is None:
                continue

            dt = entry.datetime

            if dt.year not in years:
                years[dt.year] = Year(year=dt.year)

            year = years[dt.year]
            month = self.find_or_create_month(year, dt.month)
            month.entries.append(entry)

        diary.years = [years[y] for y in sorted(years)]

    @staticmethod
    def find_or_create_month(year: Year, month_number: int):
        for month in year.months:
            if month.month == month_number:
                return month

        month = Month(year=year.year, month=month_number)
        year.months.append(month)
        return month

    def build_entry(self, post):
        ts = post.get("timestamp")
        if not ts:
            return None

        dt = dt_from_ts(ts)

        texts = find_texts(post)
        text_links = find_text_links(texts)
        external_links = find_external_links(post)

        text_link_keys = {
            normalize_url_for_dedupe(url)
            for url in text_links
        }

        extra_links = [
            url
            for url in external_links
            if normalize_url_for_dedupe(url) not in text_link_keys
        ]

        links = []
        seen = set()

        for url in text_links + extra_links:
            key = normalize_url_for_dedupe(url)
            if key in seen:
                continue
            seen.add(key)

            youtube_id = get_youtube_video_id(url)

            if youtube_id:
                links.append(
                    Link(
                        url=url,
                        kind="youtube",
                        youtube_id=youtube_id,
                    )
                )
            else:
                links.append(
                    Link(
                        url=url,
                        kind="web",
                    )
                )

        media = [
            Media(
                kind="image",
                original_uri=uri,
            )
            for uri in find_media_uris(
                post,
                self.archive_root,
                self.activity_dir,
            )
        ]

        if not texts and not links and not media:
            return None

        return Entry(
            id=self.make_entry_id(post),
            datetime=dt,
            kind="post",
            texts=texts,
            links=links,
            media=media,
            source_id=str(post.get("timestamp", "")),
        )

    def make_entry_id(self, post):
        ts = post.get("timestamp", 0)
        links = self.post_links_for_dedupe(post)
        base = f"{ts}-{'|'.join(links)}"
        dt = dt_from_ts(ts)
        return dt.strftime("%Y%m%d-%H%M%S-") + sha1_short(base, 8)

    def post_links_for_dedupe(self, post):
        texts = find_texts(post)
        links = find_text_links(texts) + find_external_links(post)

        keys = set()
        for url in links:
            key = normalize_url_for_dedupe(url)
            if key:
                keys.add(key)

        return tuple(sorted(keys))

    def count_media(self, post):
        return len(
            find_media_uris(
                post,
                self.archive_root,
                self.activity_dir,
            )
        )

    def remove_duplicate_posts(self, posts):
        """
        Version1 と同じ方針:
        リンクだけ投稿のリンクが、近い後続の本文付き投稿に含まれる場合、
        リンクだけ投稿を捨てる。
        """
        posts = sorted(posts, key=lambda p: p.get("timestamp", 0))
        kept = []

        for post in posts:
            texts = find_texts(post)
            links = self.post_links_for_dedupe(post)
            media_count = self.count_media(post)

            text_len = sum(len(t.strip()) for t in texts)
            is_link_only = (text_len == 0 and media_count == 0 and links)

            if is_link_only:
                duplicated = False
                post_ts = post.get("timestamp", 0)

                for other in posts:
                    if other is post:
                        continue

                    other_ts = other.get("timestamp", 0)

                    if other_ts < post_ts:
                        continue

                    if other_ts - post_ts > 10 * 60:
                        continue

                    other_texts = find_texts(other)
                    other_text_len = sum(len(t.strip()) for t in other_texts)

                    if other_text_len == 0:
                        continue

                    other_links = self.post_links_for_dedupe(other)

                    if set(links).issubset(set(other_links)):
                        duplicated = True
                        break

                if duplicated:
                    continue

            kept.append(post)

        return kept

    # ------------------------------------------------------------
    # Comments
    # ------------------------------------------------------------

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

    def read_comments(self, diary):
        comments_json = self.find_comments_json()
        if not comments_json:
            return

        raw = self.load_json(comments_json)

        for item in self.iter_comment_items(raw):
            entry, title = self.build_comment_entry(item)
            if entry is None:
                continue
            #print("DEBUG:COMMENT TITLE:", title)
            if (
                    "自分の投稿" in title
                    or "自分の写真" in title
                    or "自分の動画" in title
            ):
                entry.kind = "own_comment"
                diary.own_comments.append(entry)
            else:
                entry.kind = "other_comment"
                diary.other_comments.append(entry)

        diary.own_comments.sort(key=lambda e: e.datetime)
        diary.other_comments.sort(key=lambda e: e.datetime)

    def build_comment_entry(self, item):
        ts = item.get("timestamp")
        if not ts:
            return None, ""

        dt = dt_from_ts(ts)
        title = fix_facebook_text(item.get("title", "")).strip()

        texts = []

        for d in item.get("data", []):
            c = d.get("comment")

            if isinstance(c, dict):
                value = c.get("comment", "")
                if value:
                    texts.append(
                        fix_facebook_text(value).strip()
                    )

            elif isinstance(c, str):
                texts.append(
                    fix_facebook_text(c).strip()
                )

        texts = [t for t in texts if t]

        if not texts:
            return None, title

        text_links = find_text_links(texts)

        links = []
        seen = set()

        for url in text_links:
            key = normalize_url_for_dedupe(url)
            if key in seen:
                continue
            seen.add(key)

            youtube_id = get_youtube_video_id(url)

            if youtube_id:
                links.append(
                    Link(
                        url=url,
                        kind="youtube",
                        youtube_id=youtube_id,
                    )
                )
            else:
                links.append(
                    Link(
                        url=url,
                        kind="web",
                    )
                )

        media = [
            Media(
                kind="image",
                original_uri=uri,
            )
            for uri in find_media_uris(
                item,
                self.archive_root,
                self.activity_dir,
            )
        ]

        entry = Entry(
            id=self.make_comment_id(item),
            datetime=dt,
            kind="own_comment",
            texts=texts,
            links=links,
            media=media,
            source_id=str(ts),
        )

        return entry, title

    def make_comment_id(self, item):
        ts = item.get("timestamp", 0)
        base = str(item)
        dt = dt_from_ts(ts)
        return dt.strftime("%Y%m%d-%H%M%S-comment-") + sha1_short(base, 8)