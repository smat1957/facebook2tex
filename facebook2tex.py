import json
import argparse
import shutil
from pathlib import Path
from datetime import datetime
from collections import defaultdict
import re

IMAGE_EXTS = {".jpg", ".jpeg", ".png"}

URL_RE = re.compile(r'https?://[^\s<>"\]\}）)。,、]+')

def escape_url_for_tex(url):
    url = url.strip()
    url = url.replace("\\", r"\textbackslash{}")
    url = url.replace("%", r"\%")
    url = url.replace("#", r"\#")
    url = url.replace("{", r"\{")
    url = url.replace("}", r"\}")
    return url

def escape_tex_except_url(text):
    """
    URL以外だけTeXエスケープする。
    """

    result = []
    pos = 0

    for m in URL_RE.finditer(text):

        # URLの前
        result.append(
            escape_tex(text[pos:m.start()])
        )

        # URL本体
        result.append(
            r"\url{" + escape_url_for_tex(m.group(0)) + "}"
        )

        pos = m.end()

    result.append(
        escape_tex(text[pos:])
    )

    return "".join(result)


def fix_facebook_text(s):
    if not isinstance(s, str):
        return ""
    try:
        s = s.encode("latin1").decode("utf-8")
    except Exception:
        pass

    s = s.replace("\ufe0f", "")  # Variation Selector-16
    return s


def escape_tex(s):
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


def tex_paragraphs(s):
    s = fix_facebook_text(s).strip()

    paras = []

    for p in s.split("\n"):
        p = p.strip()
        if not p:
            continue

        paras.append(
            escape_tex_except_url(p)
        )

    return "\n\n".join(paras)


def dt_from_ts(ts):
    return datetime.fromtimestamp(ts)


def find_posts_json(archive_root):
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
    p = archive_root / "your_facebook_activity" / "comments_and_reactions" / "comments.json"
    return p if p.exists() else None


def collect_texts(post):
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


def source_path_from_uri(uri, archive_root, activity_dir):
    if uri.startswith("your_facebook_activity/"):
        return archive_root / uri
    return activity_dir / uri


def collect_media(post, archive_root, activity_dir, output_dir):
    """
    画像を pictures/YYYY/MM/ にコピーし、
    TeXから参照する相対パスを返す。
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

        # 既に同名がある場合は上書きしない。
        # 同じ投稿を再生成する分には同じ名前になるのでOK。
        if not dest.exists():
            shutil.copy2(src, dest)

        tex_path = f"pictures/{year}/{month}/{dest_name}"
        media_files.append(tex_path)

    return media_files


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


def extract_comment_record(item):
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


def write_preamble(out):
    out.write(r"""\documentclass[uplatex,openany]{jsbook}

\usepackage[dvipdfmx]{graphicx}
\usepackage[dvipdfmx]{hyperref}
\usepackage{pxjahyper}
\usepackage{geometry}
\usepackage{url}
\geometry{margin=25mm}

\title{Facebook日記}
\author{}
\date{}

\begin{document}

\frontmatter
\maketitle
\tableofcontents

\mainmatter

