# WVR：SVGパーツ間の隙間を防ぐための理論・実装仕様
## CFV-X拡張 — 共有境界、円弧の端点拘束、重なり構造、描画時の被覆と色の整合性

**版：1.0**  
**作成・調査日：2026-09-08**  
**対象：円・円弧・直線・Bézierを用いる高精度Raster-to-Vectorエンジン**  
**成果物の位置づけ：設計仕様＋限定的な数式検算・実描画比較。製品全体の検証完了を意味しない。**

> 隙間を「見えなくする」のではなく、発生する工程を特定して取り除く。  
> そのために、幾何の接続、塗りの構造、最終レンダリングを別々に検証する。  
> 透明度の漏れを消すために、色・外形・意図された穴を壊してはいけない。

本書でいう **WVR（Watertight Vector Reconstruction）** は、このプロジェクト内の作業名である。既存の標準規格や、性能が確立された製品名ではない。

基礎資料『Raster to Vector 統合理論・技術レビュー／CFV-X』の第13章「位相・共有境界・描画の継ぎ目」と第15章「SVGへの書き出しと互換性」を、隙間対策のための実装可能な仕様へ展開する。[P0]

今回の出発点は「生成品質は上がったが、ときどきパーツ間に隙間が生じる」という観察である。**問題を起こした実際のSVG・元画像・実装コードは、本書の検証には使用していない。** したがって個別の不具合原因を断定せず、複数の原因を診断・修正できる方式を設計する。

### 記述の区分

- **仕様・既知事項**：一次資料に基づく。`[Sxx]`を参照する。
- **導出**：本書内の前提と数式から確認できる性質。
- **設計提案**：CFV-Xへの採用案。実装・評価が必要なものを含む。
- **限定実測**：添付スクリプトで実行した小規模な再現実験。

---

## 目次

