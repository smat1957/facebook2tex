import argparse
from pathlib import Path

from json_writer import JsonWriter
from media_manager import MediaManager
from mydiary_reader import FacebookReader


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Facebook Archiveから"
            "myDiary Diary Packageを生成します。"
        )
    )

    parser.add_argument(
        "archive_root",
        help="Facebookアーカイブのルートフォルダ",
    )

    parser.add_argument(
        "package_root",
        help="出力するDiary Packageフォルダ",
    )

    parser.add_argument(
        "--no-link-capture",
        action="store_true",
        help=(
            "OGP画像がないリンクについて"
            "画面キャプチャを行わない"
        ),
    )

    parser.add_argument(
        "--dedupe-scope",
        choices=(
            "none",
            "consecutive",
            "month",
            "year",
        ),
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

    package_root = Path(
        args.package_root
    ).expanduser().resolve()

    # 1. Facebook Archiveを読む。
    #    写真はこの段階でPackageへコピーされる。
    reader = FacebookReader(
        archive_root=args.archive_root,
        package_root=package_root,
        generator_version="3.0",
        dedupe_scope=args.dedupe_scope,
    )

    package = reader.read()

    ''' for debug
    target_id = "20241212-124644-098c6aad"

    matches = [
        post
        for post in package.posts
        if post.id == target_id
    ]

    print()
    print("DEBUG target id:", target_id)
    print("件数:", len(matches))

    for i, post in enumerate(matches):
        print(
            i,
            post.id,
            post.type,
            post.diary_date,
            post.source.id if post.source else None,
            repr(post.body[:100]),
        )
    '''

    # 2. YouTubeサムネイルと
    #    Link画像を取得する。
    media_manager = MediaManager(
        package_root=package_root,
        capture_link_fallback=(
            not args.no_link_capture
        ),
    )

    media_manager.materialize(package)

    # 3. pathが確定した後でJSONを書く。
    output_file = (
        package_root / "diary.json"
    )

    JsonWriter(
        output_file
    ).write(package)

    print()
    print(
        "Diary Packageを生成しました:"
    )
    print(package_root)


if __name__ == "__main__":
    main()