# WVR 2：被覆保存型Raster-to-Vectorの改善設計
## 隙間を埋める処理から、面積・透明度・色の寄与を保存する描画へ

**版：0.2 — 追加提案・条件付き導出・合成例による検証**  
**作成日：2026-09-08**  
**基礎資料：`watertight_vector_reconstruction_spec.md` 版1.0**  
**対象：高精度で編集可能なSVGを生成するCFV-X／WVRエンジン**

> 境界を一致させるだけでなく、境界画素に各パーツが寄与する量を一致させる。  
> 「隙間が見えない」だけでなく、「色を変更しても、透明度を変えなくても、正しい境界が保たれる」を目指す。

「WVR 2」は本プロジェクト内の作業名であり、新しい標準規格や学術的な新規性の主張ではない。加算合成、平面分割、Greenの定理は既存の基礎技術である。本書の提案は、それらを**被覆保存を検証するRaster-to-Vectorコンパイラ**として組み合わせることにある。

## 記述の区分

- **既知事項**：標準仕様・公式資料・数学の基本事項。末尾の `[Sxx]` を参照。
- **導出**：明記した仮定から本書で導く性質。
- **設計提案**：製品へ組み込むための案。未実装部分を含む。
- **限定実測**：添付コードで実行した合成例の結果。実際に問題が出たユーザーのSVGは使用していない。

---

## 1. 結論：追加するのは「被覆保存」の層

WVR 1の共有境界、接合点、端点拘束、canonical serialization、保護領域、修復後の独立検証は、そのまま残す。

その上へ、次の五つを追加する。

| 追加機構 | 何を改善するか |
|---|---|
| 領域分割専用の加算合成 | 隣接する面を重なった物体として扱うことで生じる被覆欠損 |
| 透明レイヤーから非重複セルへの変換 | 実際の半透明の重なりと、隣接面の合成を区別する |
| 共有境界の面積・モーメント積分 | 面ごとのcoverage計算が食い違う問題 |
| 配色に依存しない寄与率の検査 | 今の色では目立たないが、再配色で現れる境界の誤り |
| 合成演算を理解する出力コンパイラ | 描画器や配布経路により、指定した合成方式が使えない問題 |

最重要の変更は次の区別である。

```text
本当に前後に重なる物体
    → 同じ位置でsource-over

互いに重ならない面の、画素内の寄与
    → 積分値を加算

その区別を失わないままSVG／描画バックエンドへ変換する
```

単純に「すべてのpathをplus-lighterに変更する」という提案ではない。

---

## 2. 前の仕様ですでに解決しようとしていたこと

WVR 1には、次がすでに存在する。

```text
共有境界グラフ
canonical junction
端点拘束付き円弧フィッティング
塗り順と潜在形状の探索
条件付きbase fill／underlap
半透明を保護する条件
倍率・位相・描画器による検証
構造版と表示版の分離
```

したがって、これらを新しい発明として言い換える必要はない。

今回の改善点は、**描画の計算単位そのものを「独立したpathの塗り」から「一つの画素を分け合う面の寄与」へ移すこと**である。

前の仕様の「共通サブピクセルで合成してから積分する」という原則を、加算可能な条件、セル分解、保存型積分、出力方式まで具体化する。

---

## 3. 問題の中核：重なり合成と領域積分は別である

### 3.1 source-overは、画素内の領域分割を自動的には復元しない

不透明な二面が一つの画素を半分ずつ覆う場合を考える。

```text
Aの被覆率 = 0.5
Bの被覆率 = 0.5
幾何学的な隙間 = なし
```

個別に画素平均したalphaをsource-overすると、

$$
\alpha_{\mathrm{over}}
=0.5+0.5(1-0.5)=0.75
$$

となる。source-over自体は正しい演算だが、平均化済みの値には「互いに違う位置を覆っていた」という情報がない。[S01]

正しい領域分割の総被覆は、

$$
\alpha_{\mathrm{partition}}=0.5+0.5=1
$$

である。

この例の問題は、円の中心や半径が不正確なことではない。**異なる意味の量を、同じ合成方法で扱ったこと**にある。

### 3.2 二種類の残差を分ける

今後は少なくとも次を別々に測る。

1. **合成残差**：正しい各面の被覆値があっても、合成演算によって生じる誤差。
2. **被覆計算残差**：各面をラスタライズした時点で、面積や色の寄与が基準からずれている誤差。

加算合成は前者へ効く。しかし、後者まで自動的に消すわけではない。

---

## 4. 条件付き定理：非重複な面は、積分後に加算できる

### 4.1 前提

以下を仮定する。

- 面 $F_i$ の内部は互いに重ならない。
- 各面の素材の不透明度は $0\le\tau_i(x)\le1$。
- 色 $C_i(x)$ は明示した共通の作業色空間で扱う。
- 画素フィルタ $K_p(x)$ は非負で、積分が1。
- alphaと色はpremultiplied形式で扱う。
- この段階には背景依存のblendや非局所的なfilterを含めない。

ここでpremultiplied colorとは、色へalphaを掛けた値である。

### 4.2 各面の寄与

