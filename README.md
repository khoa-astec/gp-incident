# gp-incident

本番障害・運用対応チケットを **「原因・影響範囲・対応方針」まで** 調べ切る Claude Code スキルです。
チケットを渡すと、DB（読み取り専用）・ストレージ・CDN・アプリの例外ログ・APM/RUM を順に確認し、
エンジニア向けの調査メモと、**非エンジニアにも分かるチケットコメント案** を作ります。

A Claude Code skill that takes an incident ticket to a verified root cause, the affected scope and a
plain-language comment, using read-only evidence only.

## インストール / Install
```
/plugin marketplace add khoa-astec/gp-incident
/plugin install gp-incident@gp-incident
```

## 使い方 / Usage
```
/incident GP-12345
「この写真が表示されない原因を調べて」
```

## 設定 / Configuration
認証情報はこのリポジトリに含めません。各自の環境変数で設定します（詳細は `skills/incident/SKILL.md`）。

| 変数 | 内容 |
|---|---|
| `INCIDENT_DB_EXEC` | 読み取り専用レプリカに `mysql -e` を実行するコマンド（例: 一時的な kubectl pod / 踏み台） |
| `INCIDENT_AWS_PROFILE` | S3・ECS・CloudFront の読み取り用 AWS プロファイル |
| `INCIDENT_BUCKET` / `INCIDENT_CDN_BASE` | メディア用バケット名 / CDN のURL |
| `INCIDENT_GCP_PROJECT` / `INCIDENT_GCP_SA_FILE` | （任意）Cloud Logging のプロジェクトと、読み取り権限のサービスアカウント鍵のパス |

`scripts/gcp_logs.py` は gcloud や追加パッケージなしで Cloud Logging を検索します（Python 標準ライブラリ + openssl のみ）。

## 安全のためのルール
- 本番は **読み取りのみ**。データ修復・設定変更は、ユーザーの明示的な承認後に別手順で行います。
- 秘密情報は表示しません。一時ファイルの鍵は使用後すぐ削除します。
- 顧客名・ID は共有ドキュメントやコミットに書きません。

## 実績 / Results（2026-10、本番の実チケット）
「アルバムで特定の写真だけ表示されず、ダウンロードすると1KBの壊れたファイルになる」という問い合わせを、このスキルの手順で調査しました。

| 項目 | 結果 |
|---|---|
| 原因 | 電子小黒板の合成画像を作る処理が、リリース作業（ローリングデプロイ）と重なってタイムアウトし、合成画像が保存されないまま「黒板付き」の印だけが残っていた |
| 証拠 | DBの対象行、ストレージのバージョン履歴（一度も保存されていないことを確認）、CDNの応答（111バイトのエラーXML）、アプリ例外ログ（ヘッドレスChromeのタイムアウト4件）、同時刻のブラウザエラー |
| 影響範囲 | 同じ時間帯（約3分間）の写真6枚・3社。前後の時間帯は正常と確認 |
| 所要時間 | チケット受領から原因特定・影響範囲・非エンジニア向けコメント投稿まで **半日以内** |
| その後 | 再発防止の修正をブランチで作成（失敗時は元の写真を表示）、影響を受けた写真は hotfix で復旧予定 |
