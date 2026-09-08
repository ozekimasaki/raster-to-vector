# raster-to-vector

[![Validate](https://github.com/ozekimasaki/raster-to-vector/actions/workflows/validate.yml/badge.svg)](https://github.com/ozekimasaki/raster-to-vector/actions/workflows/validate.yml)
[![License: GPL-3.0](https://img.shields.io/badge/license-GPL--3.0-blue.svg)](LICENSE)
[![Agent Skills](https://img.shields.io/badge/spec-agentskills.io-6366f1)](https://agentskills.io/specification)

Raster画像を観察し、WVR と CFV-X の理論に基づいて編集可能な SVG を構築する Agent Skill。

自動変換器を一度走らせて終わりにはしない。元画像と最終 SVG の実描画を見比べ、隙間・透明度・外形を局所修正する。

対応入力: PNG / JPEG / WebP（ロゴ、図版、線画、イラスト、写真）。

## インストール

```text
npx skills add ozekimasaki/raster-to-vector
```

特定のエージェントだけに入れる場合:

```text
npx skills add ozekimasaki/raster-to-vector -g -a cursor -y
npx skills add ozekimasaki/raster-to-vector -g -a claude-code -y
npx skills add ozekimasaki/raster-to-vector -g -a codex -y
```

入っている Skill を確認する:

```text
npx skills add ozekimasaki/raster-to-vector --list
```

`npx skills` は Cursor、Claude Code、Codex ほか対応エージェントへ配置する。手動コピーや ZIP アップロードもできる。

| 環境 | 配置先 |
|---|---|
| Cursor | `~/.cursor/skills/raster-to-vector/` |
| Claude Code | `~/.claude/skills/raster-to-vector/` または `.claude/skills/` |
| Codex | `~/.codex/skills/raster-to-vector/` |
| claude.ai | このフォルダを最上位に持つ ZIP をアップロード |

## 必要なもの

- Python 3.10+
- コア測定: `requirements-core.txt`（numpy, Pillow）
- 実描画比較: `requirements-render.txt`（Playwright / Chromium, CairoSVG）
- CFV-X ドラフト経路のみ: `requirements-cfvx.txt`

```text
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements-render.txt
```

`doctor` はモジュールに加え Chromium 起動と CairoSVG の import を確認する。ブラウザが別場所なら `CHROMIUM_PATH` を設定する。システム全体へパッケージを入れない。

## 使い方

エージェントに「この画像を SVG にして」と依頼する。Skill は観察記録 → 画像別の候補構築 → 実描画比較 → 局所修正の順で進む。

手動で補助 CLI を使う場合、`SKILL_ROOT` をこのディレクトリの絶対パスに置き換える。

```text
python "SKILL_ROOT/scripts/r2v.py" doctor
python "SKILL_ROOT/scripts/r2v.py" analyze "input.png" --out "work/input"
python "SKILL_ROOT/scripts/r2v.py" check "input.png" --svg "result.svg" --out "work/check"
```

詳細は [SKILL.md](SKILL.md) と [実行環境とCLI](references/runtime-and-cli.md) を読む。

## テスト稼働

2026-09-08、フラットイラスト（フクロモモンガのクリップアート、1024×1024、不透明な白キャンバス）を Chromium 152 で実描画比較した。

行は白・黒・有彩色背景、列は原画像・SVG 実描画・4倍差分。

![フラットイラストの原画像・SVG実描画・差分比較](_assets/glider-clipart.comparison.png)

| 項目 | 結果 |
|---|---|
| 画像種別 | フラットイラスト（少数の塗り、丸い部品、JPEG/AA の粒） |
| 採用反復 | `01`（`00` はクリーム面の欠け、`02` は目の楕円化で悪化） |
| SVG | 29,600 bytes、path 8、circle 6、区間 1,502 |
| 描画 | Chromium 152.0.7977.82、source-over、inline |
| premul RGB MAE / RMSE | 0.01014 / 0.03270 |
| alpha 欠損・過剰 | なし |
| 品質判定 | indeterminate（万能閾値は置かない） |

残差の主因は、画素化された目とクリーム面の AA に対する滑らかな円、枝の木目を単色に潰したこと。不透明キャンバスでは silhouette IoU=1 でも形の一致を意味しない。入力クリップアートの再配布権は付与しない。

## 収録内容

| パス | 内容 |
|---|---|
| `SKILL.md` | エージェント向け手順 |
| `references/` | 作業手順、幾何、被覆、SVG、品質契約、CLI |
| `references/originals/` | CFV-X / WVR 1 / WVR 2 の原文コピー |
| `scripts/` | 測定・検査 CLI |
| `vendor/cfvx/` | 既存 CFV-X の任意ドラフト経路 |
| `examples/` | sidecar テンプレート、負例 SVG、実験コード |
| `tests/` | 単体・受け入れ試験と検証記録 |
| `_assets/` | README 用の比較画像（`npx skills add` では除外） |

`npx skills add` は `README.md` と `_` 始まりのパスを除いてこのフォルダをコピーする。

## できること / しないこと

- ロゴ・図版の穴や円弧を保った SVG 構築
- 写真の領域候補比較と残差の明示
- 白い筋・隙間・透明度の切り分け
- 元 SVG の一意復元や、未知の全描画器との一致は主張しない
- 画像埋め込み SVG を成功の代替にしない

## 検証

2026-09-08 時点の記録は [tests/VALIDATION.md](tests/VALIDATION.md)。

```text
python -m unittest discover -s tests -v
```

Chromium と Shapely が必要な受け入れ試験は `tests/acceptance.py`。毎回の Skill 利用では走らせない。

## ライセンス

本文とコードは [GNU GPL-3.0](LICENSE)。改変して公開する場合は、同じ GPL-3.0 で公開する必要がある。

- `examples/inputs/astronaut-256.png` は NASA / scikit-image の public domain 画像
- `examples/inputs/character.png` と `_assets/glider-clipart.comparison.png` はユーザー提供フィクスチャで、GPL の対象外

出典の詳細は [examples/inputs/attribution.md](examples/inputs/attribution.md) と [references/source-map.md](references/source-map.md)。