$$
a_{i,p}
=
\int K_p(x)\mathbf 1_{F_i}(x)\tau_i(x)\,dx
$$

$$
c_{i,p}
=
\int K_p(x)\mathbf 1_{F_i}(x)\tau_i(x)C_i(x)\,dx
$$

互いに重ならないので、画素全体の値は、

$$
\boxed{
\alpha_p=\sum_i a_{i,p},\qquad
c_p=\sum_i c_{i,p}
}
$$

となる。

これは積分の線形性による。各面を同じモデルで正しく積分できるなら、積分前の和と積分後の和が一致する。

### 4.3 重要な帰結

**三叉点、四叉点、多色の接合点にも同じ式を適用できる。** 二色だけのbase fillとは異なり、面の数に依存しない。

**面ごとの素材alphaが異なっていてもよい。** 不透明な面だけに限定されない。必要なのは、対象のセルが空間的に重複していないこと。

**意図された穴と外周も残る。** 領域が画素の一部しか覆わないなら、alphaの合計も1未満になる。すべてを1へ正規化してはいけない。

**paintが位置で変化しても、上の積分式は成立する。** ただしpaintの積分を正しく計算できることが前提である。普通のSVG実装が常にその積分を行うという意味ではない。

### 4.4 保存すべき上限

非重複なセルと非負の正規化フィルタなら、

$$
0\le \sum_i a_{i,p}\le1
$$

であり、通常の0〜1色域では各色成分もalpha以下になる。

本来この上限を超えない設計なので、後段のclampは通常動かないはずである。大きく超えた値をclampで隠すのではなく、重複、被覆誤差、誤った分類として検査する。

---

## 5. SVGへ適用する候補：isolated plus-lighter

### 5.1 最小構成

対応する描画経路では、次のような構成が候補になる。

```svg
<svg xmlns="http://www.w3.org/2000/svg"
     width="64" height="64" viewBox="0 0 64 64">
  <g style="isolation:isolate">
    <path d="M8 8H32.5V56H8Z"
          fill="#c4354d"
          style="mix-blend-mode:plus-lighter"/>
    <path d="M32.5 8H56V56H32.5Z"
          fill="#2469c8"
          style="mix-blend-mode:plus-lighter"/>
  </g>
</svg>
```

形状は重ねていない。両側の境界は同じ座標である。

Compositing Level 2のEditor’s Draftには、plus-lighterをpremultiplied colorとalphaの加算・上限制限として定義した式がある。`isolation`は合成の対象をグループへ限定する。[S02]

ここでの記述は、すべてのSVG変換器で利用できるという互換性保証ではない。

### 5.2 実装上の条件

- 加算グループは透明な初期状態から開始する。
- グループ内へ、隙間対策用の不透明な背景を足さない。
- `mix-blend-mode`は必要な各描画要素へ指定する。親へ一度指定しただけで、子の内部合成方式がすべて変わると考えない。
- グループの外側とは、意図した通常の合成を一度だけ行う。
- `lighten`、`screen`、plus-lighterを混同しない。
- 本当に重なっている半透明オブジェクトを、そのまま同じ加算グループに入れない。
- 数値、alpha、色、外形、配布経路を最終成果物で検査する。

### 5.3 なぜisolationが重要か

白いページ背景まで加算の対象にすると、白が強く加算されて結果が壊れる可能性がある。

今回の実測でも、三つの異なる透明度の面を白背景へ描いたとき、隔離ありの最大色差は約0.0063、隔離なしでは約0.6847となった。

黒背景だけの試験では、この問題が目立たなかった。黒だけで「対応している」と判定しない。

### 5.4 互換性は機能検出ではなく描画検出で判断する

`CSS.supports()`がtrueでも、実際の配布経路や保存先が同じ処理を行うとは限らない。

最低限、

```text
半分ずつの二面
三色接合
異なる素材alpha
透明出力
白・黒・有彩色背景
inline SVG
画像として読み込むSVG
```

の小さな既知パターンを描画して、alphaと色を検査する。

今回のCairoSVG 2.8.2では、このCSS指定を追加しても測定結果が変化しなかった。一方、Cairo自体のネイティブAPIにはADD演算が存在する。[S03]

したがって「基盤ライブラリが加算できる」と「SVG変換経路がCSS指定を解釈する」は別の能力である。

---

## 6. 実際の半透明の重なりを扱う：非重複セルへの変換

### 6.1 重なる物体へ直接ADDしない

二つの素材alphaが0.5で、本当に同じ位置で重なるなら、

$$
\alpha_{\mathrm{source\mbox{-}over}}
=0.5+0.5(1-0.5)=0.75
$$

である。

そのまま足して1にするのは、作品の透明度を変更する誤りである。

### 6.2 重なりをセルへ分割する

元の形状A/Bから、

```text
Aだけがある領域
AとBが重なる領域
Bだけがある領域
```

という互いに重ならないセルを作る。

重なるセルの中では、先に正しいsource-overを計算する。その結果の色とalphaをセルのpaintとして持つ。

このための平面分割には、曲線の交点でedgeを分割し、faceと包含関係を扱うarrangementが適している。円弧や直線を扱うための構造と数値要件は、CGALの2D Arrangements資料が参考になる。[S04]

