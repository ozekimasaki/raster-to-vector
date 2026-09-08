# 被覆保存と描画の選択

原文: WVR 1 §4–5,11–18、WVR 2 §3–10,12。WVRはプロジェクト内の名称。

## 最初に区別する量

coverageは画素のどの割合を覆うか、τは素材の不透明度。
面A/Bが互いに異なる半画素を覆っても、平均alphaをsource-overすると0.5+0.5(1-0.5)=0.75。
本当に同じ位置に重なる二つの半透明素材では0.75が正しい。
同じ数式でも空間的な意味が違うので、全パスをADDにしない。

## 非重複セルの条件付き積分

面Fiの内部が非重複、Kpが非負・正規化された共通フィルタ、色空間を明示、premultipliedで扱うとき:

```text
a_i,p = ∫ Kp(x) 1_Fi(x) τi(x) dx
c_i,p = ∫ Kp(x) 1_Fi(x) τi(x) Ci(x) dx
αp = Σ a_i,p ; cp = Σ c_i,p
0 ≤ αp ≤ 1
```

外周・穴ではα<1が正しい。clampで過剰を隠したり、総和を1へ正規化しない。
色域0..1のpremultiplied成分はalpha以下。違反は分類・重複・数値誤差を調べる。

実overlapをセル化する場合、背面→前面の素材について:

```text
αcell = 1 - Π(1-τj)
ccell = Σ τj Cj Π_{k>j}(1-τk)
```

一定paint・通常source-overの条件。gradientや非局所filterへ無条件に拡張しない。
汎用の透明arrangementは同梱コードにない。必要な局所構造を明示的に作るか未対応とする。

## Greenの定理と共有積分

box pixel Pと交差した閉領域Q=Fi∩Pについて A=1/2∮(x dy-y dx)。
直線edge寄与 J=1/2(x0 y1-y0 x1)。円弧中心(cx,cy),r,連続角[t0,t1]なら:

```text
J = 1/2 [r cx(sin t1-sin t0) + r cy(cos t0-cos t1) + r²(t1-t0)]
```

共有edgeのJを一度計算し、一方へ+J、他方へ-J。画素側の閉路片も必要。
元の曲線を単に積分するだけでは画素coverageにならない。
局所原点で数値安定性を上げ、穴の向き、接線、角通過、逆向き弧、複数成分を扱う。

アフィンpaint C=u+vx+wyの積分はuA+vMx+wMy。
Mx=1/2∮x²dy、My=-1/2∮y²dx。
gradient stop、非線形色変換、位置依存alphaの積は追加の分割や積分が必要。
この専用参照モデルを通常SVGレンダラーへ強制することはできない。

## 描画候補の採否

1. 通常source-overを基準にする。
2. 同paintのunion、根拠のある背後形、局所underlapを比較する。
3. 外形・穴・alpha・色のいずれかが悪化するなら戻す。
4. 非重複partitionだけ、各要素へ `mix-blend-mode:plus-lighter`、親へ `isolation:isolate` を試す。
5. 加算グループに不透明背景を入れない。外部背景との合成は通常の一回。
6. 白・黒・有彩色・透明、0.75/1/1.5倍、位相0/0.5px、inline/imgで検査する。
7. plus-lighterが使えない全面不透明キャンバスに限り、同じパスの crispEdges 下地＋通常AAを表示版だけで試す。外形・穴が悪化したら戻す。

`CSS.supports()`だけでは対応証明にならない。CairoのADD能力とCairoSVGのCSS解釈は別。
加算経路を実描画できない場合は未検証。見た目だけ似る別blendへ置き換えない。

## 自色下地と crispEdges 二重描画

不透明な隣接面の 25% 漏れを、ページ背景ではなく隣面の色で埋める発想は、WVR 1 §12.3 の正しい色の base fill の一般化である。

表示専用の形:

```svg
<g shape-rendering="crispEdges"><!-- 同じ不透明パス --></g>
<g><!-- 同じパスを通常AAで重ねる --></g>
```

`<use>` でパスを一度だけ書く書き方もあるが、同梱 `inspect-svg` は `use` を拒否する。`check` する表示版はパスを二重化する。

成立しない条件:

- 外形と穴。画素中心が内側なら下地が不透明になり、同じ色の AA は alpha を減らせない。
- `crispEdges` はヒント。AA が切れない描画器では二重 source-over になり、partition にならない。
- 半透明面の二度描き。素材 alpha が濃くなる。
- 三叉点。勝者は1色で、plus-lighter のような加算にはならない。
- 誤色の一枚下地。alpha が直っても色が `ab(CU-CA)` ずれる。

採否は内部継ぎ目と外形を分けて測る。対照は [two_rects_normal.svg](../examples/fixtures/two_rects_normal.svg)、[two_rects_plus-lighter.svg](../examples/fixtures/two_rects_plus-lighter.svg)、[two_rects_base_fill.svg](../examples/fixtures/two_rects_base_fill.svg)、[two_rects_crisp_aa.svg](../examples/fixtures/two_rects_crisp_aa.svg)。測定は `examples/experiments/wvr2/probe_crisp_aa.py`。

Chromium 151、倍率 0.75/1/1.5、位相 0/0.5px、背景4種の最大値（解析的 box coverage、encoded sRGB）。CairoSVG はこの環境では未測定。

| 手法 | 内部 alpha 欠損 | 内部色差 | 外周 alpha 過剰 |
|---|---:|---:|---:|
| 通常 source-over | 0.251 | 0.197 | 0.249 |
| isolated plus-lighter | 0.004 | 0.005 | 0.496 |
| 背面色 base fill | 0 | 0.004 | 0.499 |
| crispEdges + AA | 0 | 0.157 | 0.750 |

内部の 0.157 は二面 50/50 での `ab|CB-CA|`（約 40/255）に一致し、勝者面への色寄りである。外周 0.75 は被覆 0.25 の画素が不透明になった場合と一致する。plus-lighter と base fill の外周差は、既存の box 基準残差と同型で、crisp+AA の外形破壊とは別である。全描画器・全倍率の保証ではない。

## 再配色検査

幾何・alpha・順序を固定し、面iだけ白、他面は黒として基底測定する。黒を透明にしない。
線形モデル y=ΣwiCi で d=w-w* なら、最大色誤差=(||d||1+|Σd|)/2。
背景を含め総和が双方1なら1/2||d||1。
実レンダラーの量子化・clamp・色変換には非線形性がある。ランダム再配色も測る。
有限試験の最大差を全配色に対する数学的保証にしない。

代表負例: [誤った下地](../examples/fixtures/underlay_wrong.svg)、
[実overlapへの加算](../examples/fixtures/overlap_raw_plus-lighter.svg)。
どちらもalpha欠損の改善だけでは成功としない。
