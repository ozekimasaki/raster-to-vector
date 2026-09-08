# raster-to-vector

[English](README.md) | [日本語](README.ja.md) | **中文**

[![Validate](https://github.com/ozekimasaki/raster-to-vector/actions/workflows/validate.yml/badge.svg)](https://github.com/ozekimasaki/raster-to-vector/actions/workflows/validate.yml)
[![License: GPL-3.0](https://img.shields.io/badge/license-GPL--3.0-blue.svg)](LICENSE)
[![Agent Skills](https://img.shields.io/badge/spec-agentskills.io-6366f1)](https://agentskills.io/specification)

光栅 → 可编辑 SVG。WVR / CFV-X。输入：PNG / JPEG / WebP。

## 安装

```text
npx skills add ozekimasaki/raster-to-vector
```

| 对象 | 命令 |
|---|---|
| Cursor | `npx skills add ozekimasaki/raster-to-vector -g -a cursor -y` |
| Claude Code | `npx skills add ozekimasaki/raster-to-vector -g -a claude-code -y` |
| Codex | `npx skills add ozekimasaki/raster-to-vector -g -a codex -y` |
| 列表 | `npx skills add ozekimasaki/raster-to-vector --list` |

| 环境 | 路径 |
|---|---|
| Cursor | `~/.cursor/skills/raster-to-vector/` |
| Claude Code | `~/.claude/skills/raster-to-vector/` 或 `.claude/skills/` |
| Codex | `~/.codex/skills/raster-to-vector/` |
| claude.ai | 以本文件夹为根的 ZIP |

## 依赖

| 用途 | 文件 |
|---|---|
| Python | 3.10+ |
| 核心测量 | `requirements-core.txt` |
| 实绘比较 | `requirements-render.txt` |
| CFV-X / mosaic-draft curve | `requirements-cfvx.txt` |

```text
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements-render.txt
```

Chromium 在其他位置时设置 `CHROMIUM_PATH`。

## 用法

```text
把这张图转成 SVG
```

`SKILL_ROOT` = 本目录的绝对路径。

```text
python "SKILL_ROOT/scripts/r2v.py" doctor
python "SKILL_ROOT/scripts/r2v.py" analyze "input.png" --out "work/input"
python "SKILL_ROOT/scripts/r2v.py" check "input.png" --svg "result.svg" --out "work/check"
```

[SKILL.md](SKILL.md) / [运行环境与 CLI](references/runtime-and-cli.md)

## 测试运行

2026-09-08。平面插画，1024×1024，Chromium 152。行：白 / 黑 / 彩色。列：原图 / SVG / 4 倍差分。

![平面插画的原图、SVG 实绘与差分比较](_assets/glider-clipart.comparison.webp)

| 项目 | 结果 |
|---|---|
| 图像类型 | 平面插画 |
| 采用迭代 | `01` |
| SVG | 29,600 bytes，path 8，circle 6，区间 1,502 |
| 渲染 | Chromium 152.0.7977.82，source-over，inline |
| premul RGB MAE / RMSE | 0.01014 / 0.03270 |
| alpha 缺失 / 过量 | 无 |
| 质量判定 | indeterminate |
| 残差 | 眼睛与奶油面的 AA、枝干木纹 |

不授予输入剪贴画的再分发权。

## 收录内容

| 路径 | 内容 |
|---|---|
| `SKILL.md` | 面向代理的流程 |
| `references/` | 作业步骤、几何、覆盖、SVG、质量约定、CLI、mosaic-draft |
| `references/originals/` | CFV-X / WVR 1 / WVR 2 原文副本 |
| `scripts/` | 测量与检查 CLI |
| `vendor/cfvx/` | CFV-X 草稿路径 |
| `examples/` | sidecar 模板、反例 SVG、实验代码 |
| `tests/` | 单元 / 验收测试与验证记录 |
| `_assets/` | README 用比较图（`npx skills add` 会排除） |

`npx skills add` 排除 `README.md` 以及 `_` 开头的路径。

## 范围

| 包含 | 不包含 |
|---|---|
| 标志、图版、线稿、插画、照片 | 还原唯一的原始 SVG |
| 孔洞、圆弧、缝隙、透明度的区分 | 与未知的全部渲染器一致 |
| 照片区域候选与残差明示 | 把内嵌图像的 SVG 当作成功 |

## 验证

[tests/VALIDATION.md](tests/VALIDATION.md)

```text
python -m unittest discover -s tests -v
```

验收测试：`tests/acceptance.py`（Chromium、Shapely）。

## 许可

[GNU GPL-3.0](LICENSE)

- `examples/inputs/astronaut-256.png` — NASA / scikit-image，public domain
- `_assets/glider-clipart.comparison.webp` — 用户提供，不适用 GPL

[examples/inputs/attribution.md](examples/inputs/attribution.md) / [references/source-map.md](references/source-map.md)