### 6.3 一般式

後ろから前へ並ぶレイヤーを $1,\ldots,n$ とし、そのセル内での素材alphaを $\tau_j$ とする。

$$
\alpha_{\mathrm{cell}}
=
1-\prod_{j=1}^{n}(1-\tau_j)
$$

$$
c_{\mathrm{cell}}
=
\sum_{j=1}^{n}
\tau_jC_j
\prod_{k=j+1}^{n}(1-\tau_k)
$$

このpremultiplied colorとalphaを持つセル群は互いに重ならないため、第4章の加算対象にできる。

一定色・一定alpha・通常のsource-overという条件では、元のレイヤーを各位置で合成した結果と一致する。

### 6.4 編集用の意味は残す

```text
編集モデル：
    元の円、元のパーツ、元の透明度、前後関係

描画モデル：
    境界の交差で分割された非重複セル
    各セルの合成済みpaint

対応表：
    セル → どの元パーツから生まれたか
```

表示用にセルを増やしても、ユーザーに細切れのパーツだけを編集させる設計にしない。元の幾何と意味はsidecarや専用エディタのモデルへ保持する。

### 6.5 適用範囲と限界

- 境界の組み合わせによってセル数が大きく増える。全体を無条件で展開せず、必要な局所領域に限定する。
- グラデーションや位置依存alphaでは、合成済みpaintが単一のSVGグラデーションで表せるとは限らない。
- blur、displacement、背景依存blendなどは局所の一定セルの式だけでは処理できない。
- 透明SVGを任意の細かな背景へ重ねた際の厳密なサブピクセル合成まで、一枚の平均RGBAだけで保証できるわけではない。
- 純粋なベクトル出力が要件なら、処理が難しい箇所をラスター埋め込みで成功扱いにしない。

---

## 7. 加算だけでは足りない：共有被覆積分

### 7.1 今回の実験で残った問題

加算合成に変えても、曲線、斜めの接合、外周で誤差が残った。

考えられる要因には、面ごとの被覆評価、曲線の内部近似、フィルタ、量子化、クリッピングがある。ただし今回の結果だけで、描画器内部のどの処理が原因かは断定しない。

この問題へは、面ごとに独立したcoverageを作るのではなく、**共有境界から双方の寄与を一度に計算する**方式を導入する。

### 7.2 画素と交差した領域の面積を使う

box filterを仮定し、画素領域を $P$、セルとの交差を $Q_i=F_i\cap P$ とする。

$$
A_i=\operatorname{Area}(Q_i)
$$

画素面積が1なら、被覆率は $A_i$ である。

Greenの定理により、境界が適切に向きづけられた領域では、

$$
\boxed{
A_i=\frac12\oint_{\partial Q_i}(x\,dy-y\,dx)
}
$$

と書ける。[S05]

### 7.3 共有edgeを一度だけ積分する

共有edge $e$ の寄与を $J_e$ とする。

```text
Face Aへは +J_e
Face Bへは -J_e
```

とする。

両側で似た式をもう一度評価するのではなく、同じ計算値を反転して使う。

そうすると、内部境界の寄与は和の中で打ち消し合う。正しい平面分割と計算モデルの下では、

$$
\sum_i A_i = \operatorname{Area}(D\cap P)
$$

を満たす構成になる。

これは「平均的に合っているはず」ではなく、保存されるべき量を計算構造へ組み込む方法である。

### 7.4 円弧の積分

中心 $(c_x,c_y)$、半径 $r$、連続的に展開された角度区間 $[t_0,t_1]$ の円弧について、

$$
x=c_x+r\cos t,\qquad y=c_y+r\sin t
$$

を代入すると、

$$
\boxed{
J_e=
\frac12\left[
rc_x(\sin t_1-\sin t_0)
+rc_y(\cos t_0-\cos t_1)
+r^2(t_1-t_0)
\right]
}
$$

を得る。

直線edge $P_0=(x_0,y_0)$、$P_1=(x_1,y_1)$ では、

$$
J_e=\frac12(x_0y_1-y_0x_1)
$$

となる。

円フィッティングで得た円弧を、面積計算のためだけに細かい折れ線へ変換する必要を減らせる。

### 7.5 実装で省略できないこと

元の輪郭をそのまま積分するのではなく、**画素との交差領域の閉じた境界**を積分する必要がある。

```text
canonical edge
    ↓
画素グリッドとの交点を一度だけ計算
    ↓
画素内の円弧／直線片へ分割
    ↓
画素の辺上の必要な区間も追加
    ↓
faceごとの閉路を構成
    ↓
符号付き積分
```

穴の向き、完全な円、接線接触、画素の角を通る場合、複数成分、逆向き円弧を扱う。

交点の数値判定と幾何構築の両方が必要であり、単にepsilonを大きくして丸めるだけでは位相を保存できない。[S04]

### 7.6 数値安定性

大きい画像座標のまま積分すると、巨大な項同士の差を取る場合がある。

画素またはtileの近傍へ原点を移し、局所座標で計算する。共有edgeの積分値は一度だけ作り、同じrevision・変換・精度設定で再利用する。

