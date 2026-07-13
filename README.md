# facebook2tex Version 3

Facebook のアーカイブデータを読み込み、個人の日記データとして長期保存するための **Diary Package** を生成する Python プログラムです。

Version 3 では、Facebook データを直接 TeX へ変換するのではなく、Facebook に依存しない中間形式である Diary Package を生成します。

生成した Diary Package は、macOS アプリ **myDiary** へ Import できます。

---

## 処理の流れ

```text
Facebook Archive
        ↓
facebook2tex Version 3
        ↓
Diary Package
├── diary.json
└── pictures/
        ↓
myDiary
        ↓
SQLite + local pictures
```

`facebook2tex` が Facebook 固有のデータ構造を解析し、必要な画像やサムネイルを Package 内へ集めます。

`myDiary` は完成した Diary Package を読み込むだけなので、Import 時に Facebook や外部Webサイトへアクセスする必要はありません。

---

## Version 3 の方針

Version 1 では、

```text
Facebook Archive
        ↓
TeX
        ↓
PDF
```

という変換を行っていました。

Version 3 では、

```text
Facebook Archive
        ↓
Diary Model
        ↓
Diary Package
```

という構成に変更しています。

Facebook 固有の入力処理と、日記データの保存・表示を分離することで、将来 Facebook 以外のデータも同じ Diary Package 形式へ変換できることを目指しています。

---

## 主な機能

- Facebook Archive の投稿読み込み
- 自分のコメントの読み込み
- 投稿とコメントの統合
- `own_comment` / `other_comment` の分類
- 親投稿を特定できるコメントへの `parent_post_id` 設定
- Facebook Archive 内の写真を Package へコピー
- YouTube サムネイルの取得
- Webリンクの OGP画像取得
- 必要に応じたWebページキャプチャ
- 取得対象外ドメインの指定
- 重複投稿の整理
- Diary Package の JSON 出力

---

## ファイル構成

主なソースファイルは次のとおりです。

```text
main.py
mydiary_reader.py
mydiary_model.py
media_manager.py
json_writer.py
utils.py
```

### `main.py`

コマンドライン引数を処理し、全体の処理を実行します。

```text
Facebook Archive 読み込み
        ↓
Diary Model生成
        ↓
MediaManager
        ↓
diary.json出力
```

### `mydiary_reader.py`

Facebook Archive を読み込み、Facebook 固有のデータを Diary Model へ変換します。

主な処理：

- 投稿の読み込み
- コメントの読み込み
- 写真のコピー
- 重複投稿の整理
- 投稿とコメントの統合
- コメントと親投稿の関連付け

### `mydiary_model.py`

Facebook に依存しない Diary Model を定義します。

投稿、メディア、投稿間リンク、入力元情報などを表現します。

### `media_manager.py`

Diary Model 内の外部メディアを実体化します。

主な処理：

- YouTube サムネイル取得
- Webリンクの OGP画像取得
- Webページキャプチャ
- Package 内への画像保存

### `json_writer.py`

完成した Diary Model を `diary.json` として出力します。

### `utils.py`

URL処理などの共通処理を提供します。

---

## 使用方法

```bash
python main.py \
    ~/facebook_backup \
    ~/MyDiaryPackage
```

第1引数：

```text
Facebook Archive のルートフォルダ
```

第2引数：

```text
出力する Diary Package フォルダ
```

---

## 重複投稿の処理

`--dedupe-scope` で重複投稿の省略範囲を指定できます。

### 連続した重複を省略

```bash
python main.py \
    ~/facebook_backup \
    ~/MyDiaryPackage \
    --dedupe-scope consecutive
```

### 同じ月の重複を省略

```bash
python main.py \
    ~/facebook_backup \
    ~/MyDiaryPackage \
    --dedupe-scope month
```

### 同じ年の重複を省略

```bash
python main.py \
    ~/facebook_backup \
    ~/MyDiaryPackage \
    --dedupe-scope year
```

