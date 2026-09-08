# SVG出力

## 基本

`xmlns`, `width`, `height`, `viewBox`を明示する。寸法は解析後の向きでの入力寸法。
色は作業sRGB、SVGはUTF-8。透明背景は背景rectを加えず維持する。
意味のあるg/idを付け、独立に編集すべきものを過度に結合しない。
外部画像、image、foreignObjectでラスターを隠さない。

共有頂点を同じ文字列表現で出力する。共有edgeの正逆生成も同じ数値から作る。
丸め精度を変えたらgeometryと実描画を再確認する。丸め桁数そのものは精度保証ではない。
全円はcircleまたは二つ以上のA。Aの半径補正、large-arc、sweep、y軸方向に注意。
パスの穴はevenoddか正しい向きを持つnonzeroで表し、再描画して確認する。
gradientUnitsとtransformを指定し、パーツ分割によるpaint座標の変化を避ける。

## 同梱描画器のサブセット

svg/g/defs、path、rect、circle、ellipse、line、polyline、polygon、
linearGradient/radialGradient/stop、clipPath、title/descを許可する。
ローカルgradient/clip参照だけを許可。use、text、style要素、filter、mask、image、foreignObject、
イベント属性、スクリプト、DTD/ENTITY、外部参照、CSS escapeを拒否する。
style属性は許可されたpresentation属性の平坦な宣言のみ。@importや任意CSSは使えない。
textはfontの実体に依存するので、同梱経路では輪郭化する。
この制限はSVG規格の制限ではなく、安全で再現しやすい同梱ツールの対応範囲。
未対応の合法SVGを不正なSVG規格違反と呼ばない。

## 構造版と表示版

result.svgにcanonical形状を残す。renderer固有調整を追加したらresult.display.svgへ分ける。
sidecarに元edge/shapeとの対応、調整理由、追加誤差、対象条件を保存する。
表示版が全SVGビューアで同じとは説明しない。

表示版の継ぎ目対策は次の順で試す。構造版へ描画ヒントや二重パスを入れない。

1. 非重複の不透明クラスタなら、isolated `plus-lighter` を Chromium で測る。
2. 二面・定色なら、背面色の base fill または directed underlap。
3. 同じ paint の隣接面は union。
4. plus-lighter が使えない全面不透明キャンバスに限り、同じパスの `shape-rendering:crispEdges` 下地＋通常AA重ねを候補にする。外形・穴のAAが壊れたら不採用。

`use` による一回定義は同梱検査の外。表示版を `check` するならパスを二重化する。
crisp 下地と plus-lighter は併用しない。半透明面を二重に描かない。

## 確認の境界

inspect-svgはXML、許可要素、参照、有限数値、path文法を検査する。
自己交差、位相、連続Hausdorff距離、正しい共有境界を自動証明しない。
SVGを再保存したらハッシュが変わるため再checkする。