実数上の保存則と浮動小数点の完全一致は別である。最終的には総和誤差、負の微小面積、交点の不確実性を数値契約へ含める。

### 7.7 通常のSVGへの効果を混同しない

この積分器を実装すると、専用の参照描画・品質測定・最適化には利用できる。

しかし、任意のSVGビューアへこの計算方法を強制できるわけではない。

```text
専用積分器で正しい
    ≠
書き出したSVGが全てのビューアで同じ
```

配布SVGには、対応バックエンド、変換候補、実描画検証が引き続き必要である。

---

## 8. 面積だけでなく色のモーメントも保存する

### 8.1 グラデーションでは被覆率だけでは足りない

一つの画素内でpaintが変化する場合、面積だけが正しくても色が正しいとは限らない。

一次のpaintを、

$$
C(x,y)=u+vx+wy
$$

とする。色の各成分へ同じ式を適用できる。

領域の一次モーメントを、

$$
M_x=\iint_Q x\,dA,\qquad
M_y=\iint_Q y\,dA
$$

とすると、

$$
\boxed{
\iint_Q C(x,y)\,dA
=
uA+vM_x+wM_y
}
$$

となる。

### 8.2 境界積分による計算

$$
M_x=\frac12\oint_{\partial Q}x^2\,dy
$$

$$
M_y=-\frac12\oint_{\partial Q}y^2\,dx
$$

と書けるため、面積と同様に共有edgeから計算できる。

### 8.3 適用範囲

一つのgradient区間が作業色空間上でアフィンな場合には有用である。

一方、途中のstop、色空間変換、非線形補間、位置依存alphaとの積などがある場合は、区間を分けるか、より高次のモーメントまたは誤差管理付きの数値積分が必要になる。

**「SVGにlinearGradientと書いてあるから、すべて一次式で処理できる」わけではない。**

### 8.4 フィルタの契約

以上の単純な面積式はbox filterに対するもの。別の再構成フィルタには、重み付き積分が必要になる。

負の係数を持つフィルタでは、coverageを単純な0〜1の確率として扱えないことがある。フィルタ選択を隠れた実装詳細にしない。[S06]

---

## 9. 配色に依存しない品質検査：寄与率行列

### 9.1 なぜ通常のRGB比較だけでは弱いか

隣接する二面がほぼ同じ色なら、色の混合比率が間違っていても目立ちにくい。

しかしユーザーが片方を濃い色へ変更すると、境界に筋が現れることがある。

そこで、

```text
現在の色が合っているか
```

だけでなく、

```text
この画素へ、各面の色が正しい割合で寄与しているか
```

を測る。

### 9.2 固定された幾何とalphaに対する線形モデル

色に線形な合成モデルでは、一つの色成分について、

$$
y_p=\sum_i w_{p,i}C_i+w_{p,\mathrm{bg}}B
$$

と書ける。

不透明度が一定の非重複セルなら、基準の重みは、

$$
w^*_{p,i}=A_{p,i}\tau_i
$$

である。背景の寄与も係数として含める。

この $w$ を**色寄与率**と呼び、画素×面の疎な行列として保持する。

### 9.3 基底色による測定

幾何、素材alpha、順序を固定したまま、

```text
試験1：面1だけ白、残りは黒
試験2：面2だけ白、残りは黒
試験3：面3だけ白、残りは黒
```

と描画する。

透明出力のpremultiplied colorを読むことで、各面の係数を推定できる。

黒にした面を透明にしてはいけない。alphaを変えると測定している合成問題そのものが変わる。

RGBの各チャネルに異なる基底を割り当てて試験をまとめる案もあるが、チャネル独立性と色管理を確認してから使用する。

### 9.4 配色全体に対する条件付き誤差上界

測定対象の正確な線形係数と基準係数の差を、

$$
d_i=w_i-w_i^*
$$

とする。

各色成分を独立に $0\le C_i\le1$ から選べるなら、

$$
\boxed{
\max_C\left|\sum_i d_iC_i\right|
=
\frac{\|d\|_1+\left|\sum_i d_i\right|}{2}
}
$$

である。

背景を含めて双方の係数合計が1なら、

$$
\boxed{
\max_C|\Delta y|=\frac12\|w-w^*\|_1
}
$$

となる。

これは、正の係数を持つ色を1、負の係数を持つ色を0へ設定する場合と、その逆を比較すれば導ける。

**現在の一配色だけでなく、同じ幾何・alphaでの再配色に対する品質を評価できる**ことが、この方法の価値である。

### 9.5 実レンダラーでは線形性も検査する

上の上界は、正確な線形モデルに対する式である。

実際の描画経路には、

```text
clamp
premultiplied／straight形式の変換
8bit量子化
色空間変換
paint依存の処理経路
```

などがあり、基底測定だけでは全配色に対する証明にならない。

そのためランダムな配色でも描画し、

$$
\eta_{\mathrm{emp}}
=
\max_{\text{試験配色}}
\|R(C)-\widehat W C\|
$$

を測る。

