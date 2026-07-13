from __future__ import annotations

import json
import shutil
import re
from pathlib import Path
from typing import Iterable
from urllib.parse import unquote, urlparse

from mydiary_model import (
    DiaryPackage,
    GeneratorInfo,
    Media,
    Post,
    SourceInfo,
)
from utils import (
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
    Facebookバックアップを読み込み、
    myDiary標準のDiaryPackageを構築する。

    Facebook固有のJSON構造は、このReader内で吸収する。

    重複除去:
        none
        consecutive
        month
        year
    """

    def __init__(
        self,
        archive_root,
        package_root,
        *,
        title: str = "Facebook日記",
        generator_version: str = "3.0",
        dedupe_scope: str = "consecutive",
    ):
        self.archive_root = (
            Path(archive_root)
            .expanduser()
            .resolve()
        )

        self.activity_dir = (
            self.archive_root
            / "your_facebook_activity"
        )

        self.package_root = (
            Path(package_root)
            .expanduser()
            .resolve()
        )

        self.pictures_root = (
            self.package_root
            / "pictures"
        )

        self.title = title
        self.generator_version = (
            generator_version
        )

        if dedupe_scope not in {
            "none",
            "consecutive",
            "month",
            "year",
        }:
            raise ValueError(
                f"不正な dedupe_scope: "
                f"{dedupe_scope}"
            )

        self.dedupe_scope = (
            dedupe_scope
        )

    # --------------------------------------------------------------
    # Public API
    # --------------------------------------------------------------
    '''
    def read(self) -> DiaryPackage:

        if not self.activity_dir.exists():
            raise FileNotFoundError(
                "Facebookアーカイブが"
                "見つかりません: "
                f"{self.activity_dir}"
            )

        self.package_root.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.pictures_root.mkdir(
            parents=True,
            exist_ok=True,
        )

        package = DiaryPackage(
            title=self.title,
            generator=GeneratorInfo(
                application="facebook2tex",
                version=self.generator_version,
            ),
        )

        posts_json = self.find_posts_json()
        raw_posts = self.load_json(posts_json)

        print("raw_posts:", len(raw_posts))

        # Facebookアーカイブ固有の
        # 「リンクだけ投稿」の整理
        raw_posts = self.remove_duplicate_posts(
            raw_posts
        )

        print(
            "remove_duplicate_posts後:",
            len(raw_posts)
        )

        # ユーザー指定の
        # consecutive/month/year/none
        raw_posts = self.apply_dedupe_scope(
            raw_posts
        )

        ### debug
        target_timestamp = 1733975204
        raw_matches = []
        for i, item in enumerate(raw_posts):
            timestamp = item.get("timestamp")
            if timestamp == target_timestamp:
                raw_matches.append(
                    (i, item)
                )
        print()
        print(
            "DEBUG raw_posts timestamp:",
            target_timestamp,
            "件数 =",
            len(raw_matches),
        )
        for i, item in raw_matches:
            print()
            print("raw index:", i)
            print(item)
        ###

        print(
            "apply_dedupe_scope後:",
            len(raw_posts)
        )

        built_posts = self.build_posts(
            raw_posts
        )

        # -------------------------------------------------
        # DEBUG: build_posts直後の重複確認
        # -------------------------------------------------

        target_id = (
            "20241212-124644-098c6aad"
        )

        matches = [
            post
            for post in built_posts
            if post.id == target_id
        ]

        print()
        print(
            "DEBUG build_posts:",
            target_id,
            "件数 =",
            len(matches),
        )

        for i, post in enumerate(matches):
            print(
                i,
                post.id,
                post.type,
                post.source.id
                    if post.source
                    else None,
                repr(post.body[:100]),
            )

        package.posts.extend(
            built_posts
        )

        comments = self.read_comments()

        print(
            "comments:",
            len(comments)
        )

        package.posts.extend(
            comments
        )

        # 同一source.idのpostとown-commentを統合
        package.posts = (
            self.merge_same_source_posts_and_comments(
                package.posts
            )
        )

        # 同一URLで親候補が一意な
        # own-commentだけ紐付け
        self.assign_parent_posts_by_unique_url(
            package.posts
        )

        package.posts.sort(
            key=lambda post: (
                post.diary_date,
                post.created_at,
                post.id,
            )
        )

        return package

    '''
    def read(self) -> DiaryPackage:

        if not self.activity_dir.exists():
            raise FileNotFoundError(
                "Facebookアーカイブが"
                "見つかりません: "
                f"{self.activity_dir}"
            )

        self.package_root.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.pictures_root.mkdir(
            parents=True,
            exist_ok=True,
        )

        package = DiaryPackage(
            title=self.title,
            generator=GeneratorInfo(
                application="facebook2tex",
                version=self.generator_version,
            ),
        )

        posts_json = (
            self.find_posts_json()
        )

        raw_posts = (
            self.load_json(posts_json)
        )

        # Facebookアーカイブ固有の
        # 「リンクだけ投稿」の整理
        raw_posts = (
            self.remove_duplicate_posts(
                raw_posts
            )
        )

        # ユーザー指定の
        # consecutive/month/year/none
        raw_posts = (
            self.apply_dedupe_scope(
                raw_posts
            )
        )

        package.posts.extend(
            self.build_posts(raw_posts)
        )

        package.posts.extend(
            self.read_comments()
        )

        # 同一source.idのpostとown-commentを統合
        package.posts = self.merge_same_source_posts_and_comments(
            package.posts
        )

        # 同一URLで親候補が一意なown-commentだけ紐付け
        self.assign_parent_posts_by_unique_url(
            package.posts
        )

        package.posts.sort(
            key=lambda post: (
                post.diary_date,
                post.created_at,
                post.id,
            )
        )

        return package


    # --------------------------------------------------------------
    # Facebook input files
    # --------------------------------------------------------------

    def find_posts_json(self) -> Path:

        posts_dir = (
            self.activity_dir
            / "posts"
        )

        candidates = [
            posts_dir
            / (
                "your_posts__check_ins__"
                "photos_and_videos_1.json"
            ),

            posts_dir
            / "your_posts_1.json",
        ]

        for candidate in candidates:
            if candidate.exists():
                return candidate

        found = sorted(
            posts_dir.glob(
                "*posts*.json"
            )
        )

        if found:
            return found[0]

        raise FileNotFoundError(
            "投稿JSONが見つかりません。"
        )

    def find_comments_json(
        self
    ) -> Path | None:

        path = (
            self.activity_dir
            / "comments_and_reactions"
            / "comments.json"
        )

        if path.exists():
            return path

        return None

    @staticmethod
    def load_json(path: Path):

        with path.open(
            "r",
            encoding="utf-8",
        ) as file:
            return json.load(file)

    # --------------------------------------------------------------
    # Posts
    # --------------------------------------------------------------

    def build_posts(
        self,
        raw_posts: list[dict],
    ) -> list[Post]:

        result: list[Post] = []

        for raw_post in sorted(
            raw_posts,
            key=lambda item:
                item.get(
                    "timestamp",
                    0,
                ),
        ):

            post = self.build_post(
                raw_post
            )

            if post is not None:
                result.append(post)

        return result

    def build_post(
        self,
        raw_post: dict,
    ) -> Post | None:

        timestamp = (
            raw_post.get(
                "timestamp"
            )
        )

        if not timestamp:
            return None

        date = dt_from_ts(
            timestamp
        )

        package_id = (
            self.make_post_id(
                raw_post
            )
        )

        texts = [
            text.strip()
            for text
            in find_texts(raw_post)
            if text
            and text.strip()
        ]

        urls = self.collect_urls(
            raw_post,
            texts,
        )

        body = self.build_body(
            texts,
            urls,
        )

        media = self.build_media(
            item=raw_post,
            package_id=package_id,
            date=date,
            urls=urls,
        )

        if not body and not media:
            return None

        return Post(
            id=package_id,
            type="post",
            title=None,
            body=body,

            created_at=date,
            updated_at=date,
            diary_date=date,

            is_favorite=False,

            media=media,
            links=[],
            tags=[],

            source=SourceInfo(
                system="facebook",
                id=str(timestamp),
            ),
        )

    @staticmethod
    def build_body(
        texts: list[str],
        urls: list[str],
    ) -> str:
        """
        Facebook本文を
        myDiaryの単一bodyへ変換する。

        URLはMedia.source_urlにも
        保存されるが、
        本文中に元から存在するURLは
        そのまま本文に残す。
        """

        del urls

        return (
            "\n\n"
            .join(texts)
            .strip()
        )

    def collect_urls(
        self,
        item: dict,
        texts: list[str],
    ) -> list[str]:

        text_links = (
            find_text_links(texts)
        )

        external_links = (
            find_external_links(item)
        )

        result: list[str] = []
        seen: set[str] = set()

        for url in (
            text_links
            + external_links
        ):

            key = (
                normalize_url_for_dedupe(
                    url
                )
            )

            if (
                not key
                or key in seen
            ):
                continue

            seen.add(key)
            result.append(url)

        return result

    def build_media(
        self,
        *,
        item: dict,
        package_id: str,
        date,
        urls: list[str],
    ) -> list[Media]:

        result: list[Media] = []

        photo_uris = (
            find_media_uris(
                item,
                self.archive_root,
                self.activity_dir,
            )
        )

        for index, uri in enumerate(
            photo_uris
        ):

            result.append(
                self.copy_photo_to_package(
                    uri=uri,
                    package_id=package_id,
                    date=date,
                    sort_order=len(
                        result
                    ),
                    photo_index=index,
                )
            )

        for url in urls:

            youtube_id = (
                get_youtube_video_id(
                    url
                )
            )

            media_type = (
                "youtube"
                if youtube_id
                else "link"
            )

            result.append(
                Media(
                    id=self.make_media_id(
                        package_id=package_id,
                        source=url,
                        index=len(result),
                    ),

                    type=media_type,

                    path=None,

                    display_path=None,
                    thumbnail_path=None,

                    source_url=url,

                    original_extension=None,
                    width=None,
                    height=None,
                    caption=None,

                    sort_order=len(result),
                )
            )

        return result

    # --------------------------------------------------------------
    # Photo copying
    # --------------------------------------------------------------

    def copy_photo_to_package(
        self,
        *,
        uri: str,
        package_id: str,
        date,
        sort_order: int,
        photo_index: int,
    ) -> Media:

        source_path = (
            self.resolve_media_source(
                uri
            )
        )

        if not source_path.exists():
            raise FileNotFoundError(
                "画像ファイルが"
                "見つかりません: "
                f"{uri}\n"
                "解決先: "
                f"{source_path}"
            )

        extension = (
            source_path
            .suffix
            .lower()
            .lstrip(".")
            or "jpg"
        )

        relative_directory = (
            Path("pictures")
            / "photos"
            / f"{date.year:04d}"
            / f"{date.month:02d}"
        )

        filename = (
            f"{date:%Y%m%d_%H%M%S}_"
            f"{package_id[-8:]}_"
            f"{photo_index + 1:03d}."
            f"{extension}"
        )

        relative_path = (
            relative_directory
            / filename
        )

        destination_path = (
            self.package_root
            / relative_path
        )

        destination_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        if destination_path.exists():

            if not self.files_are_identical(
                source_path,
                destination_path,
            ):

                destination_path = (
                    self.make_unique_destination(
                        destination_path
                    )
                )

                relative_path = (
                    destination_path
                    .relative_to(
                        self.package_root
                    )
                )

        else:
            shutil.copy2(
                source_path,
                destination_path,
            )

        if not destination_path.exists():

            shutil.copy2(
                source_path,
                destination_path,
            )

        return Media(
            id=self.make_media_id(
                package_id=package_id,
                source=str(uri),
                index=sort_order,
            ),

            type="photo",

            path=(
                relative_path
                .as_posix()
            ),

            display_path=None,
            thumbnail_path=None,

            source_url=None,

            original_extension=(
                extension
            ),

            width=None,
            height=None,
            caption=None,

            sort_order=sort_order,
        )

    def resolve_media_source(
        self,
        uri: str,
    ) -> Path:

        decoded = unquote(
            str(uri)
        )

        parsed = urlparse(
            decoded
        )

        if (
            parsed.scheme
            == "file"
        ):

            candidate = Path(
                unquote(
                    parsed.path
                )
            )

            if candidate.exists():
                return (
                    candidate
                    .resolve()
                )

        raw_path = (
            Path(decoded)
            .expanduser()
        )

        candidates: list[Path] = []

        if raw_path.is_absolute():
            candidates.append(
                raw_path
            )

        candidates.extend(
            [
                self.archive_root
                / raw_path,

                self.activity_dir
                / raw_path,
            ]
        )

        for candidate in candidates:

            if candidate.exists():

                return (
                    candidate
                    .resolve()
                )

        return (
            self.archive_root
            / raw_path
        ).resolve()

    @staticmethod
    def files_are_identical(
        first: Path,
        second: Path,
    ) -> bool:

        if (
            not first.exists()
            or not second.exists()
        ):
            return False

        if (
            first.stat().st_size
            != second.stat().st_size
        ):
            return False

        with (
            first.open("rb") as left,
            second.open("rb") as right,
        ):

            while True:

                left_chunk = left.read(
                    1024 * 1024
                )

                right_chunk = right.read(
                    1024 * 1024
                )

                if (
                    left_chunk
                    != right_chunk
                ):
                    return False

                if not left_chunk:
                    return True

    @staticmethod
    def make_unique_destination(
        path: Path,
    ) -> Path:

        stem = path.stem
        suffix = path.suffix
        parent = path.parent

        counter = 2
        candidate = path

        while candidate.exists():

            candidate = (
                parent
                / (
                    f"{stem}_"
                    f"{counter}"
                    f"{suffix}"
                )
            )

            counter += 1

        return candidate

    # --------------------------------------------------------------
    # Stable IDs
    # --------------------------------------------------------------

    def make_post_id(
        self,
        raw_post: dict,
    ) -> str:

        timestamp = (
            raw_post.get(
                "timestamp",
                0,
            )
        )

        links = (
            self.post_links_for_dedupe(
                raw_post
            )
        )

        base = (
            f"{timestamp}-"
            f"{'|'.join(links)}"
        )

        date = dt_from_ts(
            timestamp
        )

        return (
            date.strftime(
                "%Y%m%d-%H%M%S-"
            )
            + sha1_short(
                base,
                8,
            )
        )

    @staticmethod
    def make_media_id(
        *,
        package_id: str,
        source: str,
        index: int,
    ) -> str:

        base = (
            f"{package_id}|"
            f"{source}|"
            f"{index}"
        )

        return (
            f"{package_id}"
            f"-media-"
            f"{sha1_short(base, 10)}"
        )

    # --------------------------------------------------------------
    # Duplicate post removal
    # --------------------------------------------------------------

    def post_links_for_dedupe(
        self,
        raw_post: dict,
    ) -> tuple[str, ...]:

        texts = (
            find_texts(
                raw_post
            )
        )

        links = (
            find_text_links(
                texts
            )
            + find_external_links(
                raw_post
            )
        )

        keys: set[str] = set()

        for url in links:

            key = (
                normalize_url_for_dedupe(
                    url
                )
            )

            if key:
                keys.add(key)

        return tuple(
            sorted(keys)
        )

    def count_media(
        self,
        raw_post: dict,
    ) -> int:

        return len(
            find_media_uris(
                raw_post,
                self.archive_root,
                self.activity_dir,
            )
        )

    def remove_duplicate_posts(
            self,
            raw_posts: list[dict],
    ) -> list[dict]:
        """
        Facebookアーカイブ固有の重複整理。

        1. 実質的に同一の投稿を除外する。
           Facebook内部の data 配列に含まれる
           空dictの個数などは無視する。

        2. リンクだけ投稿のリンクが、
           近い後続の本文付き投稿に含まれる場合に除外する。
        """

        raw_posts = sorted(
            raw_posts,
            key=lambda item:
            item.get(
                "timestamp",
                0,
            ),
        )

        # -------------------------------------------------
        # 第1段階
        # 実質的に同一のraw_postを除外
        # -------------------------------------------------

        unique_posts: list[dict] = []
        seen_keys: set[tuple] = set()

        for raw_post in raw_posts:

            key = self.raw_post_dedupe_key(
                raw_post
            )

            if key in seen_keys:
                print(
                    "同一raw_postを除外:",
                    raw_post.get(
                        "timestamp"
                    ),
                    key,
                )
                continue

            seen_keys.add(key)

            unique_posts.append(
                raw_post
            )

        # -------------------------------------------------
        # 第2段階
        # 既存の「近接リンク重複」除外
        # -------------------------------------------------

        kept: list[dict] = []

        for raw_post in unique_posts:

            texts = find_texts(
                raw_post
            )

            links = (
                self.post_links_for_dedupe(
                    raw_post
                )
            )

            media_count = (
                self.count_media(
                    raw_post
                )
            )

            text_length = sum(
                len(
                    text.strip()
                )
                for text in texts
            )

            is_link_only = (
                    text_length == 0
                    and media_count == 0
                    and bool(links)
            )

            if (
                    is_link_only
                    and self.has_nearby_duplicate(
                raw_post,
                unique_posts,
                links,
            )
            ):
                continue

            kept.append(
                raw_post
            )

        return kept

    def raw_post_dedupe_key(
            self,
            raw_post: dict,
    ) -> tuple:
        """
        Facebook内部のノイズを無視して、
        投稿の実質的な内容から重複判定キーを作る。

        data配列中の空dictの個数などは判定に使わない。
        """

        timestamp = raw_post.get(
            "timestamp",
            0,
        )

        texts = tuple(
            text.strip()
            for text in find_texts(
                raw_post
            )
            if text.strip()
        )

        links = tuple(
            sorted(
                self.post_links_for_dedupe(
                    raw_post
                )
            )
        )

        media_count = self.count_media(
            raw_post
        )

        return (
            timestamp,
            texts,
            links,
            media_count,
        )

    def has_nearby_duplicate(
        self,
        raw_post: dict,
        all_posts: Iterable[dict],
        links: tuple[str, ...],
    ) -> bool:

        post_timestamp = (
            raw_post.get(
                "timestamp",
                0,
            )
        )

        for other in all_posts:

            if other is raw_post:
                continue

            other_timestamp = (
                other.get(
                    "timestamp",
                    0,
                )
            )

            if (
                other_timestamp
                < post_timestamp
            ):
                continue

            if (
                other_timestamp
                - post_timestamp
                > 10 * 60
            ):
                continue

            other_texts = (
                find_texts(
                    other
                )
            )

            other_text_length = sum(
                len(
                    text.strip()
                )
                for text
                in other_texts
            )

            if (
                other_text_length
                == 0
            ):
                continue

            other_links = (
                self.post_links_for_dedupe(
                    other
                )
            )

            if (
                set(links)
                .issubset(
                    set(
                        other_links
                    )
                )
            ):
                return True

        return False

    # --------------------------------------------------------------
    # Dedupe scope
    # --------------------------------------------------------------

    def post_dedupe_key(
        self,
        post: dict,
    ) -> tuple:
        """
        投稿内容比較用キー。

        日時は比較に含めない。

        比較対象:
            本文
            画像URI
            本文に含まれない追加リンク
        """

        texts = (
            find_texts(
                post
            )
        )

        text_links = (
            find_text_links(
                texts
            )
        )

        external_links = (
            find_external_links(
                post
            )
        )

        text_link_keys = {
            normalize_url_for_dedupe(
                url
            )
            for url
            in text_links
        }

        extra_links = [
            url
            for url
            in external_links
            if (
                normalize_url_for_dedupe(
                    url
                )
                not in text_link_keys
            )
        ]

        media_uris = (
            find_media_uris(
                post,
                self.archive_root,
                self.activity_dir,
            )
        )

        return (
            tuple(texts),

            tuple(
                media_uris
            ),

            tuple(
                normalize_url_for_dedupe(
                    url
                )
                for url
                in extra_links
            ),
        )

    def apply_dedupe_scope(
        self,
        posts: list[dict],
    ) -> list[dict]:
        """
        dedupe_scopeに従って
        重複投稿を除去する。

        none:
            何も除去しない

        consecutive:
            直前に残した投稿と
            内容が同じなら除外

        month:
            同じ年月内で
            既に同じ内容があれば除外

        year:
            同じ年内で
            既に同じ内容があれば除外
        """

        posts = sorted(
            posts,
            key=lambda post:
                post.get(
                    "timestamp",
                    0,
                ),
        )

        if (
            self.dedupe_scope
            == "none"
        ):
            return posts

        result: list[dict] = []

        last_key = None

        month_keys: dict[
            tuple[int, int],
            set[tuple],
        ] = {}

        year_keys: dict[
            int,
            set[tuple],
        ] = {}

        for post in posts:

            timestamp = (
                post.get(
                    "timestamp"
                )
            )

            if not timestamp:
                continue

            date = dt_from_ts(
                timestamp
            )

            key = (
                self.post_dedupe_key(
                    post
                )
            )

            if (
                self.dedupe_scope
                == "consecutive"
            ):

                if (
                    key
                    == last_key
                ):
                    continue

                result.append(
                    post
                )

                last_key = key
                continue

            if (
                self.dedupe_scope
                == "month"
            ):

                scope = (
                    date.year,
                    date.month,
                )

                seen = (
                    month_keys
                    .setdefault(
                        scope,
                        set(),
                    )
                )

                if key in seen:
                    continue

                seen.add(key)

                result.append(
                    post
                )

                continue

            if (
                self.dedupe_scope
                == "year"
            ):

                seen = (
                    year_keys
                    .setdefault(
                        date.year,
                        set(),
                    )
                )

                if key in seen:
                    continue

                seen.add(key)

                result.append(
                    post
                )

                continue

        return result

    # --------------------------------------------------------------
    # Comments
    # --------------------------------------------------------------

    @staticmethod
    def iter_comment_items(
        raw
    ):

        if isinstance(
            raw,
            list,
        ):

            for item in raw:

                if isinstance(
                    item,
                    dict,
                ):
                    yield item

        elif isinstance(
            raw,
            dict,
        ):

            for value in (
                raw.values()
            ):

                if not isinstance(
                    value,
                    list,
                ):
                    continue

                for item in value:

                    if isinstance(
                        item,
                        dict,
                    ):
                        yield item

    def read_comments(
        self
    ) -> list[Post]:

        comments_json = (
            self.find_comments_json()
        )

        if comments_json is None:
            return []

        raw = (
            self.load_json(
                comments_json
            )
        )

        result: list[Post] = []

        for item in (
            self.iter_comment_items(
                raw
            )
        ):

            post = (
                self.build_comment_post(
                    item
                )
            )

            if post is not None:
                result.append(
                    post
                )

        return result

    def build_comment_post(
        self,
        item: dict,
    ) -> Post | None:

        timestamp = (
            item.get(
                "timestamp"
            )
        )

        if not timestamp:
            return None

        date = dt_from_ts(
            timestamp
        )

        title = (
            fix_facebook_text(
                item.get(
                    "title",
                    "",
                )
            )
            .strip()
        )

        texts: list[str] = []

        for data_item in (
            item.get(
                "data",
                [],
            )
        ):

            comment = (
                data_item.get(
                    "comment"
                )
            )

            if isinstance(
                comment,
                dict,
            ):

                value = (
                    comment.get(
                        "comment",
                        "",
                    )
                )

            elif isinstance(
                comment,
                str,
            ):

                value = comment

            else:
                value = ""

            value = (
                fix_facebook_text(
                    value
                )
                .strip()
            )

            if value:
                texts.append(
                    value
                )

        if not texts:
            return None

        own_comment = (
            "自分の投稿"
            in title

            or "自分の写真"
            in title

            or "自分の動画"
            in title
        )

        package_id = (
            self.make_comment_id(
                item
            )
        )

        urls = self.collect_urls(
            item,
            texts,
        )

        body = self.build_body(
            texts,
            urls,
        )

        media = self.build_media(
            item=item,
            package_id=package_id,
            date=date,
            urls=urls,
        )

        tags = [
            "facebook-comment",

            (
                "own-comment"
                if own_comment
                else "other-comment"
            ),
        ]

        return Post(
            id=package_id,
            type="comment",
            title=(
                title
                or None
            ),
            body=body,

            created_at=date,
            updated_at=date,
            diary_date=date,

            is_favorite=False,

            media=media,
            links=[],
            tags=tags,

            source=SourceInfo(
                system="facebook",
                id=str(timestamp),
            ),
        )

    def make_comment_id(
        self,
        item: dict,
    ) -> str:

        timestamp = (
            item.get(
                "timestamp",
                0,
            )
        )

        date = dt_from_ts(
            timestamp
        )

        base = json.dumps(
            item,
            ensure_ascii=False,
            sort_keys=True,
        )

        return (
            date.strftime(
                "%Y%m%d-%H%M%S-comment-"
            )
            + sha1_short(
                base,
                8,
            )
        )

    def merge_same_source_posts_and_comments(
            self,
            posts: list[Post],
    ) -> list[Post]:
        """
        同じFacebook source.idを持つ通常投稿とown-commentを統合する。

        統合対象:
            source.system == "facebook"
            source.id が同じ
            通常postが存在
            own-commentが存在

        通常postを残し、
        own-commentの本文・mediaを必要に応じて取り込む。
        """

        groups: dict[
            tuple[str, str],
            list[Post],
        ] = {}

        ungrouped: list[Post] = []

        for post in posts:

            if (
                    post.source is None
                    or not post.source.system
                    or not post.source.id
            ):
                ungrouped.append(post)
                continue

            key = (
                post.source.system,
                post.source.id,
            )

            groups.setdefault(
                key,
                [],
            ).append(post)

        result: list[Post] = []

        for group in groups.values():

            normal_posts = [
                post
                for post in group
                if post.type == "post"
            ]

            own_comments = [
                post
                for post in group
                if (
                        post.type == "comment"
                        and "own-comment" in post.tags
                )
            ]

            others = [
                post
                for post in group
                if (
                        post not in normal_posts
                        and post not in own_comments
                )
            ]

            # 統合条件を満たさない場合はそのまま残す
            if (
                    len(normal_posts) != 1
                    or not own_comments
            ):
                result.extend(group)
                continue

            base_post = normal_posts[0]

            for comment in own_comments:
                self.merge_comment_into_post(
                    base_post,
                    comment,
                )

            result.append(base_post)
            result.extend(others)

        result.extend(ungrouped)

        return result

    def merge_comment_into_post(
            self,
            post: Post,
            comment: Post,
    ) -> None:
        """
        own-commentの内容を通常postへ統合する。
        """

        post.body = self.merge_bodies(
            post.body,
            comment.body,
        )

        post.media = self.merge_media_lists(
            post.media,
            comment.media,
        )

        # 日時は元の通常投稿を維持する。
        # updated_atだけ新しい方へ寄せる。
        if comment.updated_at > post.updated_at:
            post.updated_at = comment.updated_at

    @staticmethod
    def merge_bodies(
            post_body: str,
            comment_body: str,
    ) -> str:

        post_body = (
                post_body
                or ""
        ).strip()

        comment_body = (
                comment_body
                or ""
        ).strip()

        if not post_body:
            return comment_body

        if not comment_body:
            return post_body

        if post_body == comment_body:
            return post_body

        if comment_body in post_body:
            return post_body

        if post_body in comment_body:
            return comment_body

        return (
                post_body
                + "\n\n"
                + comment_body
        )

    def merge_media_lists(
            self,
            first: list[Media],
            second: list[Media],
    ) -> list[Media]:

        result: list[Media] = []
        seen: set[tuple] = set()

        for media in first + second:

            key = self.media_merge_key(
                media
            )

            if key in seen:
                continue

            seen.add(key)

            media.sort_order = len(result)

            result.append(media)

        return result

    @staticmethod
    def media_merge_key(
            media: Media,
    ) -> tuple:

        if media.source_url:
            return (
                media.type,
                "url",
                normalize_url_for_dedupe(
                    media.source_url
                ),
            )

        if media.path:
            return (
                media.type,
                "path",
                media.path,
            )

        return (
            media.type,
            "id",
            media.id,
        )

    def assign_parent_posts_by_unique_url(
        self,
        posts: list[Post],
    ) -> None:
        """
        own-comment と通常投稿が同じURLを持ち、
        そのURLを持つ通常投稿が1件だけの場合に限り、
        comment.parent_post_id を設定する。

        曖昧な場合は何もしない。
        """

        # URL -> 通常投稿一覧
        post_by_url: dict[str, list[Post]] = {}

        # -------------------------------------------------
        # 通常投稿が持つURLの索引を作る
        # -------------------------------------------------

        for post in posts:

            if post.type != "post":
                continue

            for url in self.collect_post_urls(post):

                post_by_url.setdefault(
                    url,
                    []
                ).append(post)

        linked_count = 0
        ambiguous_count = 0
        unmatched_count = 0

        # -------------------------------------------------
        # own-comment のURLを通常投稿と照合
        # -------------------------------------------------

        for comment in posts:

            if (
                comment.type != "comment"
                or "own-comment" not in comment.tags
            ):
                continue

            # すでに親が設定されている場合は変更しない
            if comment.parent_post_id is not None:
                continue

            comment_urls = self.collect_post_urls(
                comment
            )

            candidate_posts: dict[str, Post] = {}

            for url in comment_urls:

                for candidate in post_by_url.get(
                    url,
                    []
                ):

                    # 自分自身は候補にしない
                    if candidate.id == comment.id:
                        continue

                    candidate_posts[
                        candidate.id
                    ] = candidate

            # 候補が1件だけなら確定
            if len(candidate_posts) == 1:

                parent = next(
                    iter(candidate_posts.values())
                )

                comment.parent_post_id = parent.id

                linked_count += 1

                print(
                    "コメント親投稿を設定:",
                    comment.id,
                    "->",
                    parent.id,
                )

            elif len(candidate_posts) > 1:

                ambiguous_count += 1

                print(
                    "コメント親投稿候補が複数:",
                    comment.id,
                    list(candidate_posts.keys()),
                )

            else:

                unmatched_count += 1

        print()
        print("コメント親投稿URL照合 完了")
        print(
            "親投稿設定:",
            linked_count
        )
        print(
            "候補複数:",
            ambiguous_count
        )
        print(
            "一致なし:",
            unmatched_count
        )

    def collect_post_urls(
            self,
            post: Post,
    ) -> set[str]:
        """
        Postが持つURLを正規化して返す。

        対象:
        - media.source_url
        - 本文中のURL
        """

        urls: set[str] = set()

        # -------------------------------------------------
        # Mediaのsource_url
        # -------------------------------------------------

        for media in post.media:

            if not media.source_url:
                continue

            normalized = (
                self.normalize_url_for_parent_match(
                    media.source_url
                )
            )

            if normalized:
                urls.add(normalized)

        # -------------------------------------------------
        # 本文中のURL
        # -------------------------------------------------

        for url in self.extract_urls_from_text(
                post.body
        ):

            normalized = (
                self.normalize_url_for_parent_match(
                    url
                )
            )

            if normalized:
                urls.add(normalized)

        return urls

    @staticmethod
    def extract_urls_from_text(
            text: str,
    ) -> list[str]:

        if not text:
            return []

        return re.findall(
            r'https?://[^\s<>"\']+',
            text,
        )

    @staticmethod
    def normalize_url_for_parent_match(
            url: str,
    ) -> str:

        if not url:
            return ""

        value = url.strip()

        # Facebookデータで末尾に付くことがある
        # 不要な ? や & を除去
        while (
                value.endswith("?")
                or value.endswith("&")
        ):
            value = value[:-1]

        return value
