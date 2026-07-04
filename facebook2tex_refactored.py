import argparse
import json
import re
import shutil
from collections import defaultdict
from datetime import datetime
from pathlib import Path

# ------------------------------------------------------------
# 設定
# ------------------------------------------------------------

IMAGE_EXTS = {".jpg", ".jpeg", ".png"}

# 投稿本文内に直接書かれた URL を拾う。
# TeX の } や日本語句読点などで URL を切る。
URL_RE = re.compile(r'https?://[^\s<>"\]\}）)。,、]+')

DEFAULT_OUTPUT_DIR = "facebook_diary"
DEFAULT_MAIN_TEX = "facebook_diary.tex"


# ------------------------------------------------------------
# 文字列・TeX 用エスケープ
# ------------------------------------------------------------

def fix_facebook_text(s):
    """
    Facebook アーカイブ中の文字列を補正する。

    古い Facebook JSON では UTF-8 文字列が latin1 的に見えることがあるため、
    可能なら再デコードする。
    """
    if not isinstance(s, str):
        return ""

    try:
        s = s.encode("latin1").decode("utf-8")
    except Exception:
        pass

    # 絵文字などに付く variation selector を削る。
    return s.replace("\ufe0f", "")


def escape_tex(s):
    """通常テキストを TeX 用にエスケープする。"""
    s = fix_facebook_text(s)

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


def escape_url_for_tex(url):
    r"""
    \\\url{...} の中に入れる URL を最低限エスケープする。

    通常の本文エスケープとは別に扱う。
    """
    url = fix_facebook_text(url).strip()
    url = url.replace("\\", r"\textbackslash{}")
    url = url.replace("%", r"\%")
    url = url.replace("#", r"\#")
    url = url.replace("{", r"\{")
    url = url.replace("}", r"\}")
    return url


def escape_tex_except_url(text):
    r"""
    本文中の URL だけ \\\url{...} にし、その他は通常の TeX エスケープを行う。
    """
    text = fix_facebook_text(text)
    result = []
    pos = 0

    for m in URL_RE.finditer(text):
        result.append(escape_tex(text[pos:m.start()]))
        result.append(r"\url{" + escape_url_for_tex(m.group(0)) + "}")
        pos = m.end()

    result.append(escape_tex(text[pos:]))
    return "".join(result)


def tex_paragraphs(s):
    """
    複数行テキストを TeX の段落列に変換する。
    空行は捨てる。
    """
    s = fix_facebook_text(s).strip()
    paras = []

    for p in s.split("\n"):
        p = p.strip()
        if p:
            paras.append(escape_tex_except_url(p))

    return "\n\n".join(paras)


# ------------------------------------------------------------
# Facebook アーカイブ探索
# ------------------------------------------------------------

def dt_from_ts(ts):
    """Facebook の UNIX timestamp を datetime に変換する。"""
    return datetime.fromtimestamp(ts)


def find_posts_json(archive_root):
    """投稿 JSON を探す。Facebook の出力名が複数あり得るため候補を順に見る。"""
    posts_dir = archive_root / "your_facebook_activity" / "posts"

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


def find_comments_json(archive_root):
    """コメント JSON があれば返す。無ければ None。"""
    p = (
        archive_root
        / "your_facebook_activity"
        / "comments_and_reactions"
        / "comments.json"
    )
    return p if p.exists() else None


def source_path_from_uri(uri, archive_root, activity_dir):
    """
    Facebook JSON 中の uri から実ファイルパスを作る。
    uri が your_facebook_activity/ から始まる場合と、相対パスの場合の両方に対応。
    """
    if uri.startswith("your_facebook_activity/"):
        return archive_root / uri
    return activity_dir / uri


# ------------------------------------------------------------
# 投稿本文・リンク・画像の抽出
# ------------------------------------------------------------

def collect_texts(post):
    """1投稿から本文らしい文字列を集め、重複を除いて返す。"""
    texts = []

    for item in post.get("data", []):
        for key in ("post", "text", "description", "comment"):
            value = item.get(key)
            if value:
                texts.append(fix_facebook_text(value).strip())

    for att in post.get("attachments", []):
        for item in att.get("data", []):
            for key in ("description", "text"):
                value = item.get(key)
                if value:
                    texts.append(fix_facebook_text(value).strip())

            ext = item.get("external_context", {})
            for key in ("description", "title"):
                value = ext.get(key)
                if value:
                    texts.append(fix_facebook_text(value).strip())

    result = []
    seen = set()

    for t in texts:
        if t and t not in seen:
            result.append(t)
            seen.add(t)

    return result