今回の限定試験でも、一部の条件ではこの残差が約0.10に達した。したがって、**実測から推定した行列を、無条件の再配色保証へ変換しない**。

未知の全配色へ保証を広げるには、処理系の線形性を制約するか、非線形残差の上界を別途証明する必要がある。有限のランダム試験で得た最大値は、その証明ではない。

### 9.6 新しい最適化対象

従来の色差だけではなく、

$$
L_{\mathrm{weights}}
=
\max_{p,q}
\|w_{p,q}-w^*_{p,q}\|_1
$$

を候補に加える。$q$ は描画プロファイルである。

ただし、上位制約は引き続き、

```text
形状
位相
外周
意図された穴
素材alpha
観測への許容誤差
```

である。

色寄与率を合わせるために、元の形を勝手に変えない。

---

## 10. 出力コンパイラへ「合成の意味」を持たせる

### 10.1 一律のSVG出力ではなく、演算を選ぶ

```text
canonical geometry
    ↓
シーンの意味を分類
    ├── 非重複partition
    ├── 通常の半透明overlap
    ├── セルへ分解可能なoverlap
    └── 非局所効果／未対応
    ↓
描画器の能力と品質プロファイルを確認
    ↓
適切な合成・表現へコンパイル
    ↓
最終成果物を独立検証
```

### 10.2 出力経路

| 経路 | 内容 | 注意 |
|---|---|---|
| 対応ブラウザ向けSVG | isolated plus-lighterを条件付き使用 | 実際の表示・読み込み経路を試験 |
| 互換性優先SVG | WVR 1のunion／base fill／underlap／順序探索 | 対応する有限条件での品質 |
| 精密描画バックエンド | 共有境界の面積・モーメント積分 | 一般SVGビューアの動作とは別 |
| 構造保存SVG＋sidecar | 編集可能な幾何を保持 | 表示上の完全一致と区別 |

ネイティブ描画APIのADDやplusは利用候補になるが、SVGファイルの互換性へ自動的には引き継がれない。[S03][S07]

### 10.3 filterによる代替について

SVG filterのarithmetic `feComposite`には、入力画像を加算する係数設定がある。[S08]

しかし、すでにsource-overされた `SourceGraphic` 一枚を加工しても、失われた面別の寄与を取り戻せない。

利用するなら各面・各セルの入力を別々に供給する構成、色空間、filter領域、精度、互換性を検証する必要がある。本書ではこのfilter経路を実測しておらず、完成した代替手段として扱わない。

### 10.4 ブラウザ固有の「うまいごまかし」を学習しない

特定の1倍率だけで色誤差が減る形状変形を、canonical geometryへ戻さない。

描画器向けの表現変更は派生表現に限定し、

```text
元の円弧
変換後の曲線または折れ線
追加された幾何誤差
対象プロファイル
再検証結果
```

を記録する。

---

## 11. 実装データ契約と擬似コード

### 11.1 面積・色寄与の中間表現

```ts
type FaceId = number;
type EdgeId = number;

interface PixelFaceContribution {
  face: FaceId;
  area: number;       // box filterの場合の交差面積
  momentX: number;    // 一次モーメント
  momentY: number;
  integrationErrorBound: number | null;
}

interface CoverageTile {
  geometryRevision: string;
  transformHash: string;
  kernelId: string;
  workingColorSpace: string;
  contributions: PixelFaceContribution[][];
  domainCoverage: number[];
  unresolvedPixels: number[];
}

type CompositeMeaning =
  | "disjoint-partition"
  | "true-source-over"
  | "flattened-disjoint-cells"
  | "nonlocal-effect"
  | "unresolved";

interface RenderPlan {
  meaning: CompositeMeaning;
  backend:
    | "svg-plus-lighter"
    | "svg-compatible"
    | "shared-coverage-native";
  originalGeometryRevision: string;
  protectedFeatureIds: string[];
  capabilityProfile: string;
  validations: string[];
}
```

説明用の型であり、動作する完成APIではない。メモリ効率上は、面×全画素の密行列ではなく、tile内の疎な寄与リストを利用する。

### 11.2 共有積分キャッシュ

```text
key:
  edge ID
  geometry revision
  transform
  pixel/tile
  kernel
  precision mode

value:
  canonical directionの面積・モーメント寄与
  数値誤差情報
  clippingの接続情報
```

twin方向は同じ値の符号反転を利用する。

### 11.3 全体の擬似コード

```text
function compile_coverage_conserving(scene, contract):

    graph = existing_wvr_shared_graph(scene)
    validate_geometry_topology_and_export_contract(graph)

    clusters = classify_compositing_meaning(scene)

    for cluster in clusters:

        if cluster is true overlap:
            if cell_decomposition_is_supported(cluster):
                cells = build_local_arrangement(cluster)
                assign_pointwise_composited_paints(cells)
            else:
                keep_original_compositing_and_report_scope(cluster)

        else:
            cells = existing_disjoint_faces(cluster)

        reference = integrate_shared_edges_and_paint_moments(
            cells,
            declared_kernel,
            declared_working_space
        )

        check_coverage_budget(reference)
        check_per_face_contributions(reference)

        plans = create_semantically_valid_backend_candidates(
            cells, renderer_capabilities, contract
        )

        for plan in plans:
            artifact = serialize_canonically(plan)
            validate_roundtrip_geometry(artifact)

            alpha_color_report = render_and_compare(artifact, reference)
            weight_report = probe_color_contributions(artifact, reference)
            nonlinearity_report = test_probe_predictions(artifact)

            reject_if_protected_features_change()
            reject_if_coverage_overflow_is_only_hidden_by_clamp()
            reject_if_any_required_gate_fails()

        commit_best_verified_plan_or_report_unmet()

    validate_whole_scene_after_combining_clusters()

    return {
        structural_svg,
        display_artifact,
        semantic_sidecar,
        coverage_report,
        renderer_profile_report
    }
```

