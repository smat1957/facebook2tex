# facebook2tex

Facebook のバックアップデータを、書籍形式の LaTeX 文書へ変換する Python プログラムです。

単なるバックアップ閲覧ではなく、Facebook の投稿・画像・コメント・リンクを「日記」や「自分史」として、長期間保存・印刷できる PDF にすることを目的としています。

## 特徴

* Facebook バックアップ JSON を解析
* 投稿を年・月ごとに自動分類
* 投稿日時を保持
* 投稿本文を LaTeX へ変換
* 本文中の URL を `\url{}` に自動変換
* YouTube リンクのサムネイル画像を取得可能
* YouTube サムネイルをクリックすると元動画を開ける PDF を生成
* 外部 Web ページのキャプチャ画像を取得可能
* 添付画像を `pictures/YYYY/MM/` に整理してコピー
* 画像は 2 枚ずつ横並びにレイアウト
* Facebook バックアップ本体に依存しない LaTeX 一式を生成
* 自分の投稿へのコメントを付録として出力
* 他人へのコメントを付録として出力
* コメント内の URL や YouTube リンクも処理可能
* 年ごとの `subfiles` を生成し、各年だけを個別にコンパイル可能
* 重複投稿の省略範囲を指定可能

## 出力例

```text
facebook_diary/
│
├── facebook_diary.tex
├── preamble.tex
│
├── year2011.tex
├── year2012.tex
├── …
├── year2026.tex
│
├── appendix_own_comments.tex
├── appendix_other_comments.tex
│
└── pictures/
    ├── 2011/
    ├── 2012/
    ├── youtube/
    └── links/
```

各年ファイルは `subfiles` 対応になっているため、たとえば 2024 年分だけ確認したい場合は次のようにできます。

```bash
cd facebook_diary
uplatex year2024
dvipdfmx year2024
```

全体版は次のように作成します。

```bash
cd facebook_diary
uplatex facebook_diary
dvipdfmx facebook_diary
```

## 必要な環境

* Python 3.10 以降
* upLaTeX
* dvipdfmx

通常の変換だけなら、Python の追加ライブラリは不要です。

外部 Web ページのキャプチャを使う場合は Playwright が必要です。

```bash
python -m pip install playwright
python -m playwright install chromium
```

## 使い方

Facebook のバックアップを展開したディレクトリに対して実行します。

```bash
python facebook2tex.py ~/facebook_backup
```

すると、既定では次のフォルダが生成されます。

```text
facebook_diary/
```

## オプション

### YouTube サムネイルを取得する

```bash
python facebook2tex.py ~/facebook_backup --capture-youtube
```

YouTube リンクのサムネイルを取得し、PDF 内に画像として貼り込みます。
サムネイル画像はクリック可能で、元の YouTube 動画を開けます。

### 外部 Web ページをキャプチャする

```bash
python facebook2tex.py ~/facebook_backup --capture-links
```

外部リンク先の Web ページを Chromium で開き、スクリーンショットを保存して PDF に貼り込みます。

Facebook、Instagram、X など一部のサイトや、PDF / HTML ファイルへの直接リンクはキャプチャ対象外にしています。

### YouTube と外部リンクの両方を処理する

```bash
python facebook2tex.py ~/facebook_backup --capture-youtube --capture-links
```

### 出力先フォルダを指定する

```bash
python facebook2tex.py ~/facebook_backup -o my_diary
```

### メイン TeX ファイル名を指定する

```bash
python facebook2tex.py ~/facebook_backup --main-tex diary.tex
```

### 重複投稿の省略範囲を指定する

```bash
python facebook2tex.py ~/facebook_backup --dedupe-scope consecutive
python facebook2tex.py ~/facebook_backup --dedupe-scope month
python facebook2tex.py ~/facebook_backup --dedupe-scope year
python facebook2tex.py ~/facebook_backup --dedupe-scope none
```

指定できる値は次の通りです。

```text
none         重複省略しない
consecutive 直前に出力した投稿と同じなら省略
month        同じ月で出力済みなら省略
year         同じ年で出力済みなら省略
```

既定値は `consecutive` です。

## Facebook バックアップ

現在対応しているバックアップ形式は、次のような Facebook の JSON バックアップです。

```text
your_facebook_activity/
```

主に次のファイルを利用します。

```text
your_facebook_activity/posts/your_posts_1.json
your_facebook_activity/posts/your_posts__check_ins__photos_and_videos_1.json
your_facebook_activity/comments_and_reactions/comments.json
```

## 画像について

投稿に添付された画像は、Facebook バックアップを直接参照せず、生成先フォルダ内へコピーします。

```text
pictures/YYYY/MM/
```

YouTube サムネイルは次の場所へ保存します。

```text
pictures/youtube/YYYY/MM/
```

外部リンクのキャプチャ画像は次の場所へ保存します。

```text
pictures/links/YYYY/MM/
```

このため、元の Facebook バックアップを移動・削除しても、生成済みの LaTeX 文書はそのまま利用できます。

## LaTeX コンパイル

全体 PDF を作る場合:

```bash
cd facebook_diary
uplatex facebook_diary
dvipdfmx facebook_diary
```

目次を正しく反映するには、必要に応じて `uplatex` を複数回実行してください。

```bash
uplatex facebook_diary
uplatex facebook_diary
dvipdfmx facebook_diary
```

年別ファイルだけ確認する場合:

```bash
uplatex year2024
dvipdfmx year2024
```

## 注意事項

* Facebook のバックアップ形式は変更される可能性があります。
* ログインが必要なページや動的なページは、期待通りにキャプチャできない場合があります。
* YouTube サムネイルは YouTube 側で公開されている画像を取得します。
* 外部サイトのキャプチャや保存は、各サイトの利用条件に従ってください。
* 大量のリンクをキャプチャする場合は時間がかかります。

## ライセンス

MIT License

## Author

smat1957

GitHub: https://github.com/smat1957