def collect_links(post):
    """1投稿から external_context の URL を集める。"""
    links = []

    def add(url):
        url = fix_facebook_text(url).strip()
        if url and url not in links:
            links.append(url)

    for att in post.get("attachments", []):
        for item in att.get("data", []):
            ext = item.get("external_context", {})
            add(ext.get("url", ""))

    return links


def collect_media(post, archive_root, activity_dir, output_dir):
    """
    投稿に含まれる画像を output_dir/pictures/YYYY/MM/ にコピーし、
    TeX から参照する相対パスを返す。

    生成後の TeX は Facebook アーカイブの元フォルダに依存しない。
    """
    media_files = []

    ts = post.get("timestamp")
    if not ts:
        return media_files

    dt = dt_from_ts(ts)
    year = f"{dt.year:04d}"
    month = f"{dt.month:02d}"
    prefix = dt.strftime("%Y%m%d_%H%M%S")

    dest_dir = output_dir / "pictures" / year / month
    dest_dir.mkdir(parents=True, exist_ok=True)

    found_uris = []

    def add_uri(uri):
        uri = fix_facebook_text(uri).strip()
        if not uri:
            return

        suffix = Path(uri).suffix.lower()
        if suffix not in IMAGE_EXTS:
            return

        src = source_path_from_uri(uri, archive_root, activity_dir)
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
            for x in obj:
                walk(x)

    walk(post)

    for i, uri in enumerate(found_uris, start=1):
        src = source_path_from_uri(uri, archive_root, activity_dir)
        suffix = src.suffix.lower()

        dest_name = f"{prefix}_{i:03d}{suffix}"
        dest = dest_dir / dest_name

        # 同じ投稿を再生成すると同じファイル名になる。
        # 既存ファイルがある場合はコピーを省く。
        if not dest.exists():
            shutil.copy2(src, dest)

        media_files.append(f"pictures/{year}/{month}/{dest_name}")

    return media_files


# ------------------------------------------------------------
# コメント抽出
# ------------------------------------------------------------

def iter_comment_items(raw):
    """comments.json の構造差を吸収して、コメント item を順に返す。"""
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


def extract_comment_record(item):
    """comments.json の1要素から、TeX出力に必要な情報だけを取り出す。"""
    ts = item.get("timestamp")
    title = fix_facebook_text(item.get("title", "")).strip()
    texts = []

    for d in item.get("data", []):
        c = d.get("comment")
        if isinstance(c, dict):
            value = c.get("comment", "")
            if value:
                texts.append(fix_facebook_text(value).strip())
        elif isinstance(c, str):
            texts.append(fix_facebook_text(c).strip())

    text = "\n\n".join(t for t in texts if t)

    if not ts or not text:
        return None

    return {
        "timestamp": ts,
        "datetime": dt_from_ts(ts),
        "title": title,
        "text": text,
    }


def load_comments(archive_root):
    """
    コメントを読み込み、
    - 自分の投稿へのコメント
    - 他人へのコメント
    に分けて返す。
    """
    comments_json = find_comments_json(archive_root)
    if not comments_json:
        return [], []

    with comments_json.open("r", encoding="utf-8") as f:
        raw = json.load(f)

    own_related = []
    other_related = []

    for item in iter_comment_items(raw):
        rec = extract_comment_record(item)
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


# ------------------------------------------------------------
# TeX 出力補助
# ------------------------------------------------------------

def write_subfile_header(out, main_tex_name):
    """yearXXXX.tex や appendix_*.tex の冒頭を書く。"""
    out.write(rf"\documentclass[{main_tex_name}]{{subfiles}}" + "\n\n")
    out.write(r"\begin{document}" + "\n\n")


def write_subfile_footer(out):
    """subfile の末尾を書く。"""
    out.write("\n" + r"\end{document}" + "\n")