局所的な合格を足し合わせただけで全体の合格としない。グループ境界、filter、背景、塗り順が相互作用するためである。

---

## 12. 数値処理で新たに守る条件

### 12.1 途中で8bitへ落とさない

専用バックエンドでは、面ごとの中間値を高精度で累積し、最後に一度だけ出力形式へ量子化する方式を優先する。

各面で丸めてから加算すると、面数に応じて誤差が蓄積し得る。ただしFP32／FP64の選択だけで、交点・clip・位相の問題が解決するわけではない。

### 12.2 勝手な正規化をしない

次の処理は原則禁止する。

```text
coverageの合計が0.93だった
    ↓
全部を0.93で割って1へ揃える
```

0.93が、実際の外周、意図された穴、素材の透明度を表している可能性がある。

既知のpartitionと数値誤差の範囲に限って補正する場合も、目標は1ではなく**正しいdomain coverageと素材alpha**である。推定誤差帯を超える補正は拒否する。

### 12.3 総和が合っていても、各面が合うとは限らない

```text
理想：A=0.5, B=0.5
実際：A=0.7, B=0.3
```

なら、合計alphaは1でも色が間違う。

したがって、

```text
総被覆の保存
各面の寄与の正しさ
paintの積分
```

を三つの別ゲートとして持つ。

### 12.4 性能

空間索引、tile単位のactive edge、共有交点キャッシュ、同じpaintの統合を使う。

重なりセルの数や、画素境界との交点数が増える入力では処理が重くなる。円弧を使うから常に高速、全体が必ず線形時間、とは主張しない。

---

## 13. 今回実行した検証

### 13.1 件数

| 検証 | 件数 |
|---|---:|
| 11種類のシーン × 6表示条件 × 2合成方式 × 3描画経路 | 396 |
| 実際の背景色とisolationの組み合わせ | 6 |
| 円弧分割／折れ線化の追加比較 | 36 |
| 色寄与率の基底プローブ＋ランダム配色 | 92 |
| 合計の描画・測定 | **530** |
| 数式の数値検算 | **7種類** |

530件すべてが品質条件に合格したという意味ではない。意図的な誤用の例と、残る問題を確認する例を含む。

数式検算は浮動小数点での限定チェックであり、形式検証された実装ではない。

### 13.2 実行環境

```text
Python      3.13.5
NumPy       2.3.5
Shapely     2.1.2
CairoSVG    2.8.2
Playwright  1.57.0
Chromium    144.0.7559.96
DPR         1
```

これは実行した環境の記録であり、各製品の最新版一覧ではない。

### 13.3 描画経路

```text
Chromium / inline SVG
Chromium / SVGをimgとして読み込み
CairoSVG / PNG変換
```

今回の主行列では、Chromiumのinlineとimgの集計値は一致した。別ブラウザや別埋め込み経路まで同じと保証しない。

### 13.4 表示条件

| ID | scale | rotation | device-space phase |
|---|---:|---:|---|
| 0 | 0.75 | 0° | (0.13, 0.37) |
| 1 | 1.0 | 0° | (0.5, 0.5) |
| 2 | 1.5 | 0° | (0.5, 0.5) |
| 3 | 1.0 | 17° | (0.13, 0.37) |
| 4 | 0.75 | 17° | (0.5, 0.5) |
| 5 | 1.5 | 17° | (0.13, 0.37) |

### 13.5 基準と測定値の意味

- 多角形：画素との交差形状の面積・重心を浮動小数点で計算。
- 円：円と画素の交差面積を、区間分割と解析的な原始関数で計算。
- グラデーション：対象例で一次のpaintと交差領域の重心を使用。
- 色：符号化sRGB値上の算術を明示的に採用。
- 出力：透明PNGからpremultiplied値を復元。
- 主行列の黒／白比較：取得PNGを数値的に背景へ合成。
- 追加6件の背景試験：SVG内の背景を変更して実際に再描画。
- 主な最大値：内部境界だけでなく外周も含める。内部帯・外周帯は別項目でも記録。

基準はbox filterによる積分である。実際の描画器が別のAAを採用している場合、観測される差はそのモデル差も含む。数値だけから「描画器が仕様違反」と結論づけない。

### 13.6 成功が明瞭だった条件

以下はChromium inline、表示条件1での値。色差は黒／白合成後のRGB最大成分差で0〜1。

