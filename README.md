# TestBudget AI

Pull Request の変更差分を NVIDIA Nemotron が意味的に解析し、限られた実行時間予算の
なかで関連するテストを優先実行する CI 支援システム。

> 選択的テストが PASS しても「全テスト PASS」を意味しない。フルスイートは別経路で実行する。

## 現在の状態

| Phase | 内容 | 状態 |
|---|---|---|
| P1 | サンプルアプリ / 30 pytest / nodeid 収集 / 実行時間履歴 / 選択実行 / JSON レポート | 完了 |
| P3 | Git diff 解析、非AI順位付け、Budget Scheduler、timeout、Reporter 拡張 | 完了 |
| P2 | Nemotron API クライアント、構造化出力、検証パイプライン | 完了 |
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

# 変更差分の解析: 変更ファイルと、変更された関数・クラス名
./.venv/bin/python main.py changes                    # 未コミットの変更
./.venv/bin/python main.py changes --base origin/main # PR 相当

# 実行計画: 予算内に収まる範囲を決めるが、実行はしない
./.venv/bin/python main.py select --budget 3

# 予算付き実行: 差分を解析し、順位を付け、予算内で選び、実行する
./.venv/bin/python main.py run --budget 3

# baseline との比較
./.venv/bin/python main.py run --budget 3 --strategy file_rule

# Nemotron による順位付け (.env に NVIDIA_API_KEY が必要)
./.venv/bin/python main.py select --budget 60 --strategy nemotron

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
  pytest_tb_plugin.py   収集結果と実行結果を書き出す pytest プラグイン
  test_collector.py     nodeid の収集と検証
  change_analyzer.py    git diff から変更ファイルと関数・クラス名を抽出
  nemotron_client.py    モデルへの問い合わせ。予算連動タイムアウトとエラー分類
  model_response.py     モデル応答の検証。ネットワーク非依存
  prioritizer.py        非AI順位付け (baseline 3種 + fallback)
  scheduler.py          予算内選択。決定的
  test_runner.py        指定 nodeid のみの実行、締切と個別 timeout
  history.py            実行時間と失敗回数の履歴
  reporter.py           JSON レポートとコンソール出力
demo_project/
  app/                  EC ロジック (cart / coupon / checkout / payment / profile)
  tests/                pytest 30 件
tests_internal/         ツール自身のテスト
data/duration_history.json  計測済み実行時間
main.py                 CLI
```

## 順位付けの方式

| 方式 | 役割 | 内容 |
|---|---|---|
| `file_rule` | 評価用 baseline | 変更ファイル名に対応するテストファイルのみ |
| `duration` | 評価用 baseline | 変更を見ず、短いテストから |
| `history` | 評価用 baseline | 直近で失敗したテストから |
| `keyword` | 実運用の fallback | 上記に加え、変更された関数名がテスト名や docstring に現れるか |
| `nemotron` | 本命 | 差分と候補テストを Nemotron に渡し、意味的な順位を得る。失敗時は `keyword` へ縮退 |

baseline を賢くすると比較実験が無意味になるため、`file_rule` は意図的に単純なままにしてあります。`keyword` は「モデルが使えないときに CI を役立たせる」ための最善手なので、制限していません。

## 実測: coupon.py の丸め処理を変更した場合

`_round_percent` の丸めを切り捨てから四捨五入に変えた差分に対し、予算1秒 (フルスイートは4.6秒) で実行した結果です。

| 方式 | 選択数 | 検出した失敗 | checkout の間接的失敗 |
|---|---|---|---|
| `file_rule` | 23 / 30 | 1 | **見逃し** |
| `keyword` | 22 / 30 | 2 | 検出 |

同じ予算で、選択数はむしろ少ないのに検出した失敗は2倍です。`file_rule` は `test_checkout.py` の名前が `coupon.py` と対応しないため、構造的にこの失敗に到達できません。

### 順位の比較

同じ差分に対し、2つの失敗テストが何番目に置かれるか。数字が小さいほど早く失敗に到達します。

| 方式 | 直接の失敗 (coupon) | 間接の失敗 (checkout) | 両方に到達するまで |
|---|---|---|---|
| `file_rule` | 7 | 27 | 27 件 |
| `duration` | 26 | 27 | 27 件 |
| `history` | 26 | 27 | 27 件 |
| `keyword` | 3 | 8 | 8 件 |
| `nemotron` | 4 | **2** | **4 件** |

Nemotron だけが間接的な失敗を上位に置きました。返ってきた理由は「Order total directly computes from coupon discount which changed rounding method」で、coupon から checkout への依存を言語化しています。

`nemotron` の行は成功した1回の試行です。同条件の3回中2回は9秒のタイムアウトで `keyword` へ縮退しました。この縮退率は隠さずレポートに記録されます。

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

**予算は2段階で守る。** プラグインが実時間の締切を持ち、締切を過ぎたテストは開始しません。さらに締切は個々のテストの上限にもなります。開始を止めるだけでは、すでに走っているテストが予算を踏み越えるためです。サブプロセス全体の timeout はその数秒後に置かれた最後の砦で、通常は発動しません。

**実行結果は1件ずつ追記する。** 予算駆動の実行は途中で止まるのが常態です。セッション終了時にまとめて書くと、完了していたテストの結果まで失われます。

**キーワード照合の誤検出は残してある。** 変更された `_round_percent` の "round" が、profile テストの docstring "round trip" と一致し、無関係なアバターアップロードテストを押し上げます。これはトークン照合の実際の限界なので、調整して消さず `tests_internal/test_ranking.py` に固定してあります。モデルがこの誤りを避けられるかどうかが、比較実験の中身です。

**checkout は coupon に間接的に依存する。** `coupon.py` の丸め方を変えると
`test_checkout.py` の合計金額アサーションが落ちる。ファイル名対応だけのテスト選択が
取りこぼすのはこの種の変更であり、評価実験の中心になるケース。

## 検証

```bash
./.venv/bin/python -m pytest -q     # デモ 30 件 + ツール 10 件
```
