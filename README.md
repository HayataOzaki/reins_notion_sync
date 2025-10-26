# REINS → Notion Sync

REINS の賃貸検索結果を Notion のデータベースに同期する自動化スクリプトです。Notion の「物件検索」データベースで「検索対象」にチェックを入れた行を検出し、REINS で検索して取得した物件情報を「物件」データベースに登録します。図面 PDF があればファイルプロパティに添付します。

## 機能

- Notion API を用いた「物件検索」DB の監視
- REINS ログインおよび検索条件の自動入力（Selenium）
- 最大 50 件の物件詳細取得と PDF ダウンロード
- Notion 物件 DB への作成 / 更新、リレーション付与
- データ正規化（和暦→西暦、通貨・面積の数値化など）

## セットアップ

1. 依存パッケージをインストールします。

   ```bash
   pip install -r requirements.txt
   ```

2. `.env.example` を `.env` にコピーし、各種認証情報とデータベース ID を設定します。

   ```env
   REINS_ID=your-id
   REINS_PASSWORD=your-password
   NOTION_TOKEN=integration-token
   NOTION_DB_SEARCH=search-database-id
   NOTION_DB_PROPERTY=property-database-id
   ```

3. ChromeDriver を環境にインストールし、Chrome/Chromium のバージョンと一致させます。

## 実行方法

```bash
python main.py
```

スクリプトは以下の流れで処理を実施します。

1. Notion で「検索対象」がオンになっている行を取得
2. REINS にログインし検索条件を入力
3. 検索結果の詳細を開き情報を抽出
4. Notion 物件 DB にアップサートし PDF を添付
5. 検索行のチェックを外し、取得した物件をリレーション

## ログ

`logs/` ディレクトリに以下のファイルを出力します。

- `scraper.log`: Selenium 操作ログ
- `reins_to_notion.log`: 同期フロー全体の進行状況
- `notion_upload.log`: Notion API へのアップロード結果

## マッピング定義

`data/notion_search_to_reins.csv` と `data/reins_property_to_notion.csv` にて、Notion と REINS 間の項目マッピングおよび変換ルールを管理しています。必要に応じて CSV を編集することで柔軟にフィールド対応を調整できます。

## 注意事項

- Notion API のレートリミットに留意し、過剰なリクエストは避けてください。
- PDF は一時ディレクトリに保存され、Notion への添付後にクリーンアップされます（OS のテンポラリ機構に依存します）。
- 本スクリプトは実環境に合わせて適宜セレクタ調整やエラーハンドリングを追加してください。