def write_media_grid(out, media):
    """
    画像を横2枚ずつ並べる。
    奇数枚の場合、最後の1枚は中央配置にする。
    """
    if not media:
        return

    out.write(r"\paragraph{写真}" + "\n")

    for i in range(0, len(media), 2):
        pair = media[i:i + 2]
        out.write(r"\begin{center}" + "\n")

        if len(pair) == 2:
            for index, m in enumerate(pair):
                out.write(r"\begin{minipage}{0.48\linewidth}" + "\n")
                out.write(r"\centering" + "\n")
                out.write(rf"\includegraphics[width=\linewidth]{{{m}}}" + "\n")
                out.write(r"\end{minipage}" + "\n")
                if index == 0:
                    out.write(r"\hfill" + "\n")
        else:
            m = pair[0]
            out.write(r"\begin{minipage}{0.70\linewidth}" + "\n")
            out.write(r"\centering" + "\n")
            out.write(rf"\includegraphics[width=\linewidth]{{{m}}}" + "\n")
            out.write(r"\end{minipage}" + "\n")

        out.write(r"\end{center}" + "\n\n")


def write_post(out, post, archive_root, activity_dir, output_dir):
    """1投稿を TeX に出力する。"""
    ts = post.get("timestamp")
    if not ts:
        return

    dt = dt_from_ts(ts)
    date_line = dt.strftime("%Y年%m月%d日 %H:%M")

    texts = collect_texts(post)
    links = collect_links(post)
    media = collect_media(post, archive_root, activity_dir, output_dir)

    if not texts and not links and not media:
        return

    out.write(rf"\subsection*{{{escape_tex(date_line)}}}" + "\n")
    out.write(rf"\addcontentsline{{toc}}{{subsection}}{{{escape_tex(date_line)}}}" + "\n\n")

    for text in texts:
        out.write(tex_paragraphs(text))
        out.write("\n\n")

    if media:
        write_media_grid(out, media)

    if links:
        out.write(r"\paragraph{リンク}" + "\n")
        for url in links:
            out.write(r"\url{" + escape_url_for_tex(url) + "}" + "\n\n")


def write_comment_record(out, rec):
    """コメント1件を TeX に出力する。"""
    dt = rec["datetime"]
    date_line = dt.strftime("%Y年%m月%d日 %H:%M")

    out.write(rf"\subsection*{{{escape_tex(date_line)}}}" + "\n")
    out.write(rf"\addcontentsline{{toc}}{{subsection}}{{{escape_tex(date_line)}}}" + "\n\n")

    if rec["title"]:
        out.write(r"\textbf{" + escape_tex(rec["title"]) + "}\n\n")

    out.write(r"\begin{quote}" + "\n")
    out.write(tex_paragraphs(rec["text"]))
    out.write("\n" + r"\end{quote}" + "\n\n")


# ------------------------------------------------------------
# TeX ファイル生成
# ------------------------------------------------------------

def write_preamble_file(output_dir):
    """preamble.tex を生成する。"""
    path = output_dir / "preamble.tex"

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


def write_main_tex(output_dir, main_tex_name, years):
    """全体用の facebook_diary.tex を生成する。"""
    path = output_dir / main_tex_name

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


def write_year_file(year, by_year_month, archive_root, activity_dir, output_dir, main_tex_name):
    """指定年の yearXXXX.tex を1つ生成する。"""
    path = output_dir / f"year{year}.tex"

    months = sorted(
        month for y, month in by_year_month.keys()
        if y == year
    )

    with path.open("w", encoding="utf-8") as out:
        write_subfile_header(out, main_tex_name)
        out.write(rf"\chapter{{{year}年}}" + "\n\n")

        for month in months:
            out.write(rf"\section{{{month}月}}" + "\n\n")

            month_posts = sorted(
                by_year_month[(year, month)],
                key=lambda p: p.get("timestamp", 0),
            )

            for post in month_posts:
                write_post(out, post, archive_root, activity_dir, output_dir)

        write_subfile_footer(out)


def write_year_files(by_year_month, archive_root, activity_dir, output_dir, main_tex_name):
    """全ての年別 TeX ファイルを生成し、年のリストを返す。"""
    years = sorted({year for year, month in by_year_month.keys()})

    for year in years:
        write_year_file(
            year,
            by_year_month,
            archive_root,
            activity_dir,
            output_dir,
            main_tex_name,
        )

    return years