1. [結論と採用する設計原則](#s01)
2. [前の提案で修正・厳密化する点](#s02)
3. [隙間の分類と切り分け](#s03)
4. [なぜ完全に接していても継ぎ目が出るのか](#s04)
5. [正しい基準描画と品質契約](#s05)
6. [共有境界グラフとデータモデル](#s06)
7. [領域推定から平面グラフを構築する](#s07)
8. [接合点と円弧を同時に拘束するフィッティング](#s08)
9. [位相を壊さない共同最適化](#s09)
10. [SVG書き出しで隙間を再発させない](#s10)
11. [領域分割と重なり表現を使い分ける](#s11)
12. [下地と塗り足しを正しく使う条件](#s12)
13. [三叉点・多領域接合の特別処理](#s13)
14. [塗り足し幅を表示条件から決める](#s14)
15. [半透明・グラデーション・clip・mask](#s15)
16. [出力モードと保証の境界](#s16)
17. [漏れ・色ずれ・外形を測る検証器](#s17)
18. [倍率・位相・背景・描画器のテスト行列](#s18)
19. [統合アルゴリズムと修復の採否](#s19)
20. [ログ・品質レポート・デバッグ契約](#s20)
21. [実行した数式検算と実描画比較](#s21)
22. [既存エンジンへの導入順序](#s22)
23. [商用品質の受け入れ条件](#s23)
24. [最終原則・実装チェックリスト](#s24)
25. [再現方法・ファイル構成](#s25)
26. [一次資料・基礎資料](#sources)

---

<a id="s01"></a>
## 1. 結論と採用する設計原則

### 1.1 問題は「フィット精度」だけではない

各パーツが基準輪郭から0.1px以内に入っていても、二つが反対方向へずれれば接触は失われる。逆に、共有境界の座標が完全一致していても、別々の塗りを画素単位で合成する過程で継ぎ目が出る場合がある。

したがって、円フィッティングの精度だけを高め続けても、全ての隙間は解決しない。

WVRは、品質を次の三層に分ける。

| 層 | 保つもの | 主な対策 |
|---|---|---|
| 幾何・位相 | 境界の一致、接合点、穴、隣接関係 | 共有境界グラフ、端点拘束、交差検証 |
| シーン・合成 | 塗り順、背後の形、透明度の意味 | 重なり構造の再構成、条件付きの下地 |
| 書き出し・描画 | 数値の同一性、透明度、境界色 | canonical serialization、再parse、実描画比較 |

### 1.2 中心となる五原則

**原則A：共有境界を二度生成しない。**  
隣接する二つの面は、一つの境界オブジェクトを逆向きに参照する。頂点・円弧・制御点・簡略化結果も共有する。

**原則B：接合点を後から寄せ集めない。**  
全ての接続曲線が同一の頂点変数を使い、フィット中からその位置を共有する。

**原則C：見えている領域と、描くべきレイヤーを同一視しない。**  
背景に円が重なった構造を、必ず「円形の穴が開いた背景＋円」に分解する必要はない。

**原則D：隙間を塞ぐ修正には色の保存条件も付ける。**  
不透明な下地を置くだけならalpha欠損は減らせるが、境界色を変える場合がある。

**原則E：最終SVGそのものを検証する。**  
内部幾何の検査だけでは足りない。書き出し、再読み込み、対象レンダラーでの描画まで通して判定する。

### 1.3 推奨パイプライン

```text
入力画像・透明度・既存の領域推定
    ↓
隣接関係／意図された穴／不確実領域の整理
    ↓
Canonical Vertex + Shared Boundary Graph
    ↓
接合点を拘束した円弧・直線・Bézierフィッティング
    ↓
位相・交差・領域の被覆を検証
    ↓
領域分割／重なり構造の候補を比較
    ↓
必要な場所だけ描画用の表現を修正
    ↓
決定的なSVG書き出し
    ↓
再parse・幾何・位相の検査
    ↓
倍率／位相／透明度／色／外形の描画検査
    ↓
SVG + 編集用構造 + 品質レポート
```

「輪郭を少し太らせる」は、この中の限定的な候補の一つであって、基本設計ではない。

---

<a id="s02"></a>
## 2. 前の提案で修正・厳密化する点

前の会話の方向性は維持するが、次の部分はそのまま製品仕様にしない。

| 前の表現・発想 | 厳密化した扱い |
|---|---|
| 新たに共有境界の層が必要 | 基礎資料にも存在する。今回は診断・実装・検証を具体化する |
| 同じ境界を参照すれば隙間は0 | 同一曲線を参照する区間の不一致はなくなる。平面全体の被覆や描画の継ぎ目は別に検査する |
| 全ての面が閉じていれば十分 | 閉じた面同士でも、重複・離隔・誤った穴・自己交差はあり得る |
| 下地は通常隠れるので安全 | 境界の部分被覆画素では下地色が寄与する。塗り色と順序に条件がある |
| 不透明ならoverlapしてよい | 外形・意図された穴・グラデーション・接合部の色まで保存する必要がある |
| 同じ色なら単純に結合できる | 同じ色値だけでなく、paintの座標系、alpha、filter、意味上の境界を確認する |
| 全内部画素のalphaを1にする | 半透明作品や意図された隙間では誤り。基準alphaとの差を測る |
| グループで囲めば継ぎ目は消える | グループ化だけでは、内部要素の被覆相関が自動的に保存されるとは限らない |
| 微小な穴は全て削除する | 小さな穴にも意味がある。由来と基準形状を確認せず削除しない |
| 一定幅を足せば全倍率で安全 | device pixelとの関係が変わる。対象倍率・変換・描画器を品質契約に含める |
| scale／phase sweepで保証できる | 試した条件の実測合格であり、未試験の連続する全条件への証明ではない |
| 隠れた円が復元できた | 観測と整合する潜在形状の仮説である。元の制作手順を一意に確定したわけではない |

**特に重要な修正は「alphaが埋まった」と「正しい見た目になった」を分けること。** 本書の限定実験でも、透明度欠損が0になりながら境界色がずれる例を確認した。第21章に条件と数値を記す。

---

<a id="s03"></a>
## 3. 隙間の分類と切り分け

### 3.1 五種類に分ける

| ID | 種類 | 典型的な原因 | 優先して調べるもの |
|---|---|---|---|
| G | 実際の幾何の隙間 | 独立fit、端点の不一致、別々の簡略化 | 連続境界・頂点・交差・被覆 |
| T | 位相の誤り | 小領域の脱落、誤った穴、接続判定の失敗 | 領域ラベル・隣接グラフ・穴 |
| S | 書き出しで生じた隙間 | 丸め、変換、円弧補正、fill-rule | export前後の幾何差 |
| R | 描画時の被覆欠損 | 要素ごとのAAとsource-overの相互作用 | 透明出力のalpha・倍率・位相 |
| C | 色の継ぎ目 | 誤った下地、順序、半透明、paint座標の変化 | alphaだけでなくRGBと基準描画 |

複数が同時に存在する場合もある。例えば0.03pxの本当の離隔と、AA由来の被覆欠損が同じ境界に重なる。

### 3.2 見た目だけで断定しない

「拡大しても見えるから幾何」「縮小時だけだからAA」という判断は、調査の手がかりにはなる。しかし、極細の実隙間も倍率次第で見えたり消えたりする。

また、白い線に見えていても、背景が漏れているとは限らない。元画像の白いハイライト、色混合の誤り、clipの縁である可能性もある。

### 3.3 最小診断手順

```text
1. 問題のSVGと、その直前の内部幾何を保存する
2. 同じ内部境界が本当に同一Edge IDを参照しているか確認する
3. SVGを再parseして、共有区間と端点を比較する
4. 透明背景へ描画し、境界付近のalphaを読む
5. alphaが正常でも、基準の境界色と比較する
6. 元画像の穴・半透明・輪郭線を欠陥として消していないか確認する
7. 別描画器とsubpixel位相で再現性を確認する
```

この診断を修復より先に行う。原因の異なる隙間へ一律の膨張処理を適用すると、別の破損を生みやすい。

### 3.4 デバッグ用に保存する段階

```text
source image / metadata
region labels / adjacency
raw shared graph
fitted shared graph
optimized shared graph
render plan
serialized SVG
reparsed scene
renderer outputs / difference metrics
```

各段階にrevisionとhashを付ける。「どの工程で境界が分かれたか」を追えることが、商用実装では重要になる。

---

<a id="s04"></a>
## 4. なぜ完全に接していても継ぎ目が出るのか

### 4.1 coverageと物体の透明度を分ける

ある画素の半分を、完全に不透明な赤い面が覆っているとする。

ここで0.5になるのは、その面の**画素内の被覆率**である。赤い素材自体の不透明度が0.5という意味ではない。

両者を最終的に一つのalphaへまとめると、画素内の「どこを覆っていたか」という情報が失われる場合がある。

### 4.2 二つの相補的な領域による反例

画素の左側をA、右側をBが覆い、実際には隙間がないとする。

$$
a+b=1
$$

AとBを別々に画素平均し、Aの上にBをsource-overすると、alphaは次になる。source-overの合成則はW3Cの定義を使用する。[S01]

$$
\alpha_{\mathrm{out}}
=
b+a(1-b)
=
1-ab
$$

したがって、背景が寄与する割合は、

$$
\ell=1-\alpha_{\mathrm{out}}=ab
$$

半分ずつの場合、

$$
a=b=\frac12
\quad\Rightarrow\quad
\alpha_{\mathrm{out}}=\frac34,\qquad
\ell=\frac14
$$

となる。

**完全に接する不透明な二面でも、個別平均のalphaを合成するモデルでは25%の背景寄与が生じる。**

これは「全レンダラーが常にこの通り」という主張ではない。被覆の相関を保持する実装なら異なる。ここでは、継ぎ目が発生する仕組みを示す反例として用いる。

### 4.3 色にも影響する

A、B、背景の色を、それぞれ $C_A,C_B,C_{\mathrm{bg}}$ とする。色は一つの明示した合成空間で扱う。

別々に画素平均して合成した色は、

$$
C_{\mathrm{actual}}
=
bC_B+a(1-b)C_A+abC_{\mathrm{bg}}
$$

本来の領域分割を画素内で積分した色は、

$$
C_{\mathrm{ideal}}
=
aC_A+bC_B
$$

したがって、

$$
C_{\mathrm{actual}}-C_{\mathrm{ideal}}
=
ab(C_{\mathrm{bg}}-C_A)
$$

となる。

背景が白ければ白っぽい線、黒ければ暗い線が現れ得る。ただし、出力が既に不透明な背景を内包している場合は、外部背景を変えても色の継ぎ目が変わらないことがある。

### 4.4 三領域以上でも起こる

独立した画素平均被覆率を $a_1,\ldots,a_n$ とすると、source-overを繰り返したときの背景寄与は、

$$
\ell_n=\prod_{i=1}^{n}(1-a_i)
$$

である。

実空間の領域分割として、

$$
\sum_{i=1}^{n}a_i=1
$$

でも、この積は一般に0にならない。

三領域がそれぞれ1/3を占めるモデルでは、

$$
\ell_3=\left(\frac23\right)^3=\frac8{27}\approx0.2963
$$

となる。多領域接合を、二面の境界と同じ処理だけで済ませない理由の一つである。

### 4.5 原因は積分と合成の順序

画素内位置 $x$ に対する二つの領域の指示関数を $m_A(x),m_B(x)$ とする。

隙間も重複もないなら、

$$
m_A(x)+m_B(x)=1,\qquad m_A(x)m_B(x)=0
$$

一方、平均値だけを先に求めると、

$$
E[m_A]E[m_B]=ab>0
$$

となり得る。

つまり、

$$
E[\operatorname{Composite}(m_A,m_B)]
\ne
\operatorname{Composite}(E[m_A],E[m_B])
$$

である。

**対策の理想形は、共通のサブピクセル位置で合成してから、画素へ積分すること。** ただし通常のSVGに異なる塗りのpathを列挙するだけでは、その計算順序を全ての描画器へ強制できない。

---

<a id="s05"></a>
## 5. 正しい基準描画と品質契約

### 5.1 四つの表現を分離する

| 記号 | 内容 |
|---|---|
| $G$ | canonicalな境界・頂点・面からなる幾何グラフ |
| $S$ | paint、透明度、塗り順、潜在形状を含むシーン |
| $E$ | 実際に書き出すSVGの要素・数値・構造 |
| $R_{r,T,b}(E)$ | 描画器 $r$、変換 $T$、背景 $b$ での出力 |

内部の $G$ が正しくても、$S$ の塗り順や $E$ の数値が間違えば品質は失われる。また、正しい $E$ でも描画条件によって差が生じる。

### 5.2 不透明な領域分割の契約

対象領域を $D$、各面を $F_i$ とすると、領域分割としては、

$$
\bigcup_iF_i=D
$$

かつ、面の内部同士は重複しない。

$$
\operatorname{int}(F_i)\cap\operatorname{int}(F_j)=\varnothing
\quad(i\ne j)
$$

画素内積分では、境界上の所属を一意に決める規則を使い、

$$
\sum_i\mathbf{1}_{F_i}(x)=\mathbf{1}_D(x)
$$

を、少なくとも面積に影響しない境界集合を除いて満たす。

これは**不透明なpartition層の条件**である。透明レイヤーの重なりやストロークへ、そのまま適用しない。

### 5.3 参照描画器の要件

参照描画では、各サンプル位置で以下を行う。

```text
1. 位置xが属する面／重なっているレイヤーを判定
2. 同じxでpaintと物体の透明度を評価
3. 同じxで前後関係に従って合成
4. premultiplied colorとalphaを画素へ積分
```

線形・正規化された非負のフィルタを $K_p(x)$ とすると、

$$
\hat c_p=\int K_p(x)c_{\mathrm{scene}}(x)\,dx
$$

$$
\hat\alpha_p=\int K_p(x)\alpha_{\mathrm{scene}}(x)\,dx
$$

とする。

単純なsupersamplingでも、**全ての面で同じサンプル位置を共有**することが重要である。ただし有限サンプルは近似なので、サンプル数を増やした収束確認、または積分誤差の上界評価が必要になる。

負の係数を持つ再標本化フィルタや、blurを含む場合は別の観測モデルを明記する。単純なcoverageの性質を無条件に流用しない。

### 5.4 元画像と理想描画を分ける

元画像自体にJPEGノイズ、ぼかし、白い輪郭、AAの継ぎ目が含まれることもある。

そのため比較対象を少なくとも二つ持つ。

- **観測基準**：入力画像へどれだけ一致するか。
- **構造基準**：採用した幾何・paint・合成モデルとして、どのように描かれるべきか。

入力のノイズを全て残すことと、理想的に継ぎ目のないSVGを作ることが衝突する場合は、その差を明示する。勝手に「入力の線は全部不具合」と解釈しない。

### 5.5 品質契約は対象範囲付きにする

```text
Input class:
  opaque flat illustration + explicitly identified alpha groups

Geometry reference:
  accepted shared boundary graph revision

Target renderers:
  named engines / versions / environment

Display transforms:
  scale range, selected rotations, device pixel ratio, phase cases

Tolerances:
  geometric distance, alpha deficit/excess, color difference, silhouette error

Failure behavior:
  fallback / warning / unmet / inconclusive
```

「全ての画像・全ての倍率・全てのSVGビューアで隙間が絶対にない」は、本書の保証対象にしない。

---

<a id="s06"></a>
## 6. 共有境界グラフとデータモデル

### 6.1 パーツ中心ではなく境界中心にする

避けたい構造：

```text
Face A → 独自の輪郭 → 独自のfit → 独自の簡略化
Face B → 独自の輪郭 → 独自のfit → 独自の簡略化
```

採用する構造：

```text
                 Canonical Edge AB
                       │
              ┌────────┴────────┐
              │                 │
          Face A: 正向き      Face B: 逆向き
```

CGALのarrangementで用いられるDCELは、頂点・half-edge・faceの接続関係を保持し、同じedgeの両方向をtwinとして扱う。本書はこの構造を基礎にする。[S06]

### 6.2 境界を「同じ数値」にするより「同じオブジェクト」にする

二つの配列へ同じ座標をコピーしただけでは、一方が更新されると再びずれる。

内部では単一の `EdgeId` を参照し、各faceが持つのは参照方向だけにする。派生値をキャッシュする場合も、geometry revisionを含めて失効管理する。

```ts
type VertexId = number;
type EdgeId = number;
type HalfEdgeId = number;
type FaceId = number;
type CircleId = number;
type PaintId = number;

type Vec2 = readonly [number, number];

interface Vertex {
  id: VertexId;
  position: Vec2;
  incidentEdges: EdgeId[];
  observationConfidence: number;
}

type CurveBody =
  | { kind: "line" }
  | {
      kind: "circularArc";
      circle: CircleId;
      sweep: "positive" | "negative";
      largeArc: boolean;
    }
  | { kind: "quadratic"; control: Vec2 }
  | { kind: "cubic"; control1: Vec2; control2: Vec2 };

type BoundaryRole =
  | "partition"
  | "occlusion"
  | "exterior"
  | "intentionalOpening"
  | "unresolved";

interface Edge {
  id: EdgeId;
  start: VertexId;
  end: VertexId;
  curve: CurveBody;
  leftFace: FaceId;
  rightFace: FaceId;
  role: BoundaryRole;
  geometryRevision: number;
}

interface HalfEdge {
  id: HalfEdgeId;
  edge: EdgeId;
  reversed: boolean;
  twin: HalfEdgeId;
  next: HalfEdgeId;
  prev: HalfEdgeId;
  face: FaceId;
}

interface Face {
  id: FaceId;
  outerLoops: HalfEdgeId[];
  holeLoops: HalfEdgeId[];
  paint: PaintId | null;
  semanticRole: "painted" | "transparent" | "unknown";
}

interface Circle {
  id: CircleId;
  center: Vec2;
  radius: number;
}
```

これは契約を説明する型であり、完成ライブラリではない。`next/prev` の整合、円弧と端点の一致、faceの向きなどは構築・更新時に検査する。

### 6.3 円のパラメータと端点を独立に動かさない

円弧edgeが `CircleId` と `VertexId` を参照する場合、次の制約が必要になる。

$$
\|V_0-C\|=r,\qquad \|V_1-C\|=r
$$

円中心・半径・両端点を別々の自由変数として更新して、最後に近くへ寄せる実装にはしない。

局所ソルバーでは第8章の端点拘束パラメータを使い、全体ソルバーでは共有円と頂点の制約を解く。更新結果は一つのtransactionとしてグラフへ反映する。

### 6.4 面の幾何と描画用形状は別データにする

隙間対策で背後の形を延長しても、canonicalなpartitionそのものを膨張させない。

```ts
interface RenderOperation {
  id: string;
  sourceFaces: FaceId[];
  paint: PaintId;
  geometryRef: string;
  zOrder: number;
  opacity: number;
  purpose: "original" | "baseFill" | "underlap" | "mergedFill";
}

interface RepairRecord {
  id: string;
  affectedEdges: EdgeId[];
  kind: "sharedFit" | "merge" | "baseFill" | "underlap" | "reorder";
  preconditions: string[];
  protectedFeatures: string[];
  geometryRevisionBefore: number;
  geometryRevisionAfter: number;
  validationStatus: "pending" | "passed" | "failed" | "inconclusive";
}
```

**編集用の正準幾何と、描画互換性のための派生表現を区別する。** そうしないと、修復を繰り返すほど元の形が太る問題が起きる。

### 6.5 不変条件

partitionグラフに対して、最低限次を検査する。

| 項目 | 条件 |
|---|---|
| Twin | `twin(twin(h)) == h` |
| Edge共有 | twin同士が同一edgeを参照する |
| 方向 | twin同士の参照方向が逆である |
| 閉路 | `next/prev` が整合し、faceのloopが閉じる |
| 端点 | 隣接half-edgeの終点と始点が同じVertex ID |
| 左右の面 | 方向とfaceの対応が矛盾しない |
| 交差 | 宣言されていない内部交差がない |
| 循環順序 | junction周りの面・edgeの順序が正しい |
| 被覆 | 採用した対象領域に未割当の隙間がない |
| 意図された空白 | transparent face・穴を勝手に消していない |

一般のDCELは孤立頂点や同じfaceを両側に持つedgeも表現できる。本書の「塗り面のpartition」と、独立ストロークのグラフを分けて、用途に合った制約を適用する。

---

<a id="s07"></a>
## 7. 領域推定から平面グラフを構築する

### 7.1 最初のラベル画像を完全な割当にする

領域推定の結果に、どのラベルにも属さない画素が残ると、その穴を正確にベクトル化してしまう。

入力の状態を次のように明示する。

```text
Painted region
Intentional transparent region
Exterior
Uncertain / unresolved region
```

「unknown」を自動的に背景へ変換しない。解決できない領域は、曖昧さを保持したまま局所候補を比較する。

### 7.2 画素間境界を一度だけ抽出する

隣接する画素のラベルが異なる場所に、境界候補を一つだけ作る。

```text
左ラベル = A
右ラベル = B
    ↓
Boundary key = unordered(A, B) + connected boundary identity
```

ただし、同じA/Bの組に複数の離れた境界成分があるので、ラベル対だけをedge IDにしてはいけない。接続成分・位置・端点も識別する。

輪郭の座標補正やsubpixel推定も、この共有境界に対して行う。

### 7.3 2×2の曖昧な配置を特別扱いする

例えば、

```text
A B
B A
```

というラベル配置では、A同士を接続するか、B同士を接続するか、四領域が接するかが一意でない場合がある。

対処方針：

```text
局所色・alpha・周辺境界・元画像の連続性を使う
    ↓
複数の接続仮説を作る
    ↓
観測整合と全体の接続関係で選ぶ
    ↓
確信が足りなければunresolvedとして残す
```

4近傍と8近傍を工程ごとに無自覚に切り替えない。細い穴や接触が壊れる原因になる。

### 7.4 接合点を検出して境界chainへ分ける

通常の二面境界をchainとして追跡し、次で分割する。

- 三領域以上が接するjunction。
- 角・尖点・意図された不連続。
- 外周との接続。
- 交差・接触を表す明示的な頂点。
- 閉じた曲線に必要な人工的な基準点。

閉じた円にjunctionがない場合も、処理上の基準点を挿入してよい。ただしそれを「観測された角」として扱わない。

### 7.5 小領域を消す処理を監査する

色量子化、ノイズ除去、領域統合の各工程は、細いパーツを消し得る。

サイズだけで削除を決めず、次を保存する。

```text
削除・統合された領域ID
元の面積
隣接先
色・alpha差
細線／穴／ハイライトの可能性
処理前後の観測誤差
```

隙間対策は「小さな空白を全部埋める」ことではない。実際に必要な隙間を残せることも品質である。

### 7.6 初期グラフの検証をfitの前に行う

初期の領域ラベルとグラフが不整合なら、幾何フィットへ進まない。

この段階では、精緻な円弧である必要はない。まず折れ線でもよいので、接続・穴・面の所属が正しい状態を作る。

---

<a id="s08"></a>
## 8. 接合点と円弧を同時に拘束するフィッティング

### 8.1 Canonical Junction

三つの境界が接する場合、三つの端点を後から近づけるのではなく、

$$
C_{AB}(t_{AB})=C_{BC}(t_{BC})=C_{CA}(t_{CA})=V
$$

という一つの頂点 $V$ を使う。

頂点の観測位置に不確実性があるなら、全体ソルバー内で $V$ を動かしてよい。ただし動かすときは全ての接続edgeを同時に更新する。

### 8.2 二つの端点を厳密に通る円のパラメータ化

異なる二点 $P_0,P_1$ を固定する。

$$
d=P_1-P_0,\qquad L=\|d\|
$$

$$
m=\frac{P_0+P_1}{2}
$$

$d/L$ に直交する単位法線を $n$ とする。両端を通る円の中心は、垂直二等分線上にある。

$$
c(h)=m+hn
$$

$$
r(h)=\sqrt{\left(\frac L2\right)^2+h^2}
$$

すると全ての $h$ について、

$$
\|P_0-c(h)\|=\|P_1-c(h)\|=r(h)
$$

である。

これにより、中心2変数＋半径を自由にfitして端点をずらす代わりに、**端点を守った1変数の円候補**を探索できる。

### 8.3 フィットの目的関数

輪郭観測点を $Q_i$ とすると、

$$
e_i(h)=\|Q_i-c(h)\|-r(h)
$$

$$
E(h)=\sum_i w_i\,\rho(e_i(h))
$$

を最小化する。$w_i$ は観測信頼度、$\rho$ は外れ値に頑健な損失の候補である。

$Q_i\ne c(h)$ では、

$$
\frac{\partial e_i}{\partial h}
=
-\frac{(Q_i-c(h))\cdot n}{\|Q_i-c(h)\|}
-\frac{h}{r(h)}
$$

となる。

ただし、これは支持円への残差である。採用する**有限円弧区間**への距離・角度の順序・端点付近の逸脱も別に確認する。支持円に近い点が、採用した円弧上にあるとは限らない。

### 8.4 直線に近い場合はsagittaを使う

円弧の中点付近で、弦から法線方向へのふくらみを $q$ とする。

$$
Q_{\mathrm{mid}}=m+qn
$$

この点と両端を通る円について、

$$
h=\frac q2-\frac{L^2}{8q}
\qquad(q\ne0)
$$

となる。

短いminor arcの範囲では、曲率の大きさは、

$$
|\kappa|=\frac{8|q|}{L^2+4q^2}
$$

と書ける。

$q\to0$ で、中心・半径は巨大になる一方、曲線は直線へ近づく。したがってソルバー内では $q$ または曲率を主変数として扱い、不要に巨大な中心を演算しない構成が考えられる。

**注意**：中心を計算する上式自体は $q=0$ で発散する。直線極限を別branchとして扱う必要がある。曲線評価にも、大きな数同士の差を避ける表現を用いる。

major arcや半円をまたぐ区間ではbranchを明示する。曖昧な場合は区間を分割する。

### 8.5 フォールバックの順序

```text
端点拘束付きの直線／円弧
    ↓ 誤差・安定性・接続条件を満たさない
短い区間へ分割
    ↓
楕円弧／Bézierなど、端点を守れる候補
```

円に固執してjunctionを動かしたり、微小な直線で穴を塞いだりしない。元の忠実度と接続を守るための自由曲線フォールバックは必要である。

### 8.6 接線連続とパラメータ連続を混同しない

滑らかにつながるべき二つの曲線では、共通端点を通る **C0** に加え、接線方向が一致する **G1** を検討する。

パラメータ微分の大きさまで一致する **C1** は、G1より強い条件である。SVGの見た目を滑らかにする目的なら、まずG1の意味で考える。

円弧同士の接線方向だけでなく曲率まで等しくする条件を無条件に付けると、表現できる形を過度に制限する。角を含む輪郭や三叉点の全incident edgeへ、同じ接線を要求しない。

### 8.7 Junctionを含む共同最適化

概念上の問題は、

$$
\min_{\Theta,V}
\sum_e E_e(\Theta_e,V)
+\lambda_{\mathrm{obs}}\sum_j E_{\mathrm{vertex},j}(V_j)
$$

subject to

$$
C_e(0)=V_{\mathrm{start}(e)},\qquad
C_e(1)=V_{\mathrm{end}(e)}
$$

$$
\text{accepted topology is preserved}
$$

である。

「接合点からの距離を小さくするpenalty」だけでは、有限のpenalty重みで微小な穴が残り得る。共有変数または明示制約として扱う。

---

<a id="s09"></a>
## 9. 位相を壊さない共同最適化

### 9.1 共有境界でも、動かし方を誤ると壊れる

一つのedgeを両面が共有していても、そのedgeが他の非隣接edgeを横切れば、面の所属や穴の数が変わる。

したがって「共有している」は必要な構造だが、平面埋め込みの正しさを単独では保証しない。

### 9.2 保護すべき量

```text
領域の隣接
意図された透明領域
穴の数と所属
細いパーツの幅
非隣接境界との距離
junction周辺のedgeの循環順序
外周の位置
```

Euler特性だけでは、これら全てを検査できない。

平面グラフで外側faceを含め、連結成分数を $C$ としたときの

$$
V-E+F=1+C
$$

は整合性チェックの一つにできる。しかし、これを満たしていても誤った隣接関係はあり得る。

### 9.3 位置の許容帯と交差検査を併用する

各境界の周囲に、基準輪郭から外れてよい範囲を定義する。

非隣接の保護境界が近い場所では、この許容帯を狭くする。例えば十分な分離がある区間では、局所最小距離の一部を移動上限とする方式が考えられる。

ただしjunction近傍では境界間距離が0になる。そこでは単純な距離制約ではなく、incident edgeの順序・局所sector・交差状態を検証する。

### 9.4 頑健な幾何判定

ほぼ接する線・円弧・曲線では、浮動小数点の丸めが接続判定を反転させ得る。

orientationやincircleに対するadaptive precisionの手法は、こうした頑健な判定の基礎になる。[S07]

ただし、直線用の頑健な述語を導入しただけで、任意の円弧やBézierの交差演算が全て厳密になるわけではない。曲線種別に対応したintersection・arrangement・interval処理が必要である。[S06]

### 9.5 更新は検証付きtransactionにする

```text
現行の合格状態を保持
    ↓
共同最適化の候補更新
    ↓
端点・交差・face・穴・外形を検査
    ↓
合格ならcommit
不合格ならrollback
```

誤差最小化器が提案した更新を、そのまま全て採用しない。

### 9.6 トポロジーを変える必要がある場合

元の領域推定が誤っていると、正しい形へ直すために位相変更が必要なこともある。

その場合は、幾何ソルバーの副作用として変えるのではなく、

```text
旧位相仮説
新位相仮説
変更理由
入力との比較
消える／増える領域・穴
```

を明示した離散候補として比較する。

---

<a id="s10"></a>
## 10. SVG書き出しで隙間を再発させない

### 10.1 書き出し後のSVGは別の検証対象

内部で同一edgeを参照していても、SVGには複数のpathへ数値を展開することが多い。

その際に各faceが独自に、

```text
丸め
円弧からBézierへの変換
簡略化
相対座標化
transformの焼き込み
```

を行うと、共有性を失う。

### 10.2 Canonical Serialization

まず頂点とedgeの数値表現を一度だけ確定する。

```text
Vertex ID → canonicalな座標文字列
Edge ID   → canonicalな曲線コマンド列
```

各faceはその表現を正向き／逆向きに組み合わせる。丸め済みの値をさらに別工程で再丸めしない。

### 10.3 逆向きの曲線を正しく生成する

三次Bézierの制御点列が、

$$
(P_0,P_1,P_2,P_3)
$$

なら逆向きは、

$$
(P_3,P_2,P_1,P_0)
$$

である。

円弧では始点・終点を入れ替え、同じ座標系内で半径と回転角を保持し、通常は同じlarge-arc flagでsweep flagを反転する。退化円弧・完全な円・座標系反転は特別処理する。[S04][S05]

同じ境界を「もう一度fitして逆向き版を作る」のではない。

### 10.4 SVGの円弧補正に注意する

SVGの `A` は、端点・半径・回転・flagで円弧を指定する。

半径が端点間距離に対して小さすぎる場合は、仕様の半径補正が働く。丸めによって新しく補正が発生すると、想定していた曲線からずれる場合がある。[S05]

したがって、

```text
内部円弧
    ↓
丸め済みA command
    ↓
SVGの規則で再構成
    ↓
共有性と基準曲線との差を検査
```

とする。

完全な円を、始終点が同じ一つの `A` だけで表さない。独立した円なら `<circle>`、複合pathの一部なら複数の円弧へ分ける。[S04]

### 10.5 Transformの扱いを統一する

同じ見かけの座標でも、別の親transformを持つ二面は、端点の評価や丸めの経路が異なる。

可能なら、共有境界を持つ面は共通の座標系と親transformへまとめる。

非一様scaleを焼き込むと円が楕円になる。反転変換では向きの扱いも変わる。viewBox、CSSサイズ、device pixel ratioを含めて、実効変換を記録する。[S08]

### 10.6 `Z` は穴埋め処理ではない

SVGの塗りでは開いたsubpathが閉じたものとして扱われることがあるが、閉じる辺は意図した曲線とは限らない。[S04]

欠落した円弧の代わりに `Z` が直線の弦を作ると、閉じたpathなのに元形状から大きく外れる。

全てのfaceは、書き出し前から意図した境界loopを持たせる。

### 10.7 fill-ruleと穴

`nonzero` と `evenodd` を混在させたり、loopの向きを一部だけ反転したりすると、穴の見え方が変わる。[S03]

複合pathの穴は、採用したfill-ruleで再parse・再描画して検査する。「微小な白い部分だから消す」という後処理へ回さない。

### 10.8 外部optimizerを通したら再検証する

SVG minifierや編集ソフトが、丸め・pathの再構成・curve conversionを行う可能性がある。

本書では特定製品の挙動を前提にせず、**成果物が変わったら品質レポートを再生成する**契約にする。

canonical graphの共有制約は、一般のSVGエディタへ自動的に引き継がれるものではない。必要ならsidecarを保持し、編集後に再構築する。

---

<a id="s11"></a>
## 11. 領域分割と重なり表現を使い分ける

### 11.1 Visible RegionとLatent Shape

画像で見える領域と、実際に描く形は一致しなくてもよい。

例えば、

```text
画像として見える領域
  背景の可視部分 + 円

描く構造の候補
  A. 円形の穴を開けた背景 + 円
  B. 穴のない背景 + その上の円
```

不透明なフラット色なら、Bの方が内部境界の描画を扱いやすいことがある。

ただし「Bが元の制作方法だった」とは断定しない。これは同じ見た目を説明するシーン仮説、または描画向けの表現変換である。

### 11.2 境界の種類

| 種類 | 意味 | 基本方針 |
|---|---|---|
| Partition | 面を分ける境界 | canonical edgeを共有 |
| Occlusion | 前景が背景を隠す境界 | 背景形状の継続を候補にする |
| Exterior | 作品と外部の境界 | 原則として位置・alphaを保護 |
| Intentional opening | 穴・隙間・切り抜き | 自動の塗り足し対象から外す |
| Unresolved | 根拠が足りない境界 | 複数仮説を比較し、強制修復しない |

T字接合や円弧の連続性は遮蔽仮説の手がかりにはなるが、それだけで前後関係を確定しない。

### 11.3 円フィッティングとの接続

離れた可視円弧が同じ支持円に整合する場合、完全な円を潜在形状として提案できる。

```text
visible arc 1
visible arc 2
    ↓
shared circle hypothesis
    ↓
hidden completion candidate
    ↓
全シーンを再描画して比較
```

採用条件は、可視領域・alpha・色・外形を壊さないこと。隠れているように見える領域でも、前景が半透明なら後ろの形が見た目へ寄与する。

### 11.4 Visible-edge Ownership

描画表現で一つの内部境界を作る要素を、明示的に決める。

```text
canonical edge e
    ↓
owner = foreground shape
background shape = 必要な範囲だけ背後へ継続
```

前景側の境界はcanonical geometryを保つ。背後のshapeに不要な切り抜きを作らない。

ただし、全edgeについて選んだownerが一つの塗り順と整合するかを確認する。

```text
A is behind B
B is behind C
C is behind A
```

のような循環が生じた場合、単一のグローバルz-orderでは表せない。その場所のshapeを分割する、局所clusterで別表現を使う、partition表現を維持する、といった候補へ切り替える。

### 11.5 「画素内で隠れている」の条件

幾何的に前景の内側に入っただけでは、前景のAA遷移画素で完全に隠れるとは限らない。

二つを区別する。

1. **完全遮蔽領域**：対象描画条件で、修正が影響するサンプル／画素が前景に完全に覆われる。
2. **境界遷移領域**：前景の被覆率が0と1の間になり、背後のpaintが境界色に寄与する。

後者での下地変更には、第12章の色保存条件が必要になる。

### 11.6 関連実装との関係

VTracerの調査時点のREADMEには、stacking方針と、1.0のcutoutにおける共有境界・gapless tessellationが説明されている。[S11]

これは「共有境界」と「重なり表現」を分けて扱う設計の参考になる。一方、その記述だけから、全ての描画器・透明度・倍率で本書の色誤差条件まで満たすとは判断しない。

---

<a id="s12"></a>
## 12. 下地と塗り足しを正しく使う条件

### 12.1 対策を三つに分ける

| 対策 | 内容 | 適用を検討する条件 |
|---|---|---|
| Same-paint union | 同じpaintの隣接面を一つの塗りへまとめる | 意味・alpha・paint関数・効果が等価 |
| Base fill | 対象clusterの下を一つの適切なpaintで覆う | 透明度と色の保存条件を確認できる |
| Directed underlap | 背後の形だけを前景の下へ延長する | owner、保護領域、必要幅を確定できる |

全パーツを一律に膨張させる方式とは区別する。

### 12.2 同じpaintのunion

同じ色の隣接面を別々にAAして描くと、内部境界にalpha欠損が出る場合がある。union後に一つの塗りとして描けば、その人工的な内部境界を取り除ける。

ただし次を確認する。

```text
同じ色・不透明度か
同じ座標位置で同じpaint値を返すか
内部の輪郭線を消してよいか
filterやclipの意味が変わらないか
編集上の部品IDを別途保持できるか
```

同じgradient IDを参照していても、`objectBoundingBox`の違いでpaintの見え方が異なる場合がある。色値の一致だけでunionを決めない。

### 12.3 二面・一定色におけるbase fillの性質

不透明な二つの一定色領域A/Bが、画素を隙間なく分割しているとする。

$$
a+b=1
$$

この画素全体へ $C_A$ を不透明に塗り、その上へ被覆率 $b$ のBを描くと、

$$
C_{\mathrm{base}}
=
bC_B+(1-b)C_A
=
bC_B+aC_A
$$

$$
\alpha_{\mathrm{base}}=1
$$

である。

つまり、**一定色のAを正しい下地にする限り、この二面・完全被覆のモデルでは、alphaと理想境界色の両方を保存できる。**

成立条件は重要である。

- 対象画素はclusterの外周AAではなく、内部にある。
- 下地が画素全体を不透明に覆う。
- Bが通常のsource-overで描かれる。
- 下地色がAの正しい色である。
- paint変動・filter・blendなど、追加の相互作用がない。

### 12.4 最小SVG例

境界がdevice pixelの途中に来る可能性を含む例：

```svg
<!-- 別々のcutout面 -->
<svg xmlns="http://www.w3.org/2000/svg"
     width="64" height="64" viewBox="0 0 64 64">
  <g transform="translate(0.5,0.5)">
    <path fill="#c4354d" d="M8 8H32V56H8Z"/>
    <path fill="#2469c8" d="M32 8H56V56H32Z"/>
  </g>
</svg>
```

二面・一定色の条件を満たすときの表現候補：

```svg
<!-- Aをcluster全体の下地とし、Bを上へ描く -->
<svg xmlns="http://www.w3.org/2000/svg"
     width="64" height="64" viewBox="0 0 64 64">
  <g transform="translate(0.5,0.5)">
    <path fill="#c4354d" d="M8 8H56V56H8Z"/>
    <path fill="#2469c8" d="M32 8H56V56H32Z"/>
  </g>
</svg>
```

これは内部境界を説明する例である。cluster外周における色やAAまで一般的に等価と保証する例ではない。外周は別途検査する。

### 12.5 任意色のunderlayは色を変える

不透明な下地色を $C_U$ とし、その上にA、さらにBを別々に描くと、

$$
C_{\mathrm{underlay}}
=
bC_B+(1-b)\left[aC_A+(1-a)C_U\right]
$$

$a+b=1$ なら、

$$
C_{\mathrm{underlay}}-C_{\mathrm{ideal}}
=
ab(C_U-C_A)
$$

となる。

したがって、

$$
C_U=C_A
$$

でなければ、alphaが1になっても境界色は一般に変わる。

前の提案にあった「下地は通常隠れるから任意の近い色でよい」という理解は採用しない。**AA遷移画素では、下地は実際に見た目へ寄与する。**

### 12.6 細いstrokeを下に引く場合

共有境界に沿ってstrokeを引く方式は、次の意味では候補にできる。

```text
背後のpaintを境界付近へ継続する
```

ただし、無条件な「隙間隠しの線」にはしない。

確認項目は、paint、塗り順、strokeの半幅、端部、join、junction、外周からの距離、穴、拡大縮小、透明度である。

特に `stroke-width = w` は中心線の両側へ概ね $w/2$ ずつ広がる。必要な塗り足し幅 $\delta$ とstroke-widthを取り違えない。joinやcapが作る追加領域も検査する。[S03]

### 12.7 修正支持領域を制限する

修正の許可領域を $M_{\mathrm{allow}}$、意図された穴・外周・保護要素を $M_{\mathrm{protect}}$ とする。

修正領域 $M_{\mathrm{repair}}$ は、

$$
M_{\mathrm{repair}}\subseteq M_{\mathrm{allow}}
$$

$$
M_{\mathrm{repair}}\cap M_{\mathrm{protect}}=\varnothing
$$

を満たす必要がある。

この幾何条件に加え、描画による影響範囲も確認する。filterやblurがあると、修正の影響は幾何領域の外へ広がる。

### 12.8 推奨する適用順位

```text
1. 根本の幾何／位相／書き出し不整合を直す
2. 同じpaintの不要な内部境界をなくす
3. 根拠のある重なり構造を使う
4. 二面など条件を確認できる場所だけbase fill / underlap
5. 多領域接合をcluster単位で再評価
6. 色・alpha・外形のいずれかが未達なら修正を撤回する
```

---

<a id="s13"></a>
## 13. 三叉点・多領域接合の特別処理

### 13.1 alphaを埋めても正しい色とは限らない

次の三領域を考える。

```text
上半分：A
左下：B
右下：C
```

一つの画素での面積比を、

$$
a=\frac12,\qquad b=\frac14,\qquad c=\frac14
$$

とする。

理想色は、

$$
C_*=\frac12C_A+\frac14C_B+\frac14C_C
$$

である。

### 13.2 単純な三段重ねによる反例

次の順で描く。

```text
1. Aで全体を塗る
2. 下半分をBで塗る
3. 右下をCで塗る
```

幾何学的には同じ領域分割である。しかし、それぞれのcoverageを先に画素平均するモデルでは、

$$
C_{\mathrm{layer}}
=
\frac14C_C+
\frac34\left(\frac12C_B+\frac12C_A\right)
$$

$$
=
\frac38C_A+\frac38C_B+\frac14C_C
$$

となる。

alphaは1でも、

$$
C_{\mathrm{layer}}-C_*
=
\frac18(C_B-C_A)
$$

という色誤差が残る。

つまり、**完全な不透明下地は背景漏れには効いても、多領域接合の正しい色まで自動的には保証しない。**

### 13.3 Junction Patchを独立した検証単位にする

junctionごとに、その周囲のedge・face・paintを含むpatchを作る。

```text
JunctionPatch
  canonical vertex
  incident edges
  adjacent faces
  cyclic order
  possible paint orders
  intentional holes
  protected silhouette
  renderer footprints
```

半径は固定のSVG unitだけで決めず、対象描画器・倍率のAA影響範囲を含める。

### 13.4 候補生成

patchに対し、次を候補として比較する。

```text
共有境界のまま描く
同じpaintの面を結合する
塗り順を変える
背後のshapeの継続範囲を変える
局所的にshapeを分割する
異なるbase fill構成を使う
```

一つの候補が全てのjunctionへ使えるとは仮定しない。

### 13.5 三叉点だけ小さな円で埋めない

接合点に小さな円や三角形を追加する修正は、alphaを埋めることはあっても、余計な色斑点や細部の潰れを作る。

使う場合でも、paintの由来・可視影響・対象倍率を記録し、基準描画との色差を検証する。単なる「穴の面積が小さいから許容」では採用しない。

### 13.6 参照描画と標準SVGを混同しない

共通サブピクセルで面の所属を決める参照描画器なら、多領域接合の理想積分を計算できる。

一方、標準SVGの出力は対象レンダラーで別途評価する。参照描画器で綺麗に見えることを、そのまま配布SVGの品質証明にはしない。


### 13.7 直交する三領域では塗り順の変更が有効な例がある

上半分A、左下B、右下Cという同じ可視領域を、次の順で描く候補を考える。

```text
1. Bでcluster全体を塗る
2. 右半分全体をCで塗る（上側は後でAに隠れる）
3. 上半分全体をAで塗る
```

画素内の上側被覆率を $u$、右側被覆率を $v$ とすると、この塗り順では、

$$
C=uC_A+(1-u)\left[vC_C+(1-v)C_B\right]
$$

となる。

水平・垂直境界を、軸方向に分離可能なbox filterで評価する一定色の例では、これは理想の面積積分に一致する。半分ずつなら、

$$
C=\frac12C_A+\frac14C_C+\frac14C_B
$$

を得る。

本書のCairoSVG／Chromiumによる限定実験でも、この候補は単純な三段重ねより小さい内部色誤差となった。

**一般の曲線・斜め境界・非分離フィルタで、同じ因数分解が成立するとは限らない。** ここから採用するのは「junctionでは塗り順と潜在形状を組にして探索する」という方針であり、この一つの順序を全ての接合点へ固定することではない。


---

<a id="s14"></a>
## 14. 塗り足し幅を表示条件から決める

### 14.1 単位を分ける

| 記号 | 単位 | 意味 |
|---|---|---|
| $\delta_u$ | user unit | SVG内の塗り足し半幅 |
| $\delta_d$ | device pixel | 実際の表示面での半幅 |
| $M$ | 線形変換 | user座標からdevice座標への変換部分 |
| $n$ | 単位ベクトル | user座標での境界法線 |

CSSの1pxとdevice pixelが同一とは限らない。viewBox、CSSサイズ、device pixel ratio、親transformを含めて変換を求める。[S08]

### 14.2 一様scale

一様scaleを $s>0$ とすると、

$$
\delta_d=s\delta_u
$$

したがって、

$$
\delta_u=\frac{\delta_d}{s}
$$

である。

固定のSVG幅は、縮小表示では十分なdevice幅にならないことがある。

### 14.3 非一様scale・shear

局所的に直線とみなせる境界の法線が $n$ で、$M$ が可逆なら、平行な二本の線の距離は、

$$
\boxed{
\delta_d
=
\frac{\delta_u}{\|M^{-T}n\|}
}
$$

となる。

これは法線方向へ動かした点の変位長 $\|Mn\|\delta_u$ とは一般に異なる。shearでは、接線方向の移動成分も生じるためである。

必要device幅を $d_{\mathrm{req}}$ とするなら、

$$
\delta_u
\ge
d_{\mathrm{req}}\|M^{-T}n\|
$$

となる。

全法線方向に対する保守的な候補として、最小特異値 $\sigma_{\min}(M)$ を使い、

$$
\delta_u\ge\frac{d_{\mathrm{req}}}{\sigma_{\min}(M)}
$$

とすることもできる。ただし過度に大きな塗り足しになり得る。

### 14.4 必要device幅の初期候補

局所直線・有限の有効AA範囲を仮定する場合、前景と背後のエッジ遷移範囲をそれぞれ $r_F,r_B$、位置誤差等を $e_d$ として、

$$
d_{\mathrm{req}}
\approx
r_F+r_B+e_d+m
$$

を初期候補にできる。$m$ は安全余裕である。

**これは一般的なSVG全体への証明式ではない。** 実際のAA、filter、curve flattening、色変動、画素位相によって必要条件は変わる。最終的な採用は実描画検査で決める。

Gaussianのように理論上無限の裾を持つ処理では、閾値付きの有効範囲として定義する。

### 14.5 幅には下限と上限がある

隙間対策のための必要下限を $\delta_{\min}$、細部・穴・外形を守る上限を $\delta_{\max}$ とする。

$$
\delta_{\min}\le\delta_u\le\delta_{\max}
$$

を満たす幅が存在しなければ、その場所へunderlapを適用しない。

この場合は、shape構成の変更、paintの統合、対象表示条件の限定、あるいは未達報告へ切り替える。幅を無理に増やして細いパーツを潰さない。

### 14.6 幅の探索も検証付きにする

```text
対象の描画条件から初期幅を提案
    ↓
保護領域に触れない候補幅を列挙
    ↓
最終SVGへ反映して描画
    ↓
alpha・色・外形・穴を検査
    ↓
合格した最小候補を採用
```

色誤差が幅に対して単調に減るとは限らない。合否の単調性を仮定した二分探索だけに依存しない。

### 14.7 `non-scaling-stroke`は万能ではない

描画先に応じてstrokeのスケール挙動を変える機能はあるが、下地色、外周への突出、join、透明度、全レンダラーでの同一性を解決するものではない。[S08]

WVRでは便利な一候補として検証できるが、品質契約を省略する根拠にはしない。

---

<a id="s15"></a>
## 15. 半透明・グラデーション・clip・mask

### 15.1 物体の透明度がある場合

同じ位置で二つの半透明shapeが重なると、物体alpha $\tau_A,\tau_B$ に対し、

$$
\tau_{\mathrm{out}}
=
\tau_B+\tau_A(1-\tau_B)
$$

となる。

例えば、

$$
\tau_A=\tau_B=0.5
\quad\Rightarrow\quad
\tau_{\mathrm{out}}=0.75
$$

である。[S01]

半透明なパーツを膨張して重ねれば、重複部の色と濃さが変わる。alpha欠損だけを減らす最適化では、こうした誤りを選んでしまう。

### 15.2 一様な透明度を持つ一枚の作品ならgroup opacity

全体として一枚の不透明な多色図形があり、それを均一な透明度 $\tau$ で見せる意味なら、

```text
内部は不透明として正しく構成
    ↓
そのグループ全体へ一度だけopacityを適用
```

という表現を検討できる。

```svg
<g opacity="0.5">
  <!-- 不透明なbase fillと前景。内部表現の品質は別途検証する -->
</g>
```

ただしこれは「全体の透明度が一様」という意味が成立する場合だけである。異なる透明物体が実際に重なっているシーンを、勝手にこの方式へ変えない。

また、group opacity自体は内部の色の継ぎ目を修正しない。グループ化と内部coverageの正しさは別である。[S01][S02]

### 15.3 グラデーション

paintを定数 $C_A$ とみなせない場合、第12章の二面の式をそのまま適用できない。

正しくは位置に依存する、

$$
C_A(x),\qquad C_B(x)
$$

を考える。

下地を延長するなら、同じ座標位置で本来のpaint値を返す必要がある。単に境界の平均色でstrokeを引くと、グラデーションの帯を壊すことがある。

shapeをunionしてbboxが変わると、`objectBoundingBox`基準のgradientやpatternの座標も変わり得る。必要ならpaintを明示的な共通座標系へ変換し、前後比較する。

### 15.4 clipとmask

clipやmaskは追加の境界処理であり、常に継ぎ目を消す仕組みではない。clipの輪郭にもAAが関わり得る。maskはalphaや輝度に基づく部分的な遮蔽を表す。[S09]

特に次を検査する。

```text
子要素ごとに別々のclipを使っていないか
同じclipが別transformで評価されていないか
maskのalphaと色空間の解釈が正しいか
外周を二重にAAしていないか
filter/mask領域の不足で端が切れていないか
```

外周clipを一度だけ適用する案でも、基準描画との比較を省略しない。

### 15.5 blend mode・filter

通常のsource-overと異なるblendや、背景依存の効果がある場合、黒白背景差からalphaを復元する単純式が成立しないことがある。

この種の入力は、フラット不透明用の自動修復と別プロファイルにする。効果を含むシーン全体を評価し、対応できない機能を黙って削除しない。

### 15.6 ストローク

塗り面の隙間と、ストロークのcap/joinの隙間を混同しない。

連続する一本の線であるべきものを短い独立pathへ分割すると、capやdashの位相が変わる場合がある。fillのunderlapではなく、中心線・join・dash・stroke outlineの構造を検査する。[S03]

### 15.7 細部と外周

細い髪、まつ毛、小さな文字穴、輪郭の切り欠きなどは、内部境界と外周がAA範囲内で近接する場合がある。

この場合、外周を除いた「安全な内部帯」が存在しない。自動塗り足しを抑止し、局所のシーン全体を参照して判定する。

---

<a id="s16"></a>
## 16. 出力モードと保証の境界

### 16.1 Structuralモード

**目的：編集可能な幾何構造を優先する。**

```text
共有境界・頂点を保持
意図されたpartitionを維持
不要な下地を追加しない
描画差は検査・報告する
```

使用例は、後で専用エディタやCAD的な処理へ渡す場合である。

幾何に隙間がないことと、全表示条件で継ぎ目が見えないことは区別する。

### 16.2 Display-safeモード

**目的：宣言した表示条件で、alphaと色の継ぎ目を抑える。**

```text
canonical geometryから描画用表現を生成
同paintの結合・base fill・条件付きunderlapを比較
対象描画器・倍率・位相で検証
修正内容と対象条件を品質レポートへ記録
```

「safe」は対象プロファイルの範囲で使う言葉とする。無条件の全レンダラー保証を意味しない。

### 16.3 固定解像度の画像出力

特定解像度での見た目だけが必要なら、共通サブピクセルの参照描画器でPNG等を出す選択肢もある。

ただし、これはSVGの問題を解決したことにはならない。**Raster-to-Vectorのstrictモードでは、PNGをSVG内へ埋め込んで成功扱いにしない。**

### 16.4 推奨成果物

```text
output.svg
output.geometry.json
output.quality.json
```

必要に応じて、

```text
output.structural.svg
output.display-safe.svg
```

を分ける。

構造版と表示版で異なるのは描画プランであり、元のcanonical geometryと修復履歴は追跡できるようにする。

### 16.5 保証表現

| 表示 | 意味 |
|---|---|
| `topology_validated` | 指定した検証器で採用グラフの接続・面を検査した |
| `geometry_bound_verified` | 明示した連続基準に対する誤差上界を検証した場合のみ |
| `render_profile_passed` | 列挙された描画条件で閾値を満たした |
| `render_profile_failed` | 少なくとも一つの条件で未達 |
| `inconclusive` | 未対応機能・不確実な基準などで判定できない |

`render_profile_passed` を、連続する全てのscaleや未知のソフトへの証明と表現しない。

---

<a id="s17"></a>
## 17. 漏れ・色ずれ・外形を測る検証器

### 17.1 検証対象は最終成果物

全ての測定は、最終SVGを再parseし、実際に対象レンダラーへ渡した結果に対して行う。

内部の理想プレビューだけが合格していても、最終出力の合格とはしない。

### 17.2 検査帯を作る

内部境界集合を $B_{\mathrm{int}}$ とし、その周囲のdevice空間の帯を $N_w(B_{\mathrm{int}})$ とする。

検査対象は、

$$
M_{\mathrm{int}}
=
N_w(B_{\mathrm{int}})
\cap M_{\mathrm{expected}}
\setminus M_{\mathrm{excluded}}
$$

とする。

除外・別評価するもの：

```text
外周の正しいAA
意図された穴・開口
基準が曖昧な領域
未対応の背景依存効果
内部帯を作れないほど細い形
```

除外部分を黙って成功扱いにしない。`unassessed_area` と理由を報告する。

### 17.3 alpha欠損とalpha過剰

参照alphaを $\alpha_*(p)$、出力を $\alpha(p)$ とする。

$$
L_{\alpha^-}
=
\max_{p\in M_{\mathrm{int}}}
\max(\alpha_*(p)-\alpha(p),0)
$$

$$
L_{\alpha^+}
=
\max_{p\in M_{\mathrm{int}}}
\max(\alpha(p)-\alpha_*(p),0)
$$

前者は透明度の漏れ、後者は塗りすぎを検出する。

本来0.5の半透明領域を1にすれば、欠損はなくても過剰が増える。二つを同時に見る理由である。

### 17.4 面積・長さも測る

最大値だけでなく、欠損量を面積として集約する。

$$
A_{\mathrm{deficit}}
=
\sum_{p\in M_{\mathrm{int}}}
\max(\alpha_*(p)-\alpha(p),0)\,\Delta A_p
$$

境界長 $L_B>0$ で割った、

$$
W_{\mathrm{equiv}}=\frac{A_{\mathrm{deficit}}}{L_B}
$$

は、欠損を平均的な幅として表す補助量になる。

最大値、上位percentile、欠損が連続する長さを併記する。平均値だけでは、長く細い継ぎ目や局所的な穴を隠してしまう。

### 17.5 背景を変える試験

通常のsource-overで背景依存のblend等がなく、同じ合成空間で値を扱う場合、

$$
R_b(p)=c(p)+(1-\alpha(p))b
$$

である。$c$ はpremultiplied color。

黒と白の背景なら、

$$
R_{\mathrm{white}}(p)-R_{\mathrm{black}}(p)
=
1-\alpha(p)
$$

となる。

ただし、次の点に注意する。

- スクリーンショットの符号化RGBを、そのまま任意の合成空間の値として扱わない。
- 元々半透明なら背景依存は正しい。参照との差を見る。
- 出力内に不透明な下地があると、外部背景からの漏れは0でも色ずれが残り得る。
- blend/filterに背景依存がある場合、単純式では判定しない。

alphaが直接取得できるなら、まずその値を使う。背景試験は経路の独立した確認として有用である。

### 17.6 色誤差

alphaと別に、参照色との差を測る。

$$
L_{\mathrm{color}}
=
\max_{p,r,T,b}
\left\|
R_{r,T,b}(E)(p)-R^*_{T,b}(p)
\right\|
$$

色空間、ノルム、背景、量子化を品質契約へ明記する。

最低限、黒背景と白背景へ合成した色を評価する。premultiplied RGBだけの比較より、透明部分での見た目の違いを捉えやすい。

知覚色差を使う場合も、どのalpha・背景で評価した色かを明記する。透明画素の未使用RGBを直接比較して、大きな色誤差と誤判定しない。

### 17.7 外形・穴・細部の退行検査

内部の継ぎ目が改善しても、次が悪化したら修正を不採用とする。

```text
外周の位置・AA
意図された穴のalpha
細い部品の幅・連結
元の色領域の面積
ストロークの太さ
基準画像への全体誤差
```

下地の支持領域だけでなく、filterやmask等による影響領域も含めて比較する。

### 17.8 根拠のない「隙間検出」を避ける

基準シーンがない場合、境界に沿った明度の細い谷などを検出することはできる。しかし、それが本来の線でないとは証明できない。

こうした検出は `suspected_seam` として扱い、直接の修復命令にしない。

---

<a id="s18"></a>
## 18. 倍率・位相・背景・描画器のテスト行列

### 18.1 一つのpreviewでは不十分

境界がpixel gridへ偶然ぴったり乗ると、ある倍率で継ぎ目が消える場合がある。

逆に、少し平行移動しただけで部分被覆が増え、問題が現れることもある。

### 18.2 基本の行列

商用テストの候補として、次の軸を持つ。

| 軸 | 例 | 注意 |
|---|---|---|
| 倍率 | 0.5、0.75、1、1.25、1.5、2、4 | 用途に合わせて対象範囲を定義 |
| 位相x/y | 0、0.25、0.5、0.75 device px | xとyの組み合わせを検査 |
| DPR | 1、2、3 | CSS pxとの対応を記録 |
| 回転 | 0度、非直交角、90度 | 円弧・斜線・細部を含める |
| 変換 | 非一様scale、shear、反転 | 対象製品で許可するもの |
| 背景 | 透明、黒、白、彩度の高い色 | alphaと色の両方を見る |
| 描画器 | 対象ブラウザ、変換エンジン、編集先 | バージョンと設定を記録 |
| 埋込経路 | 単独SVG、inline、image経由 | 実際の配布方法を含める |

これは推奨するテスト設計であり、本書で全組み合わせを実行したという意味ではない。今回実行した範囲は第21章に限定して記す。

### 18.3 位相はdevice空間で定義する

同じ `translate(0.5,0.5)` でも、その上にscaleがあると0.5 device pxではなくなる。

位相試験では、

```text
canonical geometry
    ↓
対象のscale・transform
    ↓
device空間で指定したphase
```

になるように変換を構成する。

user空間で平行移動を与える必要がある場合は、実効変換の逆を用いて補正する。

### 18.4 エンジン横断比較と基準比較は別

二つの描画器が同じ画像を出しても、両方が基準から同じ方向へずれている可能性がある。

したがって、

```text
renderer A vs reference
renderer B vs reference
renderer A vs renderer B
```

を分けて記録する。

### 18.5 多数の条件を効率よく調べる

```text
少数条件で全体を検査
    ↓
問題境界とjunctionを抽出
    ↓
その周辺でphase・scaleを増やす
    ↓
最悪条件を探索
    ↓
最後に代表条件で全体退行検査
```

最悪条件探索は有用だが、有限探索を連続領域全体の証明に置き換えない。

### 18.6 基準画像に必要なパターン

```text
同色の隣接面
異色の直線境界
共有円弧
円弧と直線の接続
尖った角
三叉点・四叉点
細い部品と小さな穴
半透明グループ
本当に重なる半透明物体
グラデーション
clip・mask
大きな座標値と小さな半径
丸めで半径補正が発生する円弧
```

目立つロゴ数枚だけでなく、失敗しやすい幾何を合成して評価する。

### 18.7 実装上の安全性

テスト用SVGでも、外部リソース、script、ネットワーク参照は不要である。

検証環境は外部参照を制限し、レンダリングのtimeout・メモリ・最大要素数を設定する。失敗・timeout・未対応機能は、合格ではなく記録された未完了として扱う。

---

<a id="s19"></a>
## 19. 統合アルゴリズムと修復の採否

### 19.1 最適化の優先順位

単一の重み付きlossだけに全てを混ぜると、継ぎ目を消すために穴や外形を変える解が選ばれ得る。

優先順位を次のようにする。

```text
必須：採用した意味・位相・外周・透明度契約を守る
必須：幾何・書き出しの整合を守る
必須：対象描画条件のalpha／色の閾値を満たす
改善：観測への一致度
改善：primitive数・SVGサイズ・編集のしやすさ
```

必要条件が満たせなければ、複雑さ削減より先に未達を報告する。

### 19.2 有限の表示プロファイルに対する修復選択

修復候補を $\pi$、対象描画条件集合を $\mathcal P$ とする。

$$
\pi^*
=
\arg\min_{\pi\in\mathcal F}
\max_{q\in\mathcal P}
L_{\mathrm{render}}(\pi;q)
$$

$\mathcal F$ は、幾何・位相・保護領域・観測誤差の条件を満たす候補集合である。

これは定義した候補集合と有限プロファイル内での問題であり、全てのSVG構成に対する大域最適性を主張しない。

### 19.3 統合擬似コード

```text
function build_watertight_svg(input, cfv_scene, contract):

    archive_input_and_scene_revision()

    graph = build_or_recover_shared_boundary_graph(cfv_scene)

    label_uncertain_regions(graph)
    preserve_intentional_openings(graph)

    initial_report = validate_partition_graph(graph)

    if initial_report has unresolved topological ambiguity:
        graph = compare_explicit_topology_hypotheses(
            input, graph, contract
        )

    graph = fit_shared_edges_with_joint_vertices(
        graph,
        primitive_families = [line, circular_arc, ellipse_arc, bezier],
        endpoint_constraints = exact_shared_reference,
        confidence = observation_uncertainty
    )

    graph = constrained_refine_with_rollback(graph, contract)

    if not validate_geometry_and_topology(graph, contract):
        return UNMET_OR_INCONCLUSIVE_WITH_DIAGNOSTICS

    plans = [
        structural_partition_plan(graph),
        merge_equivalent_paints_plan(graph),
        supported_occlusion_plan(graph)
    ]

    best_verified = none

    for plan in plans:

        diagnose_alpha_and_color_seams(plan, contract)

        clusters = find_repairable_boundary_clusters(plan)

        for cluster in clusters:

            candidates = propose_local_repairs(
                cluster,
                choices = [
                    keep,
                    same_paint_union,
                    base_fill,
                    directed_underlap,
                    reorder_with_hidden_completion,
                    local_shape_split
                ]
            )

            for candidate in candidates:

                if not preserves_protected_features(candidate):
                    reject(candidate)
                    continue

                svg = serialize_from_canonical_data(candidate)
                reparsed = parse_svg(svg)

                if not validate_export_semantics(reparsed, candidate):
                    reject(candidate)
                    continue

                report = evaluate_alpha_color_silhouette_and_holes(
                    svg,
                    references = contract.references,
                    profiles = contract.render_profiles
                )

                if report passes every required condition:
                    commit_candidate_if_better(candidate, report)
                else:
                    rollback(candidate)

        final_svg = serialize_from_canonical_data(plan)

        final_report = independent_full_validation(
            final_svg, graph, input, contract
        )

        if final_report passes:
            best_verified = choose_best_verified(
                best_verified, final_svg, plan, final_report
            )

    if best_verified is none:
        return report_best_attempt_as_unmet_not_success()

    return {
        svg: best_verified.svg,
        canonical_geometry: graph,
        render_plan: best_verified.plan,
        repair_log: all_accepted_repairs,
        quality: best_verified.report
    }
```

この擬似コードは責務分割を示す。位相推定、curve intersection、有限誤差検証などは、それぞれ独立した実装が必要である。

### 19.4 既存SVGしかない場合

内部の領域グラフが保存されていない場合、修復は難しくなる。

処理案：

```text
SVGを正規化・parse
    ↓
候補となる隣接境界を空間索引で抽出
    ↓
端点・曲線形状・paint・接触区間を照合
    ↓
共有されるべき区間を仮説として構築
    ↓
必要な位置で曲線を分割
    ↓
共有頂点・edgeへ置き換え
    ↓
修正前後の見た目と位相を比較
```

単なる「距離が近いからsnap」は、意図された狭い隙間を消す危険がある。

元画像・元の領域ラベルが利用できる場合は、それを根拠にする。利用できない場合は、修復の確信度を下げ、構造変更を制限する。

### 19.5 局所修復と全体検査

局所的に合格した修復も、他の修復と組み合わさると塗り順や下地が干渉する。

clusterの独立性を確認できない限り、最終SVGの全体検証は省略しない。

---

<a id="s20"></a>
## 20. ログ・品質レポート・デバッグ契約

### 20.1 必須の記録

```text
入力hash
元のcanonical graph revision
exporter revision
各共有境界・頂点のID
使用したprimitive
修復候補と採否理由
対象レンダラー・バージョン
scale・DPR・phase・背景
alpha欠損／過剰
色誤差
外周・穴・細部の退行
未検証領域・未対応機能
```

再現できない「たまに出る隙間」を、条件付きの再現可能な不具合へ変える。

### 20.2 品質レポートの型

以下は型の例であり、実際の達成値ではない。

```ts
interface RenderProfileResult {
  profileId: string;
  renderer: string;
  rendererVersion: string;
  scale: number;
  devicePixelRatio: number;
  phaseDevicePx: readonly [number, number];

  alphaDeficitMax: number;
  alphaExcessMax: number;
  colorErrorMax: number;
  colorErrorSpace: string;

  silhouetteRegression: number | null;
  holePreservation: "passed" | "failed" | "inconclusive";

  status: "passed" | "failed" | "inconclusive";
  artifacts: string[];
}

interface WvrQualityReport {
  inputHash: string;
  graphRevision: string;
  exportHash: string;

  topologyStatus: "validated" | "failed" | "inconclusive";
  geometryReference: string;
  geometryBound: number | null;

  renderProfiles: RenderProfileResult[];
  unassessedRegions: string[];
  acceptedRepairIds: string[];

  productStatus: "passed_declared_profile" | "unmet" | "inconclusive";
}
```

### 20.3 境界単位のレポート

```text
Edge 138
  shared by faces: 12 / 27
  canonical vertices: 51 → 53
  fitted primitive: circular arc
  fit status: accepted
  serialized reverse status: matched
  suspected problem: raster alpha deficit
  candidate repair: back-paint underlap
  rejected condition: touches protected opening
  final status: unchanged / profile unmet
```

「修復しなかった理由」も保存する。失敗を隠すより、後で改善可能な状態にする方が重要である。

### 20.4 UIに出す説明

推奨する表現：

```text
幾何の接続：検証済み
表示プロファイル：16条件中15条件で合格
未達：縮小表示の三領域接合で色差
適用した修正：同色面の統合、背後形状の継続
保持したもの：外形、指定の穴、部品ID
```

避ける表現：

```text
隙間ゼロを永久保証
全レンダラー対応
最大誤差0（比較対象の説明なし）
```

---

<a id="s21"></a>
## 21. 実行した数式検算と実描画比較

### 21.1 検証の目的

本書では、理論の中核となる反例と、条件付きの修正が実際の描画でどう現れるかを確認した。

実行したのは、

```text
12件の数式・幾何の限定検算
12種類の合成SVG
4倍率
4組のdevice-space位相
2種類の描画器
```

である。

実描画の比較数は、

$$
12\times4\times4\times2=384
$$

となる。

**384件全てが品質テストに合格したという意味ではない。** 不具合を再現するためのケースも含め、差分を測定した件数である。数式検算12件は全てassertionを通過した。

### 21.2 実行環境

| 項目 | 実行時の値 |
|---|---|
| Python | 3.13.5 |
| NumPy | 2.3.5 |
| Pillow | 12.3.0 |
| CairoSVG | 2.8.2 |
| Playwright | 1.57.0 |
| Chromium | 144.0.7559.96 |
| DPR | 1 |
| 倍率 | 0.75、1、1.5、2 |
| 位相の組 | (0,0)、(0.25,0.5)、(0.5,0.5)、(0.75,0.25) device px |

これは「現在の最新版」の一覧ではなく、今回実際に使用した環境の記録である。

### 21.3 基準と測定範囲

合成形状は軸に平行な矩形からなる。基準は矩形と画素の交差面積を直接計算し、**同一画素内の正しい領域分割を積分したもの**とした。

色比較は、明示的に**符号化sRGB上の算術**を使用した。一般の知覚色差や、全ての描画器の内部演算を保証する指標ではない。

実描画は透明PNGで取得した。黒白の色比較は、そのPNGを定義した算術で黒／白へ数値合成して求めた。**ブラウザ内で背景色を切り替えた再描画試験ではない。**

測定範囲は内部境界付近であり、外周のAAは除外した。したがって、これらの結果を外周・全画像・任意曲線の品質保証として使用しない。

### 21.4 代表的な結果

以下は各ケース16条件の最大値である。alpha欠損・過剰は0〜1、色誤差は黒／白合成後のRGB最大成分差で、やはり0〜1の数値として示す。

| ケース | 描画器 | alpha欠損 | alpha過剰 | 色誤差 |
|---|---|---:|---:|---:|
| 共有境界の二面cutout | cairosvg | 0.247059 | 0.000000 | 0.197093 |
| 共有境界の二面cutout | chromium | 0.247059 | 0.000000 | 0.192111 |
| 正しい一定色のbase fill | cairosvg | 0.000000 | 0.000000 | 0.003922 |
| 正しい一定色のbase fill | chromium | 0.000000 | 0.000000 | 0.003922 |
| 異なる色のunderlay | cairosvg | 0.000000 | 0.000000 | 0.152941 |
| 異なる色のunderlay | chromium | 0.000000 | 0.000000 | 0.152941 |
| 同色面を一つへunion | cairosvg | 0.000000 | 0.000000 | 0.000000 |
| 同色面を一つへunion | chromium | 0.000000 | 0.000000 | 0.000000 |
| 内部構成＋group opacity | cairosvg | 0.000000 | 0.001961 | 0.003849 |
| 内部構成＋group opacity | chromium | 0.000000 | 0.001961 | 0.005390 |
| 個別opacityのまま重ねる | cairosvg | 0.000000 | 0.252941 | 0.204890 |
| 個別opacityのまま重ねる | chromium | 0.000000 | 0.252941 | 0.198985 |
| 三領域のcutout | cairosvg | 0.278431 | 0.000000 | 0.210796 |
| 三領域のcutout | chromium | 0.278431 | 0.000000 | 0.210796 |
| 三領域の単純な重ね塗り | cairosvg | 0.000000 | 0.000000 | 0.156863 |
| 三領域の単純な重ね塗り | chromium | 0.000000 | 0.000000 | 0.156863 |
| 三領域の形と塗り順を変更 | cairosvg | 0.000000 | 0.000000 | 0.003922 |
| 三領域の形と塗り順を変更 | chromium | 0.000000 | 0.000000 | 0.004412 |

### 21.5 結果から確認できること

**共有境界だけでは、描画時のalpha欠損をなくせない例がある。**  
今回の二面cutoutでは、両描画器で最大約0.247の欠損が観測された。第4章の理想化モデルの0.25と近いが、8bitの量子化や実装差を含むため完全一致ではない。

**一定色の二面では、適切なbase fillが有効だった。**  
内部のalpha欠損は0となり、色差は最大約0.003922だった。この矩形・一定色・内部帯の条件に限った結果である。

**任意色の下地はalphaを直しても色を壊す。**  
`underlay_wrong` はalpha欠損0だが、色誤差が約0.153残った。下地の色を選ぶ条件を省略できない。

**三領域の単純な重ね塗りも、alphaと色で結果が分かれた。**  
`triple_layered` はalpha欠損0だが、内部境界帯の最大色誤差は約0.157だった。

**三領域でも、形と塗り順の組を変えることで改善した例がある。**  
`triple_reordered` はalpha欠損0、色誤差はCairoSVGで約0.003922、Chromiumで約0.004412となった。

**一様な透明度と、半透明shapeの重複は別物である。**  
`per_shape_opacity_overlap` は、目標としている一様0.5の透明度に対し約0.253のalpha過剰が出た。これは個別opacityの表現を一様透明度の作品へ誤適用した反例である。

### 21.6 三領域の「中央の式」と「最大実測値」が異なる理由

第13章の中央画素の導出では、理想比率をA=1/2、B=1/4、C=1/4としている。

一方、実測表は中央画素だけでなく、内部境界帯全体の最大値を取っている。単純な三段重ねでは、A/Cの境界付近に、本来は隠れているBの色が寄与する場所もある。

したがって、中央画素の理論色差と、内部帯の最大色差を同じ指標として比較してはいけない。

### 21.7 意図された隙間のケース

`geometry_gap` と `intentional_gap` は、同じ0.2 user unitの空白を持つSVGを使用する。

違いは比較基準である。

```text
geometry_gap:
  基準は本来つながった二面 → 空白は欠陥

intentional_gap:
  基準にも同じ空白がある → 空白そのものは保持すべき
```

これにより、見た目や小ささだけで空白の意味を判断できないことを示している。

なお、意図された空白がある場合でも、個別coverageの合成によって基準積分との差が生じることはある。その差を減らすことと、空白を物理的に埋めることは別の操作である。

### 21.8 実行した12件の限定検算

| 検算 | 確認したこと |
|---|---|
| 相補的な二面 | 0.5と0.5の個別合成でalphaが0.75になる |
| 等分された三面 | 背景寄与が8/27になるモデル |
| 積分と合成の順序 | サンプルごとに合成すればalphaが1になる反例 |
| 異なる色のunderlay | 色誤差が $ab(C_U-C_A)$ になる |
| 正しい背後色のunderlay | 二面・一定色の条件で理想色に一致する |
| 透明度の重複 | 個別0.5の重複は0.75、group opacityとは異なる |
| 端点拘束円 | 垂直二等分線パラメータで両端点を通る |
| sagitta | $q$ と円中心・半径の関係 |
| 変換後の帯幅 | $\delta_u/\|M^{-T}n\|$ と法線射影が一致する |
| 三次Bézierの反転 | 制御点を逆順にすれば同じ曲線を逆向きにたどる |
| 三段重ねの反例 | alphaが1でも三領域の色がずれる |
| 直交三領域の順序変更 | 条件付きで理想の色積分に一致する |

### 21.9 今回検証していないもの

```text
実際に問題が出たユーザーのSVG
CFV-Xエンジン全体への組み込み
曲線や円弧の全ケース
DCEL実装全体の正しさ
任意Bézierの連続交差保証
全てのx/y位相組
任意倍率・任意DPR
Safari、Firefox、デザインツール
clip・mask・gradient・filter
外周の退行
一般画像への性能・処理速度
```

この区分を明記したうえで、再現実験を設計判断の材料として使用する。

---

<a id="s22"></a>
## 22. 既存エンジンへの導入順序

### Phase 1：原因を測れる状態にする

最初に実装するのは、自動膨張ではなく診断である。

```text
共有境界IDとjunction IDのログ
export前後の幾何比較
透明PNGのalpha検査
境界帯の色比較
問題scale／phaseの記録
```

**出口条件**：同じ不具合を、同じSVGと描画条件で再現できる。

### Phase 2：構造的な幾何の隙間をなくす

```text
共有edgeを一度だけfit
canonical vertex
端点拘束付き円弧
共有edge単位の簡略化
face loopと交差の検証
```

**出口条件**：独立fitと端点不一致による隙間が、対象ケースで発生しない。

### Phase 3：書き出しによる再発を防ぐ

```text
頂点数値の再利用
edgeコマンド列の一意化
逆向き円弧・Bézierの共通生成
共通transform
丸め後の再parse
```

**出口条件**：内部と再parse後の形が、設定誤差内で対応する。

### Phase 4：不透明フラット画像の描画を改善する

```text
同paintのunion
一定色のbase fill
前景ownerの決定
保護領域を避けたunderlap
塗り順の候補比較
```

**出口条件**：幾何だけでなく、対象プロファイルでalphaと色の閾値を満たす。

### Phase 5：Junctionと半透明を分離して扱う

```text
junction patch
shape分割／塗り順の探索
uniform group opacityの意味判定
意図された半透明重なりの保護
```

**出口条件**：alphaを修正した結果、色や透明度が悪化するケースを検出・拒否できる。

### Phase 6：互換性と退行検査

```text
実際の配布先ブラウザ
SVG変換器
編集先での再保存
DPR・回転・縮小
外周・穴・細部
```

**出口条件**：対応を宣言した環境について、再現可能な品質レポートを出せる。

### 導入時の重要な判断

既に共有境界グラフがあるなら、全面的な作り直しより先に、

```text
junction更新
共有edgeの簡略化
SVGの数値展開
塗りの合成
```

を調べる。

逆に、パーツごとに完全独立したpathを生成している場合は、表示用の塗り足しだけで対処を続けるより、共有境界を内部表現へ導入する方が根本的である。

---

<a id="s23"></a>
## 23. 商用品質の受け入れ条件

### 23.1 必須ゲート

| ゲート | 合格条件 |
|---|---|
| G0：入力・意味 | 意図された透明領域と未確定領域を明示している |
| G1：位相 | 面・接合・穴・隣接に意図しない変更がない |
| G2：幾何 | 共有境界・端点・交差・基準誤差の条件を満たす |
| G3：書き出し | 再parse後の構造・曲線が検証済み |
| G4：alpha | 対象領域の欠損と過剰が閾値内 |
| G5：色 | 境界帯の色差が閾値内 |
| G6：退行 | 外周・穴・細部・全体観測誤差が許容範囲 |
| G7：互換性 | 宣言した表示条件で検査済み |
| G8：説明可能性 | 修復内容・未対応・未達を報告できる |

G4だけを満たしても、合格としない。

### 23.2 閾値の決め方

閾値は製品要件・出力bit深度・入力ノイズ・用途に依存する。

例えば8bit画像の限定的な再現テストでは、

```text
alphaの量子化許容
色の量子化許容
内部境界の最大差
全体の観測差
```

を分けて設けられる。

しかし「alpha誤差2/255なら商業的に常に十分」といった普遍的な閾値は置かない。高コントラストの長い境界と、短い低コントラストの境界では見え方が異なる。

### 23.3 エラー予算の配分

幾何の基準誤差と書き出し誤差など、同じ距離尺度に対する上界は、条件を確認して加算できる。

一方、

```text
幾何誤差px
色誤差
alpha誤差
位相の破損
```

を、同じ意味の数値として足し合わせない。

特に「幾何誤差が小さいから色の継ぎ目も小さい」とは限らない。独立したゲートを維持する。

### 23.4 Fail Closedではなく、正確な状態報告

全ての入力でSVGを出さないようにする必要はない。未達時にも、成果物と説明を返せる設計にする。

```text
structural SVGは生成済み
display-safe条件は一部未達
該当箇所と条件を記録
未検証の補正は適用していない
```

ただし、未達を「高精度モード成功」と偽って返さない。

---

<a id="s24"></a>
## 24. 最終原則・実装チェックリスト

### 24.1 最終原則

> **共有境界を一度だけ構築し、接合点を共有したままfitする。**  
> **塗りの構造は見えている領域とは別に選び、alphaと色の両方を保つ。**  
> **そして、最終SVGを実際の表示条件で検証する。**

この三つがWVRの中心である。

### 24.2 実装チェックリスト

- [ ] 同じ内部境界を、二つのパーツで独立fitしていない。
- [ ] Junctionは同じVertex IDを共有し、更新も同時に行う。
- [ ] 円弧の支持円だけでなく、有限区間と端点を検証する。
- [ ] 共有edgeの簡略化と変換を一度だけ行う。
- [ ] 微小な穴を、意図を確認せず消していない。
- [ ] 外周・細い部品・意図された開口を保護している。
- [ ] Canonical geometryと描画用underlapを分離している。
- [ ] 下地のpaintと塗り順に根拠がある。
- [ ] 半透明shapeへ一律の膨張を行っていない。
- [ ] 三領域接合を二面境界とは別に検証している。
- [ ] SVGの丸め後に再parseしている。
- [ ] alpha欠損だけでなく、alpha過剰と色差を見ている。
- [ ] 外周・穴・細部の退行を検査している。
- [ ] 倍率・DPR・位相・描画器を記録している。
- [ ] 未検証条件を成功と表示していない。

### 24.3 今回の理論で最も大切な到達点

問題を、

```text
パーツを少し重ねれば隙間は消える
```

から、

```text
正しい可視形状とpaintを維持しながら、
共有境界・潜在形状・塗り順・描画条件を整合させる
```

へ置き換える。

隙間が消えても、色が変われば未解決である。  
色が合っても、意図された穴を潰せば未解決である。  
プレビューで綺麗でも、書き出したSVGで再発すれば未解決である。

**幾何、意味、描画の三つが同時に成立することを、完成条件とする。**

---

<a id="s25"></a>
## 25. 再現方法・ファイル構成

### 25.1 添付資料の構成

```text
watertight_vector_reconstruction_spec.md
README.md
verify_wvr.py
requirements.txt
SHA256SUMS.txt

results/
  results.json
  results.md

  fixtures/
    cutout_shared.svg
    base_fill.svg
    underlay_wrong.svg
    same_paint_cutout.svg
    same_paint_union.svg
    uniform_group_opacity.svg
    per_shape_opacity_overlap.svg
    geometry_gap.svg
    intentional_gap.svg
    triple_cutout.svg
    triple_layered.svg
    triple_reordered.svg

  samples/
    cairosvg_*.png
    chromium_*.png
```

`fixtures`と`samples`には、倍率1、位相(0.5,0.5)の代表例を保存した。全条件の数値は `results.json` に収録している。

### 25.2 実行

```bash
python -m pip install -r requirements.txt

# Chromiumが環境にない場合に、Playwright用ブラウザを用意する
python -m playwright install chromium

python verify_wvr.py --out rerun_results
```

CairoSVGだけで試す場合：

```bash
python verify_wvr.py --out rerun_results --skip-browser
```

ブラウザが起動できない、ライブラリが不足する等の場合は、JSONの `skipped` と実際のrender件数を確認する。未実行の描画器を合格扱いにしない。

ブラウザの入手方法によって使用バージョンは変わる。本書の実行環境と一致しない場合でも、その環境を記録して比較する。

### 25.3 数値結果の読み方

```json
{
  "engine": "chromium",
  "case": "base_fill",
  "scale": 1.0,
  "phase": [0.5, 0.5],
  "min_alpha": 1.0,
  "max_alpha_deficit": 0.0,
  "max_alpha_excess": 0.0,
  "max_black_white_color_error": 0.0039215686274509665
}
```

上の抜粋は今回の該当条件の実測値である。全体保証値ではない。

### 25.4 ハーネスの限界

`verify_wvr.py` は、原因を再現し、式と実描画の関係を確認するためのサンプルである。

次は実装していない。

```text
ユーザーSVGの汎用読み込み・修復
DCEL構築
円弧fit
任意曲線の精密積分
全体トポロジーの保証
製品用の最悪条件探索
```

これらを実装した完成エンジンと誤解しない。

また、ハーネスはコード内で生成する合成SVGだけを扱う。ブラウザの `--no-sandbox` は今回の隔離実行環境向けの起動設定であり、任意の外部SVGを扱う商用サービスへそのまま流用しない。ネットワーク参照も不要な構成にしている。

### 25.5 検証の追加方法

次に追加すべき試験は、実際に問題を起こしたSVGから作る最小再現例である。

```text
該当する2〜4面
共有境界
必要なdefs／clip／mask／transform
表示サイズ
DPR
背景
レンダラー
```

を残して切り出す。filterや親transformを除いてしまうと、元の不具合が再現しなくなることがある。

---

<a id="sources"></a>
## 26. 一次資料・基礎資料

以下は、本書で使用した仕様・データ構造・検証手段の根拠である。各資料がWVR全体の有効性を証明しているわけではない。

数式の反例、修復候補の選択方針、限定実験の結果は、本書の導出・提案・実測として区別した。

### [S01] W3C — Compositing and Blending Level 1

参照箇所：Simple alpha compositing、Source Over、Compositing Groups、Group invariance。source-over式とグループの扱いの根拠。

確認した文書は2024-03-21のCandidate Recommendation Draftとして公開されている。規格の状態と実装上の互換性は別に扱う。

`https://www.w3.org/TR/compositing-1/`

### [S02] W3C — SVG 2: Rendering Model

参照箇所：描画順、グループ、合成モデル。SVGの要素と描画処理を分けて考える根拠。

`https://www.w3.org/TR/SVG2/render.html`

### [S03] W3C — SVG 2: Painting

参照箇所：fill-rule、stroke、paint-order、color-interpolation、shape-rendering。`geometricPrecision`はレンダリングのヒントであり、本書の継ぎ目品質契約の代わりにはしない。

`https://www.w3.org/TR/SVG2/painting.html`

### [S04] W3C — SVG 2: Paths

参照箇所：pathの閉鎖、円弧コマンド、退化ケース。閉じたpathであることと、意図した境界で閉じていることを区別する根拠。

`https://www.w3.org/TR/SVG2/paths.html`

### [S05] W3C — SVG 2: Implementation Notes

参照箇所：円弧の端点表現と中心表現、半径の補正。丸め・再parse検証の根拠。

`https://www.w3.org/TR/SVG2/implnote.html`

### [S06] CGAL — 2D Arrangements / DCEL

参照箇所：頂点・half-edge・face、twin、arrangementのデータ構造。

`https://doc.cgal.org/latest/Arrangement_on_surface_2/index.html`

`https://doc.cgal.org/latest/Arrangement_on_surface_2/classAosDcel.html`

本書は概念と構造を参考にしたものであり、添付コードへCGALを組み込んではいない。

### [S07] Jonathan Richard Shewchuk — Adaptive Precision Floating-Point Arithmetic and Fast Robust Predicates for Computational Geometry

参照箇所：orientation、incircle、丸めによる判定誤り、adaptive precision。

`https://www.cs.cmu.edu/~quake/robust.html`

この資料の述語だけで、任意曲線の全演算が自動的に保証されるとはしていない。

### [S08] W3C — SVG 2: Coordinate Systems, Transformations and Units

参照箇所：viewBox、座標変換、単位、vector effects。device-spaceの幅とuser-spaceの幅を区別する根拠。

`https://www.w3.org/TR/SVG2/coords.html`

法線方向の帯幅 $\delta_d=\delta_u/\|M^{-T}n\|$ は、本書の線形代数による導出である。

### [S09] W3C — CSS Masking Module Level 1

参照箇所：clipping、masking、clipの境界とAA、maskの扱い。

`https://www.w3.org/TR/css-masking-1/`

### [S10] Microsoft — Playwright for Python: Screenshots

参照箇所：スクリーンショット取得、bufferとしての取り出し。今回のChromium描画比較に使用したAPIの公式資料。

`https://playwright.dev/python/docs/screenshots`

### [S11] visioncortex — VTracer公式README

参照箇所：stacking、1.0のcutout、shared boundaries、simplification。

`https://github.com/visioncortex/vtracer/blob/master/README.md?plain=1`

確認日：2026-09-08。`master`は可変である。製品の依存先にする場合はcommit・ライセンス・実際の挙動を別途固定・確認する。本書ではVTracer自体を性能比較対象として実行していない。

### [S12] CairoSVG — Documentation

参照箇所：Python API、SVGからPNGへの変換。今回の独立した描画比較に使用した。

`https://cairosvg.org/documentation/`

### [P0] このプロジェクトの基礎資料

『Raster to Vector 統合理論・技術レビュー／CFV-X』版1.0、2026-09-08。

ファイル名：

`raster_to_vector_theory_review.md`

参照した主な箇所：

```text
第13章：位相・共有境界・描画の継ぎ目
第15章：SVGへの書き出しと互換性
```

参照ファイルのSHA-256：

```text
c880c14b0116b41682e7e4cd8ea8c2eb3073abd64b6717f84240b021ea69aaf6
```

---

**本書のまとめ**

共有境界は、幾何のずれを防ぐ基礎である。  
下地と塗り順は、描画時の被覆を整える手段である。  
しかし、どちらも単独では色・透明度・外形の正しさまで自動的に保証しない。

**共有された幾何、根拠のある塗り構造、最終SVGへの独立検証を、一つの工程として設計する。**
