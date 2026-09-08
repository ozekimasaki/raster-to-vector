# 実行と負例

## ロゴを変換

依頼: 「このロゴの穴と丸い輪郭を保持してSVGにして」
analyze→目視→circle/pathと穴を構築→check→穴のalpha、輪郭を目視→納品。
円の全周はcircleまたは複数A。穴は背景色で塗り潰さず透明として保持する。

## 写真を変換

依頼: 「この写真をできるだけ忠実なSVGにして」
analyze→目視→32/64/128色候補→重要領域と陰影を選択→パス/gradient構築→check→局所改善。
色面候補だけを成果物にせず、細部と陰影の残差を記録する。写真から元SVGを回復したとは言わない。

## 素材半透明

依頼: 「重なった透明な円をSVGに」
元素材と前後関係を推定し、source-overを使う。0.5と0.5の実overlapが0.75になる意味を保つ。

## 負例の読み方

| fixture | 何を検出するか |
|---|---|
| underlay_wrong.svg | alpha欠損が消えても、下地の色寄与が誤る |
| per_shape_opacity_overlap.svg | 一様group opacityを個別opacityの重なりに変えるとalpha過剰 |
| overlap_raw_plus-lighter.svg | 本当の半透明overlapへADDを適用した誤り |
| intentional_gap.svg / intentional_slit_normal.svg | 意図された空白を穴埋めしてはいけない |
| base_fill.svg | 条件を満たす矩形・一定paintの対照例。万能修復ではない |
| two_rects_plus-lighter.svg | 非重複加算の小さな対照例。全描画器対応を意味しない |

原文の集計にある530描画測定等は全件成功数ではない。
実験は examples/experiments/。任意SVGの修復器として呼び出さない。
