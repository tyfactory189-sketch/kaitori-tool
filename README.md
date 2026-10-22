# 買取差益チェッカー

買取wiki・買取商店・森森買取の新品買取価格と、Yahoo!ショッピングの新品最安値（ポイント込みの実質価格）を JAN で突き合わせ、
差益の大きい順に一覧表示する自分用ツールです。GitHub Actions が 1日3回自動で更新し、GitHub Pages で見られます。

## しくみ

```
GitHub Actions（6:07 / 14:07 / 22:07）
  └ run.py
     ├ scrapers/  買取3サイトから JAN・商品名・新品買取価格を取得 → data/buyback_*.json
     ├ yahoo.py   JANごとに Yahoo商品検索API(v3) で新品・在庫ありの出品を取得 → data/yahoo_cache.json
     └ docs/data.json を出力してコミット
GitHub Pages
  └ docs/index.html が data.json を読み、ブラウザ側で還元率・クーポンを反映して計算
```

- Yahoo API は 1秒1件の制限があるため、1回の実行で照合するのは最大 240 分ぶん（約1.3万件）。照合が古いものから順に更新するので、件数が多くても数回で一巡します。
- 同じJANで出品されている部品・付属品・中古・箱傷み品は除外しています（`yahoo.py` の `EXCLUDE`）。
- 買取サイトの取得に失敗したときは前回のデータを使い、画面上部に「⚠取得失敗」を出します。

## セットアップ（初回だけ・約15分）

1. **Yahoo のアプリID（Client ID）を取る**
   https://e.developer.yahoo.co.jp/dashboard/ → 「新しいアプリケーションを開発」→ 種別「クライアントサイド」で作成し、Client ID を控える。

2. **GitHub にリポジトリを作ってこのフォルダを入れる**
   - 新規リポジトリを作成（Public 推奨。無料プランで Pages を使えるのは Public のみ）
   - このフォルダの中身を全部アップロード（`.github` フォルダも忘れずに）

3. **アプリIDを登録**
   リポジトリの Settings → Secrets and variables → Actions → New repository secret
   - Name: `YAHOO_APPID` / Secret: 手順1の Client ID

4. **Pages を有効化**
   Settings → Pages → Source「Deploy from a branch」、Branch `main` / フォルダ `/docs` → Save

5. **初回実行**
   Actions タブ → 「価格データ更新」→ Run workflow
   終わったら `https://<ユーザー名>.github.io/<リポジトリ名>/` を開く。

## 設定（任意）

Settings → Secrets and variables → Actions → Variables に追加すると変更できます。

| 変数 | 既定値 | 内容 |
|---|---|---|
| `MIN_BUY` | 3000 | Yahooで照合する最低買取価格 |
| `YAHOO_BUDGET_MIN` | 240 | 1回の実行でYahoo照合に使う最大分数 |

画面左の還元率・クーポン・送料の設定はブラウザに保存されます。

## 自分のPCで動かす場合

GitHub のサーバーからだと買取サイトにブロックされる場合は、PCで取得してから push してください。

```
pip install -r requirements.txt
set YAHOO_APPID=xxxxx        （Macは export YAHOO_APPID=xxxxx）
python run.py
python -m http.server -d docs 8000   → http://localhost:8000
```

## テスト

```
python tests/test_parsers.py
```

各サイトのページ構造（2026年10月時点）を模したHTMLでパーサを確認します。サイトの作りが変わって 0件になった場合は `scrapers/` の該当ファイルを直します。

## 注意

- 買取価格は各サイトの掲載価格（参考値）です。実際の金額は申込後の承諾メール等で決まります。
- 差益の多くは期間限定の PayPayポイントです。
- 各サイトの利用規約を確認し、アクセス間隔（1秒前後）を短くしすぎないでください。
