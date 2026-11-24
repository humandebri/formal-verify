# formal-verify v0.2.0
Agent Skills形式の形式検証オーケストレーター（独立実装）。Z3/cvc5、Quint、Verus、Kani、Lean 4を対象とする。

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
python3 -m unittest discover -s tests -v
```
出力ディレクトリは新規であること。各実行はJSON、標準出力・標準エラー、入力とログのSHA256、ツールバージョン情報を保存する。終了コード0は収集処理の成功のみを意味し、証明成功ではない。意味論的判定は必ずレビューする。SMT例では期待値は sat / unsat。`--property` はQuint/Kani以外では記録用ラベル。

## Limitations
- v0.2は証跡収集とエージェント向けルーティングのMVP。全バックエンドの自動判定、形式的なモデル対応証明、完全な信頼境界監査、CI用の意味論的ゲートは未実装。
- 2026-11-24 に macOS arm64 で Quick start の全サンプルを実検証済み（Z3 5.4.1 / cvc5 1.4.2 / Quint 0.34.0 + Apalache (JDK 21) / Verus 0.2026.05.05 / Kani 0.68.0 / Lean 4.36.0）。Pythonテスト8件も成功（模擬ソルバー含む）。他環境・他バージョンでは再確認すること。
- タイムアウトは直接起動プロセスに対するもの。子孫プロセスの完全停止、ネットワーク遮断、資源制限は外部サンドボックスに委ねる。未信頼コードは隔離環境でのみ実行する。
- 入力ファイルのみハッシュ化する。依存関係・インポート・ソース全体の証跡は別途固定する。

## v0.2: Counterexample-driven workflow
参考: https://zenn.dev/mizchi/articles/quint-application-modeling 。`references/application-modeling.md` と `templates/case.json` を使用し、モデル反例・実装再現・修正後再現を区別する。`python3 scripts/case_check.py path/to/case.json` は証跡の存在とハッシュを確認するだけで、意味論は認証しない。

Quint collector: `--quint-mode typecheck|test|run|verify`、`--quint-backend apalache|tlc`、`--seed`、`--samples` を追加。CLIの実バージョンでオプションを確認すること。TLCの有限全探索は探索完了を別途確認する。

`examples/async-counter/` は独自の最小サンプル。Python実装のRED/GREENは実行確認済み。`quint test` / `quint run` / `quint verify` で counter.qnt の反例と fixed.qnt の無違反を確認済みで、replay.py のイベント列はその反例トレースと一致する。既存の他バックエンドも引き続き利用できる。
