from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime
from typing import Any, Literal, Optional


PostType = Literal["post", "comment"]

MediaType = Literal[
    "photo",
    "youtube",
    "link",
    "generated",
    "video",
    "audio",
    "pdf",
    "unknown",
]


@dataclass
class GeneratorInfo:
    """Diary Packageを生成したアプリケーションの情報。"""

    application: str
    version: str


@dataclass
class SourceInfo:
    """
    投稿の由来。

    system:
        facebook / myDiary / instagram など。

    id:
        元システム側の識別子。SQLiteの内部IDとは無関係。
    """

    system: str
    id: Optional[str] = None


@dataclass
class Media:
    """
    投稿に添付されるメディア。

    path:
        Diary Packageルートからの相対パス。

    source_url:
        YouTubeや一般Webページの元URL。通常写真の場合はNone。

    display_path / thumbnail_path:
        あらかじめ生成済みの場合だけ指定する。
        無い場合、myDiary側が必要に応じて生成できる。
    """

    id: str
    type: MediaType

    path: Optional[str] = None
    display_path: Optional[str] = None
    thumbnail_path: Optional[str] = None
    source_url: Optional[str] = None

    original_extension: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    caption: Optional[str] = None

    sort_order: int = 0


@dataclass
class PostLink:
    """
    Diary Package内の別投稿へのリンク。

    target:
        リンク先投稿のPost.id。SQLiteの内部IDではない。
    """

    target: str
    sort_order: int = 0


@dataclass
class Post:
    """Diary Package Version 1の投稿。"""

    id: str
    type: PostType

    title: Optional[str]
    body: str

    created_at: datetime
    updated_at: datetime
    diary_date: datetime

    is_favorite: bool = False

    # コメントの親投稿
    # 親投稿を特定できない場合は None
    parent_post_id: Optional[str] = None

    media: list[Media] = field(default_factory=list)
    links: list[PostLink] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)

    source: Optional[SourceInfo] = None


@dataclass
class DiaryPackage:
    """
    myDiary Import / Export用の標準パッケージ。

    Version 1:
        format
        version
        generator
        title
        created_at
        posts
    """

    format: str = "myDiary"
    version: int = 1

    generator: GeneratorInfo = field(
        default_factory=lambda: GeneratorInfo(
            application="facebook2tex",
            version="2.0",
        )
    )

    title: str = "Diary"
    created_at: datetime = field(default_factory=datetime.now)

    posts: list[Post] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """JSONへ書き出せる辞書へ変換する。"""

        return _convert_for_json(self)


def _convert_for_json(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()

    if is_dataclass(value):
        return {
            key: _convert_for_json(item)
            for key, item in asdict(value).items()
        }

    if isinstance(value, list):
        return [_convert_for_json(item) for item in value]

    if isinstance(value, tuple):
        return [_convert_for_json(item) for item in value]

    if isinstance(value, dict):
        return {
            key: _convert_for_json(item)
            for key, item in value.items()
        }

    return value
