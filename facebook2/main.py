import argparse

from .reader import FacebookReader
from .json_writer import JsonWriter

def parse_args():
    parser = argparse.ArgumentParser(
        description="Facebookバックアップから Diary Model を作成します。"
    )

    parser.add_argument(
        "archive_root",
        help="Facebookアーカイブを展開したフォルダ",
    )

    parser.add_argument(
        "--format",
        choices=("summary", "json"),
        default="summary",
        help="出力形式。summary=概要表示, json=Diary ModelをJSON出力",
    )

    parser.add_argument(
        "-o",
        "--output",
        default="facebook_diary.json",
        help="JSON出力ファイル名",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    diary = FacebookReader(args.archive_root).read()
    if args.format == "json":
        output_file = JsonWriter(args.output).write(diary)
        print(f"JSONを書き出しました: {output_file}")
        return

    print("Diary Model を作成しました。")
    print(f"title: {diary.title}")
    print(f"years: {len(diary.years)}")
    print(f"own_comments: {len(diary.own_comments)}")
    print(f"other_comments: {len(diary.other_comments)}")

    for year in diary.years:
        entry_count = sum(len(month.entries) for month in year.months)
        print(f"{year.year}: {entry_count} entries")


if __name__ == "__main__":
    main()