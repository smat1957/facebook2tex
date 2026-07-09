from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Literal, Optional


@dataclass
class Media:
    kind: Literal["image", "video", "unknown"]
    original_uri: str
    path: Optional[str] = None


@dataclass
class Link:
    url: str
    kind: Literal["web", "youtube"]
    youtube_id: Optional[str] = None
    thumbnail: Optional[str] = None
    capture: Optional[str] = None


@dataclass
class Entry:
    id: str
    datetime: datetime
    kind: Literal["post", "own_comment", "other_comment"]
    texts: list[str] = field(default_factory=list)
    links: list[Link] = field(default_factory=list)
    media: list[Media] = field(default_factory=list)
    source_id: Optional[str] = None


@dataclass
class Month:
    year: int
    month: int
    entries: list[Entry] = field(default_factory=list)


@dataclass
class Year:
    year: int
    months: list[Month] = field(default_factory=list)


@dataclass
class Diary:
    title: str = "Facebook日記"
    format: str = "facebook2tex-diary"
    version: str = "2.0"
    years: list[Year] = field(default_factory=list)
    own_comments: list[Entry] = field(default_factory=list)
    other_comments: list[Entry] = field(default_factory=list)

    def to_dict(self):
        def convert(obj):
            if isinstance(obj, datetime):
                return obj.isoformat()
            if hasattr(obj, "__dataclass_fields__"):
                return {k: convert(v) for k, v in asdict(obj).items()}
            if isinstance(obj, list):
                return [convert(x) for x in obj]
            if isinstance(obj, dict):
                return {k: convert(v) for k, v in obj.items()}
            return obj

        return convert(self)