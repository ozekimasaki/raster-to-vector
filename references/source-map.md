# 出典対応表

３資料の原文をoriginals/へ無変更で収録。以下のハッシュとsource-manifest.jsonでコピーを確認できる。
元資料は2026-09-08、CFV-X/WVR 1は版1.0、WVR 2は版0.2。

| 原文 | SHA-256 |
|---|---|
| `raster_to_vector_theory_review.md` | `c880c14b0116b41682e7e4cd8ea8c2eb3073abd64b6717f84240b021ea69aaf6` |
| `watertight_vector_reconstruction_spec.md` | `e3c9f7f756352e218d4d33e4dfedb640df713865047db02ff749554cebce4cc1` |
| `wvr2_coverage_conserving_design.md` | `b5925751e20911235e5384502854dec6003d9f0ddb3b8d9a94de746c37abf474` |

## 必要なときに読む原文

- [CFV-X](originals/raster_to_vector_theory_review.md): §3–6 精度・観測、§8–11 輪郭・円弧・共同最適化、§12 画素fit、§14 保証、§18.8 写真。
- [WVR 1](originals/watertight_vector_reconstruction_spec.md): §3 診断、§6–10 共有境界・端点・書き出し、§11–18 合成と表示条件、§23 受け入れ。
- [WVR 2](originals/wvr2_coverage_conserving_design.md): §4 加算の条件、§5 SVG候補、§6 セル化、§7–8 積分、§9 寄与率、§16 未実装。

## 主張の区別

既知事項: source-over、SVG、Greenの定理。元資料の一次出典を参照。
導出: 明示したbox filter・非重複・色空間などの条件で成り立つ数式。
限定実測: experiments/に収録した合成例と数式検算。任意画像の品質証明ではない。
未実装: 汎用DCEL、円弧arrangement、透明セル分割器、連続Hausdorff上界、精密逆描画。
追加設計: Skillの画像別ルーティング、補助CLI、保護領域記録、写真の候補比較、停止条件。
既存CFV-Xコード: vendor/cfvxへ無変更コピー。WVR 2の完成実装ではない。

## 公式Skill仕様

- https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview
- https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices

2026-09-08確認。name/description、命名・文字数、段階的読み込みに従う。
形式互換はClaude/Codexの両環境で実行済みという意味ではない。

## 再現コード

experiments/の各コードは元の合成実験で、任意SVG入力のツールではない。
再実行時は作業フォルダへコピーし、そこへ出力する。review_checks.pyは自分の隣に結果を書く。
古いハーネスの--no-sandboxは外部SVG処理へ流用しない。同梱r2vの描画経路は別実装。
本文とコードの公開ライセンスはリポジトリ直下の LICENSE（MIT）。
`examples/inputs/character.png` はユーザー提供フィクスチャで MIT の対象外。
`examples/inputs/astronaut-256.png` は NASA / scikit-image の public domain 画像。