def write_appendix_file(path, title, records, main_tex_name):
    """付録用 subfile を1つ生成する。"""
    with path.open("w", encoding="utf-8") as out:
        write_subfile_header(out, main_tex_name)
        out.write(rf"\chapter{{{title}}}" + "\n\n")

        for rec in records:
            write_comment_record(out, rec)

        write_subfile_footer(out)


def write_appendix_files(own_comments, other_comments, output_dir, main_tex_name):
    """2種類のコメント付録ファイルを生成する。"""
    write_appendix_file(
        output_dir / "appendix_own_comments.tex",
        "自分の投稿へのコメント",
        own_comments,
        main_tex_name,
    )

    write_appendix_file(
        output_dir / "appendix_other_comments.tex",
        "他人へのコメント",
        other_comments,
        main_tex_name,
    )


# ------------------------------------------------------------
# 全体処理
# ------------------------------------------------------------

def group_posts_by_year_month(posts):
    """投稿を (年, 月) ごとに分類する。"""
    by_year_month = defaultdict(list)

    for post in posts:
        ts = post.get("timestamp")
        if not ts:
            continue

        dt = dt_from_ts(ts)
        by_year_month[(dt.year, dt.month)].append(post)

    return by_year_month


def load_posts(posts_json):
    """投稿 JSON を読み込む。"""
    with posts_json.open("r", encoding="utf-8") as f:
        return json.load(f)


def build_diary(archive_root, output_dir, main_tex_name):
    """Facebook アーカイブから TeX 一式を生成する。"""
    activity_dir = archive_root / "your_facebook_activity"
    if not activity_dir.exists():
        raise FileNotFoundError(f"見つかりません: {activity_dir}")

    output_dir.mkdir(parents=True, exist_ok=True)

    posts_json = find_posts_json(archive_root)
    posts = load_posts(posts_json)
    own_comments, other_comments = load_comments(archive_root)

    by_year_month = group_posts_by_year_month(posts)

    write_preamble_file(output_dir)

    years = write_year_files(
        by_year_month,
        archive_root,
        activity_dir,
        output_dir,
        main_tex_name,
    )

    write_appendix_files(
        own_comments,
        other_comments,
        output_dir,
        main_tex_name,
    )

    write_main_tex(output_dir, main_tex_name, years)

    return {
        "posts_json": posts_json,
        "own_comment_count": len(own_comments),
        "other_comment_count": len(other_comments),
        "output_dir": output_dir,
        "main_tex": output_dir / main_tex_name,
        "years": years,
    }


def parse_args():
    parser = argparse.ArgumentParser(
        description="Facebookアーカイブを書籍風LaTeX日記に変換します。"
    )

    parser.add_argument(
        "archive_root",
        help="Facebookアーカイブを展開したフォルダ",
    )

    parser.add_argument(
        "-o",
        "--output-dir",
        default=DEFAULT_OUTPUT_DIR,
        help=f"出力先フォルダ。省略時は {DEFAULT_OUTPUT_DIR}",
    )

    parser.add_argument(
        "--main-tex",
        default=DEFAULT_MAIN_TEX,
        help=f"メインTeXファイル名。省略時は {DEFAULT_MAIN_TEX}",
    )

    return parser.parse_args()


def main():
    args = parse_args()

    archive_root = Path(args.archive_root).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    main_tex_name = args.main_tex

    info = build_diary(archive_root, output_dir, main_tex_name)

    print(f"投稿JSON: {info['posts_json']}")
    print(f"自分の投稿へのコメント: {info['own_comment_count']} 件")
    print(f"他人へのコメント: {info['other_comment_count']} 件")
    print(f"作成フォルダ: {info['output_dir']}")
    print(f"メインTeX: {info['main_tex']}")
    print("年別ファイル:", ", ".join(f"year{y}.tex" for y in info["years"]))
    print("画像コピー先: pictures/YYYY/MM/")
    print("付録ファイル: appendix_own_comments.tex, appendix_other_comments.tex")
    print()
    print("全体PDF作成例:")
    print(f"  cd {info['output_dir']}")
    print(f"  uplatex {main_tex_name}")
    print(f"  dvipdfmx {Path(main_tex_name).with_suffix('.dvi')}")
    print()
    print("年別PDF作成例:")
    print("  uplatex year2024.tex")
    print("  dvipdfmx year2024.dvi")


if __name__ == "__main__":
    main()
