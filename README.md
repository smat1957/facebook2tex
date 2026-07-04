# facebook2tex

Facebook のバックアップデータを、書籍形式の LaTeX 文書へ変換する Python プログラムです。

生成される PDF は、単なるバックアップの閲覧ではなく、「日記」や「自分史」として長期間保存・印刷できることを目的としています。

---

## 特徴

- Facebook バックアップ(JSON)を解析
- 年・月ごとに自動分類
- 投稿日時を保持
- 投稿本文を LaTeX へ変換
- 文中の URL を `\url{}` に自動変換
- 添付画像を整理してコピー
- 画像は 2 枚ずつ横並びにレイアウト
- 画像は Facebook バックアップから独立したフォルダへ保存
- 自分の投稿へのコメントを付録として出力
- 他人へのコメントを付録として出力
- 年ごとの `subfiles` を生成し、各年だけを個別にコンパイル可能

---

## 出力例

```
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
    ├──2011/
    ├──2012/
    └──…
```

各年は

```tex
\documentclass[facebook_diary.tex]{subfiles}
```

となっているため、

```
uplatex year2024
```

だけで 2024 年分だけ確認できます。

完成版は

```
uplatex facebook_diary
dvipdfmx facebook_diary
```

で一冊の PDF を生成できます。

---

## 必要な環境

- Python 3.10 以降
- upLaTeX
- dvipdfmx

使用する Python ライブラリは標準ライブラリのみです。

追加インストールは不要です。

---

## 使い方

Facebook のバックアップを展開したディレクトリに対して

```bash
python facebook2tex.py ~/facebook_backup
```

を実行します。

すると

```
facebook_diary/
```

ディレクトリが生成されます。

その後

```bash
cd facebook_diary

uplatex facebook_diary
dvipdfmx facebook_diary
```

で PDF が作成されます。

---

## Facebook バックアップ

現在対応しているバックアップ形式は

```
your_facebook_activity/
```

以下を含む Facebook の JSON バックアップです。

利用する主なファイルは

```
your_posts_1.json
```

または

```
your_posts__check_ins__photos_and_videos_1.json
```

コメントについては

```
comments_and_reactions/comments.json
```

を利用します。

---

## 画像について

画像は Facebook バックアップを直接参照せず、

```
pictures/YYYY/MM/
```

へコピーされます。

そのため、バックアップを削除・移動しても生成した LaTeX 文書はそのまま利用できます。

---

## 今後の予定

- 動画への対応
- Facebook リンク投稿の改善
- 絵文字処理の改善
- インデックス生成
- 投稿検索機能
- しおり(PDF Bookmark)の強化

---

## ライセンス

MIT License

---

## Author

smat1957
