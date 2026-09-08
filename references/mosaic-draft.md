# mosaic-draft

ラベルマップから共有境界グラフを作り、各辺を一度だけ fit して SVG にする。VTracer の mosaic パイプラインを参考にした再実装であり、VTracer 本体は依存しない。完成証明ではない。地位は `cfvx-draft` と同じ `draft_only`。

## 使うとき

フラットな色面が隣接するイラスト・図版の初期候補。ロゴの基本図形や写真の意味構造の代替ではない。

```text
python "SKILL_ROOT/scripts/r2v.py" mosaic-draft "input.png" --out "work/mosaic" --colors 22 --mode polygon
python "SKILL_ROOT/scripts/r2v.py" mosaic-draft "input.png" --out "work/mosaic" --from-labels "work/p64/labels.npy" --mode pixel
```

`--mode pixel` と `polygon` は numpy のみ。`curve` は vendor/cfvx の直線・円弧・三次を開いた共有辺へ載せる。scipy が無い、または逸脱が 0.5px を超える辺は polygon へ落とす。

## 取るもの

- 画素 `(x,y)` は単位正方形 `(x,y)..(x+1,y+1)`。境界は格子点 `0..W × 0..H`
- 透明と画像外は同じ `OUTSIDE`
- 次数 3 以上が接合点。チェッカーボード `A B / B A` は pinch（右優先 successor）
- 辺は一度だけ fit。逆向きは同じ数値の t→1-t
- 対称 Douglas-Peucker。片側 outset は使わない
- 逸脱予算の既定は 0.5px（`--tolerance`）
- `fill-rule="nonzero"`。領域を常に左に置く
- Pixel モードでは面を塗り戻してラベルと一致することを `draft-status.json` に書く

## 取らないもの

- VTracer / visioncortex の階層クラスタ、watershed、4-point spline
- stacked（穴を作らない重ね）。重ねは WVR の下地候補のまま
- 面積だけでの小領域削除
- 自動ドラフトを最終合格にすること
- 汎用 DCEL、円弧 arrangement、透明セル分割

## 4近傍

クラック境界は4近傍。対角接触は接合点で pinch し、対角線をまたがない。8近傍クラスタリングと混ぜない。

## 成果

`candidate.svg` / `shared-boundary.json` / `draft-status.json`

`area_matches_pixels` と `shared_coordinates_consistent` は格子グラフの検査。幾何が watertight でも、描画器は隣接パスを別々に AA するためヘアラインは残り得る。被覆の話は [被覆と合成](coverage-and-compositing.md) を読む。`check` で実描画する。
