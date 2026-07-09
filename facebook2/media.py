from pathlib import Path
import shutil

from .model import Media
from .utils import source_path_from_uri


class MediaManager:
    """
    Media の実体ファイルを管理する。

    Reader は original_uri だけ設定する。
    Writer が必要になった時点で ensure_entry_media() を呼び、
    pictures/YYYY/MM/ 以下へコピーする。
    """

    def __init__(self, archive_root, output_dir):
        self.archive_root = Path(archive_root).expanduser().resolve()
        self.output_dir = Path(output_dir).expanduser().resolve()
        self.activity_dir = self.archive_root / "your_facebook_activity"

    def ensure_entry_media(self, entry):
        for media in entry.media:
            self.ensure_media(media, entry.datetime)

    def ensure_media(self, media: Media, dt):
        if media.path:
            return

        if media.kind == "image":
            media.path = self.copy_image(media.original_uri, dt)

    def copy_image(self, uri, dt):
        year = f"{dt.year:04d}"
        month = f"{dt.month:02d}"

        src = source_path_from_uri(uri, self.archive_root, self.activity_dir)

        dest_dir = self.output_dir / "pictures" / year / month
        dest_dir.mkdir(parents=True, exist_ok=True)

        dest = dest_dir / src.name

        if not dest.exists():
            shutil.copy2(src, dest)

        return str(Path("pictures") / year / month / src.name)