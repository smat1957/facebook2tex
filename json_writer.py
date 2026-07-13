import json
from pathlib import Path


class JsonWriter:
    """
    Diary Model を JSON ファイルへ出力する Writer。

    Reader や Facebook JSON の構造は知らない。
    diary.to_dict() で得られる整理済みデータだけを書き出す。
    """

    def __init__(self, output_file):
        self.output_file = Path(output_file).expanduser().resolve()

    def write(self, diary):
        """
        Diary Model を JSON として保存する。
        """
        self.output_file.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        with self.output_file.open("w", encoding="utf-8") as f:
            json.dump(
                diary.to_dict(),
                f,
                ensure_ascii=False,
                indent=2,
            )

        return self.output_file