| ケース | 通常合成の最大色差 | 加算合成の最大色差 |
|---|---:|---:|
| 三色T字接合 | 0.216647 | 0.006594 |
| 異なるalphaの三領域 | 0.124431 | 0.005785 |
| 円形の内部境界 | 0.246521 | 0.091534 |
| 合成済みの非重複透明セル | 0.094918 | 0.005059 |

最初の二つは、形状を膨張させず改善した例である。ただし円のケースには無視できない差が残っている。

### 13.7 条件を増やすと残る差

以下は6条件全体での最大色差、Chromium inline。

| ケース | 通常合成 | 加算合成 |
|---|---:|---:|
| 三色T字接合 | 0.253046 | 0.097841 |
| 斜めの三色接合 | 0.252172 | 0.222164 |
| 円形の内部境界 | 0.271850 | 0.168747 |
| 円環＋内円 | 0.261928 | 0.250339 |

**加算合成だけで商用品質が完成したとは言えない。**

この結果が、共有境界の積分と寄与率検査を追加する理由である。

### 13.8 誤用の負例

実際に重なる半透明物体を、そのまま加算したケースでは、表示条件1の最大色差が、

```text
通常source-over：0.008814
誤った加算：     0.230314
```

となった。

分類を誤ったままADDを使うと、むしろ大きく悪化する。

### 13.9 円弧を細かくすればよいわけではない

円を2、4、8、16、32、64、128本の円弧で表す候補と、128／512辺の折れ線候補を比較した。

一部で改善したが、円弧分割数と誤差は単調な関係ではなかった。

折れ線版は追加の幾何近似を含む。円弧のままの構造版を残し、誤差予算を満たす場合だけ表示用候補として扱う。

この結果から「円を多角形へ変えれば解決」と結論づけない。

### 13.10 寄与率測定

三色T字、斜め三色、異なるalphaの三領域、円境界について、2表示条件・2合成方式で基底色とランダム配色を試した。

良い条件では基底モデルと実描画が近かった。一方、斜め三色のある条件では、加算合成の基底モデルからのランダム配色予測残差が約0.1046となった。

これは「測定した係数をそのまま厳密な全配色保証として使う」ことへの反例である。clamp等による非線形性の可能性を含め、対応条件を制限する必要がある。

### 13.11 数式検算

```text
1. 非重複なサンプルの加算と、各位置での合成の一致
2. overlapセルの合成式とsource-overの一致
3. 円弧の面積積分式と数値積分・反転の一致
4. 共有edgeによる面積・一次モーメントの保存
5. 一次paintのモーメント積分
6. 一般の色寄与率誤差の最大値
7. 合計が一致する係数の1/2 L1上界
```

7種類すべてのassertionを通過した。今回の最大数値差は約5.7×10^-14で、設定した検算許容値10^-10以内だった。

---

## 14. 実装順序

### 第一段階：分類と小さな加算バックエンド

既存WVRの形状は変えず、非重複セルを判定できる箇所だけ加算候補を追加する。

**出口条件**：元のshape、穴、alphaを保持したまま、対応経路で改善した／未達を再現できる。

### 第二段階：寄与率と非線形性の診断

現在の配色だけでなく、基底色・対照色・ランダム配色で測る。

**出口条件**：alpha欠損、面別寄与の誤り、配色依存の非線形残差を分けて報告できる。

### 第三段階：共有被覆積分を参照エンジンとして実装

最初は直線と円弧、box filter、一定色に限定する。その後に一次paintを追加する。

**出口条件**：共有edge、面積の保存、各faceの面積、外周、穴について独立比較できる。

### 第四段階：一定paintの透明overlapをセル化

局所arrangementと合成済みセルpaintを生成する。編集モデルは維持する。

**出口条件**：元のsource-overとの点ごとの同値性と、最終描画品質を別々に確認できる。

### 第五段階：配布先別のコンパイルと退行検査

対応ブラウザ、画像経由、変換器、編集ソフトの再保存などを別プロファイルにする。

**出口条件**：構造保存と表示品質を区別した、再現可能な品質レポートを出せる。

---

## 15. 新しい品質ゲート

従来の位相・幾何・外形・alpha・色に、次を追加する。

| ゲート | 検査内容 |
|---|---|
| P0：分類 | disjointとtrue overlapを混同していない |
| P1：被覆予算 | 合計が正しいdomain coverageと素材alphaに整合 |
| P2：面別寄与 | 合計だけでなく、各面の寄与が正しい |
| P3：paint積分 | グラデーション等の位置依存paintに対応 |
| P4：合成隔離 | 背景が意図せず加算グループへ入らない |
| P5：線形性範囲 | 基底モデルを使える条件と残差を記録 |
| P6：能力検査 | 指定されたSVG合成が実際に実行される |
| P7：再配色 | 現在の色だけに過剰適合していない |
| P8：出力区別 | 専用描画の成功を一般SVGの保証と混同しない |

必須ゲートを満たせなかった場合でも、構造版のSVGと未達箇所を返せる。失敗を隠す補正は適用しない。

---

## 16. 今回まだ実装・検証していないもの

