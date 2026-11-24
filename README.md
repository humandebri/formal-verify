# formal-verify v0.6.0
[![ci](https://github.com/humandebri/formal-verify/actions/workflows/ci.yml/badge.svg)](https://github.com/humandebri/formal-verify/actions/workflows/ci.yml)

Agent Skills形式の形式検証オーケストレーター（独立実装）。Z3/cvc5、Quint、Verus、Kani、Lean 4を対象とし、証明計画と Idris2 による型レベル API 設計の指針も含む。

## Install
このリポジトリを clone し、Claude Codeなら `~/.claude/skills/formal-verify`、Codexなら `~/.codex/skills/formal-verify`（またはプロジェクトの `.agents/skills/formal-verify`）に配置する。

```sh
git clone https://github.com/humandebri/formal-verify ~/.claude/skills/formal-verify
```
各検証器は必要時に公式手順で個別に導入する。Python 3.10+、外部Python依存なし。

## Quick start
```sh
python3 scripts/verify.py detect
python3 scripts/verify.py run z3 examples/average.smt2 --property average_equivalence --out evidence/smt
python3 scripts/verify.py run quint examples/counter.qnt --property safe --bound 10 --out evidence/quint
python3 scripts/verify.py run verus examples/add.rs --property add --out evidence/verus
python3 scripts/verify.py run kani examples/kani_average.rs --property check --out evidence/kani
python3 scripts/verify.py run lean examples/Add.lean --property add_comm_example --out evidence/lean
# プロジェクト単位（Cargo / Lake）
python3 scripts/verify.py run kani --project examples/projects/kani-crate --property midpoint_matches_wide --out evidence/kani-proj
python3 scripts/verify.py run verus --project examples/projects/verus-crate --property max --out evidence/verus-proj
python3 scripts/verify.py run lean LeanLake/Midpoint.lean --project examples/projects/lean-lake --property midpoint_le_max --out evidence/lean-proj
python3 -m unittest discover -s tests -v
FORMAL_VERIFY_INTEGRATION=1 python3 -m unittest tests/test_integration.py -v  # 実検証器で全サンプルを確認（遅い）
```
出力ディレクトリは新規であること。各実行はJSON、標準出力・標準エラー、入力とログのSHA256、ツールバージョン情報を保存する。SMT例では期待値は sat / unsat。`--property` はQuint run/verify では invariant、Kani では harness、それ以外では記録用ラベル。`quint test`/`typecheck` では受け付けない（テスト選択は `--quint-match`）。

### 終了コードと `observed`
| 終了コード | `observed.outcome` | 意味 |
|---|---|---|
| 0 | `clean` | ツールが失敗を報告しなかった（証明成功を意味しない） |
| 1 | `violation_reported` / `untrusted_axioms` | 反例・検証失敗・テスト失敗をツールが報告した。Lean で `sorry` や標準外の公理に依存した |
| 2 | `timeout` / `tool_missing` / `unrecognized` | 未導入、タイムアウト、既知パターン外の失敗、または入力ファイルが実行中に変化した |
| 3 | `input_error` | 構文・型エラー、存在しない invariant/harness 名など、入力や引数をツールが拒否した |

`observed.signals` には判定根拠となった出力行が入る。SMT では `smt_results`（sat/unsat/unknown の列）、Verus では JSON の検証件数、Lean では `#print axioms` の結果が `lean_axioms` に入り、`propext`・`Classical.choice`・`Quot.sound` 以外の公理（`sorryAx`、ユーザー定義 `axiom`、`native_decide` の補助公理）があれば `untrusted_axioms`（終了コード1）になる。`--property` の定理に `#print axioms` 出力がなければ警告する。分類は各ツールの出力パターンによるヒューリスティックで、意味論的判定ではない。必ず生ログをレビューする。

ツールは既定で `OUT/work` を作業ディレクトリとして実行され、ビルド成果物（Verus の実行ファイル、`_apalache-out/` 等）はそこに閉じ込められる。

### プロジェクトモード（`--project DIR`）
| backend | 実行内容 | 対象の指定 |
|---|---|---|
| kani | `cargo kani --harness <property>` | `--property` に harness 名 |
| verus | `cargo verus focus -- --output-json`（依存クレートは検証しない） | crate 全体。`--property` は記録用 |
| lean | `lake lean <file> -- -DwarningAsError=true`（import 先をビルドしてから検査） | プロジェクト内のファイル。`#print axioms` を書く |

Cargo のビルド出力は `CARGO_TARGET_DIR=OUT/work/target` に隔離する。Lake は `.lake/` と `lake-manifest.json` をプロジェクト内に作る（通常の Lake の動作）。実行前後にプロジェクト内の全ソースファイル（git 管理下なら `git ls-files -co --exclude-standard`）をハッシュし、既存ファイルが変更・削除されたら `input_changed`（終了コード2）、新規作成ファイルは警告として `project.changes` に記録する。`cargo verus` には Verus と同じ日付の `vstd` クレートが必要（例: Verus 0.2026.11.22 なら `vstd = "=0.0.0-2026-11-22-0344"`）。

### プロセスの後始末
ツールは独自のプロセスグループで起動する。タイムアウト時はグループ全体（Apalache の JVM、CBMC など）を SIGTERM→SIGKILL で停止し、正常終了後に残ったプロセスも停止して警告に記録する。自分で新しいセッションを作るデーモンは対象外。

### 証跡の照合（case_check）
`case.json` の evidence に `model_check_result`（元モデルの検査の `result.json`）と `fixed_check_result`（修正後モデルの検査の `result.json`）を入れると、`case_check.py` が次を機械的に確認する: ログの sha256 が一致すること、`input_sha256` が evidence の `model` / `fixed_model` と一致すること、元モデルが `violation_reported`・修正後が `clean` であること、両者の backend・property・bound・mode が同じであること（性質を弱めて修正していないこと）、検査中に入力が変わっていないこと。どちらかが無ければ警告を出す。result.json には git の HEAD と未コミット変更の有無も記録される。`detect` は各ツールの `--version` を実行し、`usable` が false なら導入済みでも使えない（例: Lean のツールチェーン未設定）。

## Limitations
- v0.3は証跡収集とエージェント向けルーティングのMVP。全バックエンドの自動判定、形式的なモデル対応証明、完全な信頼境界監査、CI用の意味論的ゲートは未実装。
- 2026-11-24 に macOS arm64 で Quick start の全サンプルを実検証済み（Z3 5.4.1 / cvc5 1.4.2 / Quint 0.34.0 + Apalache (JDK 21) / Verus 0.2026.11.22 / Kani 0.68.0 / Lean 4.36.0）。単体テスト29件と統合テスト（単一ファイル11ケース、プロジェクト3ケース、async-counter の case_check 通し確認）も成功。GitHub Actions で単体テスト（Ubuntu/macOS × Python 3.10/3.13）と、全検証器を固定バージョンで導入した統合テストを実行する。他環境・他バージョンでは再確認すること。
- タイムアウトはプロセスグループ単位で停止するが、新しいセッションを作るデーモン、ネットワーク遮断、資源制限は外部サンドボックスに委ねる。Cargo/Lake はビルドスクリプトや依存の取得を行う。未信頼コードは隔離環境でのみ実行する。
- 単一ファイルモードでは入力ファイルのみハッシュ化する（git の HEAD/dirty は記録）。プロジェクトモードではプロジェクト内のソースを全てハッシュするが、外部依存（crates.io、Lake の依存パッケージ）はロックファイルで別途固定する。
- `result.json` には入力・コマンド・作業ディレクトリの絶対パス（ホームディレクトリ名を含む）が記録される。証跡を公開リポジトリに commit する前に確認する。

## Changelog
- v0.6.0: `--project` で Cargo（Kani / Verus）と Lake（Lean）のプロジェクトを検証（ビルド出力の隔離、プロジェクト全体のハッシュと変更検出）。タイムアウト時と終了後にプロセスグループごと停止。`case_check.py` が verify.py の result.json を照合。result.json に git 情報を追加（`schema_version: 3`）。Verus を 0.2026.11.22 に更新。
- v0.5.0: 旧 `formalize-proofs` スキルを統合（証明計画テンプレートと公理・定義・補題・定理・refinement の構造化、Idris2、Lean のモデリング規則、Verus の抽出境界と specgen-cli 連携、ルーティング追加）。Codex 用 `agents/openai.yaml` を追加。
- v0.4.0: Lean で標準外の公理・`sorry` に依存した証明を終了コード1（`untrusted_axioms`）に変更し、`lean_axioms` を記録。CI（GitHub Actions）を追加。references（SMT/Kani/Verus/Lean）を拡充し、掲載コード例を実検証器で確認。
- v0.3.0: `observed` による結果分類と終了コード 0/1/2/3、作業ディレクトリを `OUT/work` に分離、`detect` の動作確認、`quint test` での `--property` 拒否、cvc5 に `--produce-models`、実検証器の統合テスト。`result.json` は `schema_version: 2`。

## v0.2: Counterexample-driven workflow
参考: https://zenn.dev/mizchi/articles/quint-application-modeling 。`references/application-modeling.md` と `templates/case.json` を使用し、モデル反例・実装再現・修正後再現を区別する。`python3 scripts/case_check.py path/to/case.json` は証跡の存在とハッシュを確認するだけで、意味論は認証しない。

Quint collector: `--quint-mode typecheck|test|run|verify`、`--quint-backend apalache|tlc`、`--seed`、`--samples` を追加。CLIの実バージョンでオプションを確認すること。TLCの有限全探索は探索完了を別途確認する。

`examples/async-counter/` は独自の最小サンプル。Python実装のRED/GREENは実行確認済み。`quint test` / `quint run` / `quint verify` で counter.qnt の反例と fixed.qnt の無違反を確認済みで、replay.py のイベント列はその反例トレースと一致する。既存の他バックエンドも引き続き利用できる。
