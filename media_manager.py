from __future__ import annotations

import html
import re
import shutil
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

from mydiary_model import DiaryPackage, Media
from utils import get_youtube_video_id, sha1_short

SKIP_CAPTURE_DOMAINS = {
    "facebook.com", "fb.watch", "fb.me", "messenger.com",
    "instagram.com", "threads.net", "x.com", "twitter.com",
    "asahi.com", "sankei.com", "yomiuri.co.jp", "fujitv.co.jp",
    "jst.go.jp", "ehgdae.ru", "lamoncloa.gob.es", "fnn.jp",
    "kyoto.travel",
}

class MediaManager:
    """
    DiaryPackage内のMediaについて、実体ファイルを生成・保存する。

    photo:
        FacebookReaderがすでにPackageへコピー済みなので何もしない。

    youtube:
        YouTubeサムネイルを取得し、
        pictures/youtube/YYYY/MM/ 以下へ保存する。

    link:
        1. WebページのOGP画像を取得
        2. 取得できなければPlaywrightでページをキャプチャ
        3. pictures/links/YYYY/MM/ 以下へ保存する。

    取得成功時:
        Media.path にDiary Packageルートからの相対パスを設定する。

    取得失敗時:
        Media.path はNoneのままとする。

    myDiary側はネットワークへアクセスせず、
    pathが存在するMediaだけをPackageからコピーする。
    """

    USER_AGENT = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0 Safari/537.36"
    )

    def __init__(
        self,
        package_root,
        *,
        capture_link_fallback: bool = True,
        timeout: int = 15,
    ):
        self.package_root = (
            Path(package_root)
            .expanduser()
            .resolve()
        )

        self.pictures_root = (
            self.package_root / "pictures"
        )

        self.capture_link_fallback = (
            capture_link_fallback
        )

        self.timeout = timeout

    # --------------------------------------------------------------
    # Public API
    # --------------------------------------------------------------

    def materialize(
        self,
        package: DiaryPackage,
    ) -> None:
        """
        Package内の全Mediaを走査し、
        必要な実体ファイルを生成する。
        """

        youtube_count = 0
        link_count = 0
        failed_count = 0

        browser = None
        playwright = None

        try:
            for post in package.posts:

                for media in sorted(
                    post.media,
                    key=lambda item: item.sort_order,
                ):

                    # Readerがすでに実体を作成済み
                    if media.path:
                        continue

                    try:
                        if media.type == "youtube":

                            if self.materialize_youtube(
                                media,
                                post.diary_date,
                            ):
                                youtube_count += 1
                            else:
                                failed_count += 1

                        elif media.type == "link":

                            # まずOGP画像を試す
                            if self.materialize_link_ogp(
                                media,
                                post.diary_date,
                            ):
                                link_count += 1
                                continue

                            # ★ ここで除外判定
                            if self.is_skip_capture_domain(
                                    media.source_url
                            ):
                                print(
                                    "取得除外:",
                                    media.source_url,
                                )
                                continue

                            # OGPが無ければPlaywright
                            if not self.capture_link_fallback:
                                failed_count += 1
                                continue

                            if browser is None:
                                (
                                    playwright,
                                    browser,
                                ) = self.start_browser()

                            if self.materialize_link_capture(
                                media,
                                post.diary_date,
                                browser,
                            ):
                                link_count += 1
                            else:
                                failed_count += 1

                    except Exception as error:
                        print(
                            "メディア取得失敗:",
                            media.id,
                            error,
                        )
                        failed_count += 1

        finally:
            if browser is not None:
                browser.close()

            if playwright is not None:
                playwright.stop()

        print()
        print("MediaManager 完了")
        print(
            f"YouTubeサムネイル: "
            f"{youtube_count}"
        )
        print(
            f"リンク画像: "
            f"{link_count}"
        )
        print(
            f"取得失敗: "
            f"{failed_count}"
        )

    # --------------------------------------------------------------
    # YouTube
    # --------------------------------------------------------------

    def materialize_youtube(
        self,
        media: Media,
        date,
    ) -> bool:

        if not media.source_url:
            return False

        video_id = get_youtube_video_id(
            media.source_url
        )

        if not video_id:
            return False

        relative_directory = (
            Path("pictures")
            / "youtube"
            / f"{date.year:04d}"
            / f"{date.month:02d}"
        )

        filename = (
            f"{date:%Y%m%d_%H%M%S}_"
            f"{video_id}_"
            f"{sha1_short(media.source_url, 8)}"
            ".jpg"
        )

        relative_path = (
            relative_directory / filename
        )

        destination = (
            self.package_root / relative_path
        )

        destination.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        # 既に存在する場合は再取得しない
        if destination.exists():
            media.path = relative_path.as_posix()
            media.original_extension = "jpg"
            return True

        candidates = [
            (
                "https://img.youtube.com/"
                f"vi/{video_id}/maxresdefault.jpg"
            ),
            (
                "https://img.youtube.com/"
                f"vi/{video_id}/hqdefault.jpg"
            ),
        ]

        for url in candidates:
            try:
                data, content_type = (
                    self.download_binary(url)
                )

                if not self.looks_like_image(
                    data,
                    content_type,
                ):
                    continue

                # maxresdefaultが存在しない場合、
                # 小さな代替画像が返ることがある
                if len(data) < 1000:
                    continue

                destination.write_bytes(data)

                media.path = (
                    relative_path.as_posix()
                )

                media.original_extension = "jpg"

                print(
                    "YouTube:",
                    media.source_url,
                )

                return True

            except Exception:
                continue

        print(
            "YouTube取得失敗:",
            media.source_url,
        )

        return False

    # --------------------------------------------------------------
    # Link: OGP
    # --------------------------------------------------------------

    def materialize_link_ogp(
        self,
        media: Media,
        date,
    ) -> bool:

        if not media.source_url:
            return False

        page_url = media.source_url

        try:
            page_data, _ = self.download_binary(
                page_url
            )

            page_html = page_data.decode(
                "utf-8",
                errors="replace",
            )

            image_url = self.find_og_image(
                page_html,
                page_url,
            )

            if not image_url:
                return False

            image_data, content_type = (
                self.download_binary(image_url)
            )

            if not self.looks_like_image(
                image_data,
                content_type,
            ):
                return False

            extension = (
                self.extension_from_content_type(
                    content_type
                )
                or self.extension_from_url(
                    image_url
                )
                or "jpg"
            )

            relative_path = (
                self.make_link_relative_path(
                    media,
                    date,
                    extension,
                    suffix="ogp",
                )
            )

            destination = (
                self.package_root
                / relative_path
            )

            destination.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            destination.write_bytes(
                image_data
            )

            media.path = (
                relative_path.as_posix()
            )

            media.original_extension = (
                extension
            )

            print(
                "Link OGP:",
                page_url,
            )

            return True

        except Exception as error:
            print(
                "OGP取得失敗:",
                page_url,
                error,
            )

            return False

    # --------------------------------------------------------------
    # Link: Playwright screenshot
    # --------------------------------------------------------------

    @staticmethod
    def start_browser():

        try:
            from playwright.sync_api import (
                sync_playwright,
            )
        except ImportError as error:
            raise RuntimeError(
                "Playwrightがインストールされていません。\n"
                "pip install playwright\n"
                "playwright install chromium"
            ) from error

        playwright = sync_playwright().start()

        browser = playwright.chromium.launch(
            headless=True
        )

        return playwright, browser

    def materialize_link_capture(
        self,
        media: Media,
        date,
        browser,
    ) -> bool:

        if not media.source_url:
            return False

        relative_path = (
            self.make_link_relative_path(
                media,
                date,
                "png",
                suffix="capture",
            )
        )

        destination = (
            self.package_root
            / relative_path
        )

        destination.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        page = browser.new_page(
            viewport={
                "width": 1280,
                "height": 900,
            }
        )

        try:
            page.goto(
                media.source_url,
                wait_until="domcontentloaded",
                timeout=self.timeout * 1000,
            )

            # ページが少し描画されるのを待つ
            page.wait_for_timeout(1500)

            page.screenshot(
                path=str(destination),
                full_page=False,
            )

            media.path = (
                relative_path.as_posix()
            )

            media.original_extension = "png"

            print(
                "Link Capture:",
                media.source_url,
            )

            return True

        except Exception as error:
            print(
                "Capture失敗:",
                media.source_url,
                error,
            )

            if destination.exists():
                destination.unlink()

            return False

        finally:
            page.close()

    # --------------------------------------------------------------
    # OGP parsing
    # --------------------------------------------------------------

    @staticmethod
    def find_og_image(
        page_html: str,
        page_url: str,
    ) -> str | None:

        patterns = [
            r'''
            <meta
            [^>]+
            property=["']og:image["']
            [^>]+
            content=["']([^"']+)["']
            ''',

            r'''
            <meta
            [^>]+
            content=["']([^"']+)["']
            [^>]+
            property=["']og:image["']
            ''',

            r'''
            <meta
            [^>]+
            name=["']twitter:image["']
            [^>]+
            content=["']([^"']+)["']
            ''',

            r'''
            <meta
            [^>]+
            content=["']([^"']+)["']
            [^>]+
            name=["']twitter:image["']
            ''',
        ]

        for pattern in patterns:
            match = re.search(
                pattern,
                page_html,
                flags=(
                    re.IGNORECASE
                    | re.VERBOSE
                ),
            )

            if not match:
                continue

            image_url = html.unescape(
                match.group(1)
            ).strip()

            if not image_url:
                continue

            # 相対URLを正しく絶対URLへ変換する。
            # 単純な baseURL + imageURL は行わない。
            return urljoin(
                page_url,
                image_url,
            )

        return None

    # --------------------------------------------------------------
    # Download
    # --------------------------------------------------------------

    def download_binary(
        self,
        url: str,
    ) -> tuple[bytes, str]:

        request = Request(
            url,
            headers={
                "User-Agent": self.USER_AGENT,
                "Accept": (
                    "text/html,"
                    "application/xhtml+xml,"
                    "image/avif,"
                    "image/webp,"
                    "image/apng,"
                    "image/*,*/*;q=0.8"
                ),
            },
        )

        with urlopen(
            request,
            timeout=self.timeout,
        ) as response:

            data = response.read()

            content_type = (
                response.headers
                .get_content_type()
            )

            return data, content_type

    # --------------------------------------------------------------
    # Paths
    # --------------------------------------------------------------

    def make_link_relative_path(
        self,
        media: Media,
        date,
        extension: str,
        *,
        suffix: str,
    ) -> Path:

        relative_directory = (
            Path("pictures")
            / "links"
            / f"{date.year:04d}"
            / f"{date.month:02d}"
        )

        url_hash = sha1_short(
            media.source_url or media.id,
            10,
        )

        filename = (
            f"{date:%Y%m%d_%H%M%S}_"
            f"{suffix}_"
            f"{url_hash}."
            f"{extension}"
        )

        return (
            relative_directory
            / filename
        )

    # --------------------------------------------------------------
    # Image helpers
    # --------------------------------------------------------------

    @staticmethod
    def looks_like_image(
        data: bytes,
        content_type: str,
    ) -> bool:

        if not data:
            return False

        if content_type.startswith("image/"):
            return True

        signatures = (
            b"\xff\xd8\xff",       # JPEG
            b"\x89PNG\r\n\x1a\n", # PNG
            b"GIF87a",
            b"GIF89a",
            b"RIFF",               # WebP候補
        )

        return any(
            data.startswith(signature)
            for signature in signatures
        )

    @staticmethod
    def extension_from_content_type(
        content_type: str,
    ) -> str | None:

        mapping = {
            "image/jpeg": "jpg",
            "image/png": "png",
            "image/webp": "webp",
            "image/gif": "gif",
        }

        return mapping.get(
            content_type.lower()
        )

    @staticmethod
    def extension_from_url(
        url: str,
    ) -> str | None:

        suffix = (
            Path(
                urlparse(url).path
            )
            .suffix
            .lower()
            .lstrip(".")
        )

        if suffix in {
            "jpg",
            "jpeg",
            "png",
            "webp",
            "gif",
        }:
            return (
                "jpg"
                if suffix == "jpeg"
                else suffix
            )

        return None

    @staticmethod
    def is_skip_capture_domain(url: str) -> bool:
        try:
            host = (urlparse(url).hostname or "").lower()

            for domain in SKIP_CAPTURE_DOMAINS:
                if host == domain or host.endswith("." + domain):
                    return True

            return False

        except Exception:
            return True