```text
実際に不具合が出たユーザーSVGの診断
CFV-X／WVR製品への組み込み
汎用の保存型円弧クリッパ・ラスタライザ
汎用arrangementによる透明セル展開
任意曲線の交差・連続誤差の形式保証
Safari／Firefox／デザインツールの互換性
GPU／OS／DPRの広い行列
非局所filterと任意blend
全配色・全倍率への数学的保証
全入力での速度・メモリ性能
SVG filter arithmeticによる代替経路
```

本書で完成させたのは、**次の改善に向けた問題分解、条件付きの数式、候補バックエンド、実際の反例を含む検証設計**である。完成した汎用ベクトライザではない。

---

## 17. 再現資料

### 構成

```text
wvr2_coverage_conserving_design.md
README.md
requirements.txt
verify_coverage.py
test_arc_lowering.py
probe_weights.py
verify_math.py
SHA256SUMS.txt

results/
    results.json
    results.md
    arc_lowering.json
    weight_probe_results.json
    math_results.json
    fixtures/
    samples/
```

### 実行

```bash
python -m pip install -r requirements.txt

# システムChromiumがない場合はPlaywrightのブラウザを用意
python -m playwright install chromium

# 必要なら実行ファイルを指定
export CHROMIUM_PATH=/path/to/chromium

python verify_coverage.py --out results
python test_arc_lowering.py --out results
python probe_weights.py --out results/weight_probe_results.json
python verify_math.py --out results/math_results.json
```

`CHROMIUM_PATH`未指定なら、システムの`chromium`、なければPlaywrightのブラウザを使用する。

ブラウザ起動、ライブラリ不足、描画失敗は合格としない。コードは合成fixtureを調べるハーネスであり、任意のSVGを修復する製品APIではない。

**安全上の注意**：この検証コードでは隔離された実行環境で自分が生成したfixtureのみを扱うため、Chromiumへ`--no-sandbox`を指定している。外部から任意のSVGを受け取るサービスへ、その起動設定を流用しない。ネットワーク隔離、外部参照拒否、時間・メモリ制限、適切なサンドボックスが別途必要である。

---

## 18. 参考資料

本書の式の導出・設計提案・限定実測と、以下の既知事項を区別する。いずれの資料も本書の統合方式全体の性能を証明するものではない。

### [P0] 本プロジェクトのWVR 1仕様

`watertight_vector_reconstruction_spec.md`、版1.0、2026-09-08。

共有境界、接合点、塗り順、下地、透明度、書き出しと検証を継承する。

### [S01] W3C — Compositing and Blending Level 1

source-over、premultiplied color、グループ合成の定義。

`https://www.w3.org/TR/compositing-1/`

### [S02] CSS Working Group — Compositing and Blending Module Level 2

plus-lighter、isolation、mix-blend-modeの適用の根拠。参照したのはEditor’s Draftであり、全実装の互換性保証ではない。

`https://drafts.csswg.org/compositing/`

### [S03] Cairo — Compositing operators

ネイティブのADD演算の根拠。CairoSVGのCSS解釈とは区別する。

`https://www.cairographics.org/operators/`

### [S04] CGAL — 2D Arrangements User Manual

平面分割、DCEL、円弧・直線のarrangementと数値表現に関する資料。今回のハーネスにCGALは組み込んでいない。

`https://doc.cgal.org/latest/Arrangement_on_surface_2/index.html`

### [S05] Active Calculus Multivariable — Green’s Theorem

領域積分を境界積分へ変換する数学的基礎。本書の円弧式・保存型実装案はこの基礎からの導出。

`https://activecalculus.org/multi1e/S_Vector_GreensTheorem.html`

### [S06] Physically Based Rendering, Fourth Edition — Image Reconstruction

画素フィルタ、再構成、サンプリングに関する基礎。box filter基準を全描画器の唯一の正解と扱わないための参照。

`https://pbr-book.org/4ed/Sampling_and_Reconstruction/Image_Reconstruction`

### [S07] Skia — SkBlendMode overview

ネイティブのplus合成に関する資料。SVG配布時の機能対応とは別。

`https://skia.org/docs/user/api/skblendmode_overview/`

### [S08] W3C — Filter Effects Module Level 1

feCompositeのarithmetic演算、filter画像の扱い。本書では代替経路として言及のみで、実測していない。

`https://www.w3.org/TR/filter-effects-1/`

---

## 最終結論

WVR 1は、**境界を共有し、塗りの構造を選び、最終SVGを検証する**設計だった。

WVR 2では、その間へ、

> **面ごとの被覆・透明度・色の寄与を保存する**

という計算上の契約を加える。

```text
形を合わせる
    ↓
各面の画素内寄与を共同で計算する
    ↓
重なりと領域分割に適した演算で合成する
    ↓
配色を変えても正しいか検査する
    ↓
実際に対応する描画経路へ出力する
```

**最も有望なのは、加算合成一つではなく、
「非重複セル化 × 共有被覆積分 × 寄与率検査 × 対応経路へのコンパイル」
を組み合わせること。**

これにより「隙間を見えなくした」から、「境界画素が正しい内訳で構成される」へ、完成条件を一段進められる。