### 重複省略を行わない

```bash
python main.py \
    ~/facebook_backup \
    ~/MyDiaryPackage \
    --dedupe-scope none
```

`none` を指定した場合でも、Facebook Archive 内に存在する実質的に同一の raw post は整理されます。

例えば、

- 同一 timestamp
- 同一本文
- 同一URL
- 同一メディア

であり、Facebook内部の `data` 配列に含まれる空要素数だけが異なる投稿は、同一投稿として扱います。

---

## Link Capture を無効にする

OGP画像が見つからないWebページについて、画面キャプチャを行わない場合：

```bash
python main.py \
    ~/facebook_backup \
    ~/MyDiaryPackage \
    --no-link-capture
```

---

## Diary Package

生成されるPackageは概ね次の構成です。

```text
MyDiaryPackage/
├── diary.json
└── pictures/
    ├── photo/
    ├── youtube/
    └── link/
```

### `pictures/photo/`

Facebook Archive に含まれていた写真を保存します。

### `pictures/youtube/`

YouTube のサムネイルを保存します。

### `pictures/link/`

Webリンクの OGP画像またはキャプチャ画像を保存します。

---

## オフラインImport

Version 3 の重要な方針は、

> 外部メディアの取得は facebook2tex が行い、myDiary は Package 内のファイルだけを読み込む

ことです。

```text
facebook2tex
    ├── Facebook Archiveを解析
    ├── 写真をコピー
    ├── YouTubeサムネイルを取得
    └── Link画像を取得

            ↓

      完成したPackage

            ↓

myDiary
    └── Package内ファイルだけをImport
```

これにより、Diary Package をコピーするだけで、別のMacへ日記データを移動できます。

---

## コメントと親投稿

Facebook Archive では、コメントと元投稿の関係が常に明確に保存されているとは限りません。

Version 3 では、次の安全な範囲で親投稿を設定します。

1. 同一 `source.id` の投稿と `own_comment` は統合
2. 同一URLを持つ親候補が一意の場合、`parent_post_id` を設定
3. 候補が複数ある場合は自動的に関連付けない
4. 一致しないコメントは独立した `own_comment` として残す

`parent_post_id` が設定されたコメントは、myDiary 側で親投稿の下に表示できます。

自動判定できなかったコメントについては、将来 myDiary 側で手動関連付けを行えるようにする予定です。

---

## myDiary

Diary Package の閲覧・編集には、別プロジェクトの `myDiary` を使用します。

myDiary は SwiftUI と SQLite（GRDB）で作成した macOS 用日記アプリです。

```text
Diary Package
        ↓ Import
myDiary
        ↓
SQLite
+
local pictures
```

---

## Version 1 / Version 2 / Version 3

### Version 1 — `main`

Facebook Archive から TeX 文書を直接生成します。

### Version 2 — `v2-diary-model`

Diary Model 導入のための開発ブランチです。

### Version 3 — `v3`

Diary Package を正式な中間形式として生成し、myDiary との連携を行います。

---

## 開発状況

Version 3 は現在開発中です。

実装済み：

- Facebook投稿の読み込み
- コメントの読み込み
- Diary Modelへの変換
- 写真のPackage化
- YouTubeサムネイル取得
- Webリンク画像取得
- 重複投稿整理
- 投稿とコメントの統合
- 一部コメントの親投稿関連付け
- Diary Package JSON出力
- myDiaryへのImport

今後の予定：

- Diary Package仕様の文書化
- JSON仕様READMEの追加
- コメントと親投稿の関連付け改善
- myDiaryからのDiary Package Export
- より汎用的なDiary Package形式への整理

---

## Privacy

Facebook Archive には個人情報、投稿本文、写真などが含まれます。

このリポジトリには、実際のFacebook Archive、生成された Diary Package、個人の写真や日記データは含めないでください。

---

## License

MIT License