""")


def write_media_grid(out, media):
    """
    画像を横2枚ずつ並べる。
    奇数枚の場合、最後の1枚は中央配置。
    """
    if not media:
        return

    out.write(r"\paragraph{写真}" + "\n")

    for i in range(0, len(media), 2):
        pair = media[i:i + 2]

        out.write(r"\begin{center}" + "\n")

        if len(pair) == 2:
            for m in pair:
                out.write(r"\begin{minipage}{0.48\linewidth}" + "\n")
                out.write(r"\centering" + "\n")
                out.write(rf"\includegraphics[width=\linewidth]{{{m}}}" + "\n")
                out.write(r"\end{minipage}" + "\n")
                out.write(r"\hfill" + "\n")
        else:
            m = pair[0]
            out.write(r"\begin{minipage}{0.70\linewidth}" + "\n")
            out.write(r"\centering" + "\n")
            out.write(rf"\includegraphics[width=\linewidth]{{{m}}}" + "\n")
            out.write(r"\end{minipage}" + "\n")

        out.write(r"\end{center}" + "\n\n")


def write_post(out, post, archive_root, activity_dir, output_dir):
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
            out.write(rf"\url{{{url}}}" + "\n\n")


def write_comment_record(out, rec):
    dt = rec["datetime"]
    date_line = dt.strftime("%Y年%m月%d日 %H:%M")

    out.write(rf"\subsection*{{{escape_tex(date_line)}}}" + "\n")
    out.write(rf"\addcontentsline{{toc}}{{subsection}}{{{escape_tex(date_line)}}}" + "\n\n")

    if rec["title"]:
        out.write(r"\textbf{" + escape_tex(rec["title"]) + "}\n\n")

    out.write(r"\begin{quote}" + "\n")
    out.write(tex_paragraphs(rec["text"]))
    out.write("\n" + r"\end{quote}" + "\n\n")


def write_year_files(by_year_month, archive_root, activity_dir, output_dir):
    years = sorted({year for year, month in by_year_month.keys()})

    for year in years:
        path = output_dir / f"year{year}.tex"

        with path.open("w", encoding="utf-8") as out:
            out.write(rf"\chapter{{{year}年}}" + "\n\n")

            months = sorted(
                month for y, month in by_year_month.keys()
                if y == year
            )

            for month in months:
                out.write(rf"\section{{{month}月}}" + "\n\n")

                month_posts = sorted(
                    by_year_month[(year, month)],
                    key=lambda p: p.get("timestamp", 0)
                )

                for post in month_posts:
                    write_post(
                        out,
                        post,
                        archive_root,
                        activity_dir,
                        output_dir
                    )

    return years


def write_appendix_files(own_comments, other_comments, output_dir):
    own_path = output_dir / "appendix_own_comments.tex"
    other_path = output_dir / "appendix_other_comments.tex"

    with own_path.open("w", encoding="utf-8") as out:
        out.write(r"\chapter{自分の投稿へのコメント}" + "\n\n")
        for rec in own_comments:
            write_comment_record(out, rec)

    with other_path.open("w", encoding="utf-8") as out:
        out.write(r"\chapter{他人へのコメント}" + "\n\n")
        for rec in other_comments:
            write_comment_record(out, rec)


def write_main_tex(output_path, years):
    with output_path.open("w", encoding="utf-8") as out:
        write_preamble(out)

        for year in years:
            out.write(rf"\input{{year{year}.tex}}" + "\n")

        out.write("\n")
        out.write(r"\appendix" + "\n")
        out.write(r"\input{appendix_own_comments.tex}" + "\n")
        out.write(r"\input{appendix_other_comments.tex}" + "\n\n")

        out.write(r"\end{document}" + "\n")


def main():
    parser = argparse.ArgumentParser(
        description="Facebookアーカイブを書籍風LaTeX日記に変換します。"
    )
    parser.add_argument("archive_root")
    parser.add_argument("-o", "--output", default="facebook_diary.tex")
    args = parser.parse_args()

    archive_root = Path(args.archive_root).expanduser().resolve()
    activity_dir = archive_root / "your_facebook_activity"

    if not activity_dir.exists():
        raise FileNotFoundError(f"見つかりません: {activity_dir}")

    output_path = Path(args.output).resolve()
    output_dir = output_path.parent
    output_dir.mkdir(parents=True, exist_ok=True)

    posts_json = find_posts_json(archive_root)

    with posts_json.open("r", encoding="utf-8") as f:
        posts = json.load(f)

    own_comments, other_comments = load_comments(archive_root)

    by_year_month = defaultdict(list)

    for post in posts:
        ts = post.get("timestamp")
        if not ts:
            continue
        dt = dt_from_ts(ts)
        by_year_month[(dt.year, dt.month)].append(post)

    years = write_year_files(
        by_year_month,
        archive_root,
        activity_dir,
        output_dir
    )

    write_appendix_files(
        own_comments,
        other_comments,
        output_dir
    )

    write_main_tex(
        output_path,
        years
    )

    print(f"投稿JSON: {posts_json}")
    print(f"自分の投稿へのコメント: {len(own_comments)} 件")
    print(f"他人へのコメント: {len(other_comments)} 件")
    print(f"作成しました: {output_path}")
    print("年別ファイル:", ", ".join(f"year{y}.tex" for y in years))
    print("画像コピー先: pictures/YYYY/MM/")
    print("付録ファイル: appendix_own_comments.tex, appendix_other_comments.tex")


if __name__ == "__main__":
    main()