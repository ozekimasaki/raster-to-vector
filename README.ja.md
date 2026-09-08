# raster-to-vector

[English](README.md) | **日本語** | [中文](README.zh.md)

[![Validate](https://github.com/ozekimasaki/raster-to-vector/actions/workflows/validate.yml/badge.svg)](https://github.com/ozekimasaki/raster-to-vector/actions/workflows/validate.yml)
[![License: GPL-3.0](https://img.shields.io/badge/license-GPL--3.0-blue.svg)](LICENSE)
[![Agent Skills](https://img.shields.io/badge/spec-agentskills.io-6366f1)](https://agentskills.io/specification)

Raster → 編集可能な SVG。WVR / CFV-X。入力は PNG / JPEG / WebP。

## インストール

```text
npx skills add ozekimasaki/raster-to-vector
```

| 対象 | コマンド |
|---|---|
| Cursor | `npx skills add ozekimasaki/raster-to-vector -g -a cursor -y` |
| Claude Code | `npx skills add ozekimasaki/raster-to-vector -g -a claude-code -y` |
| Codex | `npx skills add ozekimasaki/raster-to-vector -g -a codex -y` |
| 一覧 | `npx skills add ozekimasaki/raster-to-vector --list` |

| 環境 | 配置先 |
|---|---|
| Cursor | `~/.cursor/skills/raster-to-vector/` |
| Claude Code | `~/.claude/skills/raster-to-vector/` または `.claude/skills/` |
| Codex | `~/.codex/skills/raster-to-vector/` |
| claude.ai | このフォルダを最上位に持つ ZIP |

## 必要なもの

| 用途 | ファイル |
|---|---|
| Python | 3.10+ |
| コア測定 | `requirements-core.txt` |
| 実描画比較 | `requirements-render.txt` |
| CFV-X / mosaic-draft curve | `requirements-cfvx.txt` |

```text
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements-render.txt
```

Chromium が別場所なら `CHROMIUM_PATH`。

## 使い方

```text
この画像を SVG にして
```

`SKILL_ROOT` = このディレクトリの絶対パス。

```text
python "SKILL_ROOT/scripts/r2v.py" doctor
python "SKILL_ROOT/scripts/r2v.py" analyze "input.png" --out "work/input"
python "SKILL_ROOT/scripts/r2v.py" check "input.png" --svg "result.svg" --out "work/check"
```

[SKILL.md](SKILL.md) / [実行環境とCLI](references/runtime-and-cli.md)

## テスト稼働

2026-09-08。フラットイラスト、1024×1024、Chromium 152。行: 白・黒・有彩色。列: 原画像・SVG・4倍差分。

![フラットイラストの原画像・SVG実描画・差分比較](_assets/glider-clipart.comparison.webp)

| 項目 | 結果 |
|---|---|
| 画像種別 | フラットイラスト |
| 採用反復 | `01` |
| SVG | 29,600 bytes、path 8、circle 6、区間 1,502 |
| 描画 | Chromium 152.0.7977.82、source-over、inline |
| premul RGB MAE / RMSE | 0.01014 / 0.03270 |
| alpha 欠損・過剰 | なし |
| 品質判定 | indeterminate |
| 残差 | 目とクリーム面の AA、枝の木目 |

入力クリップアートの再配布権は付与しない。

## 収録内容

| パス | 内容 |
|---|---|
| `SKILL.md` | エージェント向け手順 |
| `references/` | 作業手順、幾何、被覆、SVG、品質契約、CLI、mosaic-draft |
| `references/originals/` | CFV-X / WVR 1 / WVR 2 の原文コピー |
| `scripts/` | 測定・検査 CLI |
| `vendor/cfvx/` | CFV-X ドラフト経路 |
| `examples/` | sidecar テンプレート、負例 SVG、実験コード |
| `tests/` | 単体・受け入れ試験と検証記録 |
| `_assets/` | README 用の比較画像（`npx skills add` では除外） |

`npx skills add` は `README.md` と `_` 始まりのパスを除く。

## 範囲

| 対象 | 対象外 |
|---|---|
| ロゴ・図版・線画・イラスト・写真 | 元 SVG の一意復元 |
| 穴・円弧・隙間・透明度の切り分け | 未知の全描画器との一致 |
| 写真の領域候補と残差の明示 | 画像埋め込み SVG を成功扱い |

## 検証

[tests/VALIDATION.md](tests/VALIDATION.md)

```text
python -m unittest discover -s tests -v
```

受け入れ試験: `tests/acceptance.py`（Chromium、Shapely）。

## ライセンス

[GNU GPL-3.0](LICENSE)

- `examples/inputs/astronaut-256.png` — NASA / scikit-image、public domain
- `_assets/glider-clipart.comparison.webp` — ユーザー提供、GPL 対象外

[examples/inputs/attribution.md](examples/inputs/attribution.md) / [references/source-map.md](references/source-map.md)
