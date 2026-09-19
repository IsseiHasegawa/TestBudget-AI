# TestBudget AI

Pull Request の変更差分を NVIDIA Nemotron が意味的に解析し、限られた実行時間予算の
なかで関連するテストを優先実行する CI 支援システム。

> 選択的テストが PASS しても「全テスト PASS」を意味しない。フルスイートは別経路で実行する。

## 現在の状態

| Phase | 内容 | 状態 |
|---|---|---|
| P1 | サンプルアプリ / 30 pytest / nodeid 収集 / 実行時間履歴 / 選択実行 / JSON レポート | 完了 |
| P2 | Git diff 取得、Nemotron API クライアント、構造化出力、ID 検証、fallback | 未着手 |
| P3 | Budget Scheduler、timeout、Runner と Reporter の拡張 | 未着手 |
| P4 | GitHub Actions、Secrets と権限 | 未着手 |
| P5 | 非 AI baseline、10 件以上の変更シナリオ、評価集計 | 未着手 |
| P6 | デモ PR、結果画面、発表準備 | 未着手 |

## セットアップ

```bash
python3 -m venv .venv
./.venv/bin/python -m pip install -r requirements.txt
```

## 使い方

```bash
# 収集: 実在する nodeid、要約、計測済み実行時間を一覧する
./.venv/bin/python main.py collect

# 選択実行: 指定した nodeid だけを実行し、結果を JSON に保存する
./.venv/bin/python main.py run \
  --nodeid 'demo_project/tests/test_coupon.py::test_percent_discount_truncates_partial_cent' \
  --nodeid 'demo_project/tests/test_checkout.py::test_percent_coupon_changes_total'

# フルスイート実行 (実行時間履歴の更新にも使う)
./.venv/bin/python main.py run --all

# 計測済みの実行時間を遅い順に表示する
./.venv/bin/python main.py history
```

`run` は常に `artifacts/run-<timestamp>.json` にレポートを書き出す。`--json PATH` で
出力先を指定できる。レポートには選択したテストだけでなく、**実行しなかったテスト**の
一覧も必ず含まれる。

## ディレクトリ構成

```
src/
  config.py             共通パスと既定値、pytest サブプロセスの環境
  models.py             TestCandidate / TestResult / RunOutcome
  pytest_tb_plugin.py   収集結果と実行結果を JSON に書き出す pytest プラグイン
  test_collector.py     nodeid の収集と検証
  test_runner.py        指定 nodeid のみの実行
  history.py            実行時間と失敗回数の履歴
  reporter.py           JSON レポートとコンソール出力
demo_project/
  app/                  EC ロジック (cart / coupon / checkout / payment / profile)
  tests/                pytest 30 件
tests_internal/         ツール自身のテスト
data/duration_history.json  計測済み実行時間
main.py                 CLI
```

## 設計上の決定

**nodeid は pytest 自身から受け取る。** junit-xml のクラス名から nodeid を組み立てると
パラメータ化テストやクラス内テストで壊れる。`src/pytest_tb_plugin.py` は
`report.nodeid` をそのまま書き出すので、スケジューラが pytest に渡す ID は必ず
収集済みの ID と完全一致する。

**モデル出力はシェルに渡らない。** nodeid は argv の個別要素として渡し、文字列連結は
しない。収集済み候補に存在しない ID は `validate_nodeids` が実行前に捨てる。

**実行時間は中央値で推定する。** 1 回だけ遅かった実行に引きずられないようにするため。
推定値は予測であって保証ではないので、スケジューラ (P3) は余裕時間を持たせる。

**デモテストの一部は意図的に待ち時間を入れている。** `demo_project/tests/support.py` の
`simulate_io()` は決済ゲートウェイや画像アップロードの I/O 待ちを模したもので、実測
した処理時間ではない。デモアプリは純粋な算術演算のみでマイクロ秒で終わるため、この
待ち時間がないと時間予算スケジューリングが成立しない。

**checkout は coupon に間接的に依存する。** `coupon.py` の丸め方を変えると
`test_checkout.py` の合計金額アサーションが落ちる。ファイル名対応だけのテスト選択が
取りこぼすのはこの種の変更であり、評価実験の中心になるケース。

## 検証

```bash
./.venv/bin/python -m pytest -q     # デモ 30 件 + ツール 10 件
```
