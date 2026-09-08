---
name: raster-to-vector
description: Raster画像を観察し、WVRとCFV-Xの理論に基づいて編集可能なSVGを構築・実描画比較・修正する。PNG、JPEG、WebPのロゴ、図版、線画、イラスト、写真のベクター化、トレース、SVG再構成、変換後の隙間や透明度の診断に使用する。ラスター画像の生成・レタッチだけの依頼には使用しない。
---

# Raster-to-Vector

画像の意味と観測を保ちながらSVGを作る。LLMが構造を判断し、同梱コードが測定を支える。
自動変換器の実行だけで完了としない。画像を見て、最終SVGの実描画も見る。

## 既定の契約

- ユーザーの指定を最優先する。
- 外形、穴、透明度、重要な細部を保護し、見た目の忠実度、編集性、容量の順で選ぶ。
- 元画像の縦横比、キャンバス、背景を維持する。自動の背景除去や写真の様式変更はしない。
- PNG、JPEG、WebPを扱う。アニメーションはフレームを確認して `--frame` を指定する。
- 写真も対象。円弧や少数のフラット色だけに限定しない。
- 元SVGの一意復元、未知の全描画器との一致、連続誤差の保証を主張しない。
- 未知の内部構造は仮説であり、観測された構造とは区別する。
- 通常の成果物は純粋なベクトルSVG。画像埋め込みを成功の代替にしない。
- 日本語で説明する。ユーザーが別の言語を指定したら合わせる。

## 最初に読むもの

毎回 [作業手順](references/workflow.md) と [画像別の判断](references/image-profiles.md) を読む。
その後、今の問題に必要な資料だけ読む。

| 状況 | 参照先 |
|---|---|
| 隣接面、円弧、穴、接合点、ストローク | [幾何・位相](references/geometry-and-topology.md) |
| 隙間、透明度、重なり、下地、加算 | [被覆と合成](references/coverage-and-compositing.md) |
| SVGの組み立てと再出力 | [SVG出力](references/svg-output.md) |
| 誤差を読む、修正を採否する | [品質契約](references/quality-contract.md) |
| コマンドと環境不足 | [実行環境とCLI](references/runtime-and-cli.md) |
| 導出の原文や実験の位置づけ | [出典対応表](references/source-map.md) |

大きな原文を最初から全部読まない。対応表の章番号から必要な箇所を調べる。

## 開始例

以下の `SKILL_ROOT` は、このSKILL.mdを含むディレクトリの絶対パスに置き換える。
作業ディレクトリからの相対位置を推測しない。入力と出力も明示する。

```text
python "SKILL_ROOT/scripts/r2v.py" doctor
python "SKILL_ROOT/scripts/r2v.py" analyze "input.png" --out "work/input"
```

`work/input/normalized.png` と元画像を開く。色・alphaの統計だけで画像種別を断定しない。
`analysis.json` の向き・ICC処理・寸法・警告を読む。
元画像を上書きしない。依存不足ならCLI資料の代替経路を選ぶ。

## 1. 観察を記録する

`result.sidecar.json` を [テンプレート](examples/sidecar.template.json) から作る。
少なくとも次を画像に即して記入する。

- 画像種別と、その判断理由。
- 維持する背景・外形・穴・細線・文字・顔など。
- 意図された透明領域と、素材半透明の可能性。
- 観測された形と、背後の推定形。
- 不確実な領域と採用する仮説。
- ユーザーの用途・出力条件。未指定なら元寸法と通常SVGを使用。

色数の多さは写真・JPEGノイズ・AAのいずれでも生じる。
境界alphaと素材alphaは一枚の画像から区別できない場合がある。
読めない文字を創作しない。外見を維持するなら文字形を輪郭として再構成する。

## 2. 画像に合った候補を作る

### ロゴ・図版

基本図形、対称性、接線関係を仮説にし、観測への一致を確認する。
円に見えるからといって全てを円へ丸めない。直線・円弧・Bézierを比較する。
少数の意味のあるパーツをLLMが直接SVGまたは生成コードで構築する。

### フラットイラスト

色領域と前後関係を整理する。必要なら初期候補を生成する。

```text
python "SKILL_ROOT/scripts/r2v.py" cfvx-draft "input.png" --out "work/draft"
```

CFV-Xは素材alphaの切り捨て、小領域除去、輪郭下への膨張を含む。
共有境界やWVR 2を満たす完成出力ではない。`draft-status.json`を読む。
既存CFV-Xの `overall: passed` を最終合格として引用しない。

### 線画

均一幅の線はstroke候補、幅が変わる線は塗り形状候補にする。
開いた線、交点、線端の形を保つ。塗り面の閉路条件を開いたstrokeへ強制しない。

### 写真

```text
python "SKILL_ROOT/scripts/r2v.py" propose-regions "photo.jpg" --colors 32 --out "work/p32"
python "SKILL_ROOT/scripts/r2v.py" propose-regions "photo.jpg" --colors 64 --out "work/p64"
python "SKILL_ROOT/scripts/r2v.py" propose-regions "photo.jpg" --colors 128 --out "work/p128"
```

これらは領域候補。最終SVGでも色数を固定する指示ではない。
大きな形から作り、顔や主要物体の境界、陰影を局所的に細分化する。
滑らかな陰影にはgradient、複雑な輪郭にはBézierを使う。
模様とAA混合色を同じ規則で消さない。写真を一律にイラスト調にしない。
画素ごとの矩形列を通常解にしない。必要な複雑度と残差を報告する。

### 素材半透明

色、alpha、前後関係を明示する。CFV-Xを標準経路にしない。
通常のsource-overを出発点とし、重なりを加算に変えない。

## 3. 共有構造を使う

隣接面があるときは [共有グラフ例](examples/shared-boundary.json) を参考にする。
境界は一度だけ構築し、左右の面は同じedgeを逆向きに参照する。
junctionは共有頂点変数。fit後に別々の端点を近づける方式にしない。
正逆のSVGコマンド生成は同じ数値・精度・transformを使う。

円弧は両端を固定した候補を使い、支持円だけでなく有限区間を検査する。
ほぼ直線はsagittaか曲率で扱い、直線の分岐を持つ。
観測に合わなければ区間分割またはBézierへ切り替える。

穴、接続、細線の保持は幾何誤差とは別に確認する。
小領域を面積だけで除去しない。canonical形状と描画用の変更を混ぜない。
提供例はデータ表現の例であり、汎用DCEL・arrangementエンジンではない。

## 4. 塗りと合成を選ぶ

基本は通常のSVGとsource-over。
下地・union・underlapは必要な局所だけで検討し、alphaと色と外形を比較する。
同じRGBでもopacity、paint座標、意味の境界が違えば安易にunionしない。

`plus-lighter`を使う場合は [適用条件](references/coverage-and-compositing.md) を読む。
非重複の面、正しい素材alpha、isolation、対象経路での実測を必要とする。
半透明の実overlapに直接ADDしない。総alphaを1に正規化しない。
構造版を残し、表示専用の調整は `result.display.svg` に分ける。

## 5. 最終SVGを実描画する

```text
python "SKILL_ROOT/scripts/r2v.py" check "input.png" --svg "result.svg" --out "work/check"
```

`check`はSVGを再parseしてから実際の描画器へ渡す。
元画像とキャンバスが違えば黙って伸縮しない。
差分画像、白・黒・有彩色背景、alpha差を開く。
数値だけで終了しない。重要部と最大差の切り出しを目視する。

`inspect-svg`のpassedは構文・許可範囲の検査。位相保証ではない。
`render`のpassedは描画成功。元画像に忠実という意味ではない。
実行できなかった検査はindeterminate。未実行を0誤差や合格としない。

## 6. 局所修正する

初期候補を保存し、既定で最大3回の改善を行う。
最大の問題を、輪郭・塗り・透明度・書き出し・描画方式へ分類する。
一度に対象を絞り、修正前後を同条件で比較する。
穴や透明度を壊す修正は、RGB誤差が減っても採用しない。

終了条件は要求達成、2回連続で改善なし、3回終了、必要機能不足のいずれか。
最良候補を保持し、停止理由をsidecarへ記録する。
ユーザーが追加改善を求めたら保存候補から再開する。

## 7. 納品する

```text
result.svg
result.preview.png
result.comparison.png
result.report.json
result.sidecar.json
```

CLIの比較結果を上記名へ整理し、原入力とSVGのハッシュを残す。
必要な場合だけ `result.display.svg` を追加し、検証条件も別に記録する。
sidecarには意味のあるグループ・共有edge・推定・修正履歴を保持する。
CLIは観察や編集構造を推測して埋めない。LLMが実物に即して記録する。

最終回答には成果物へのリンク、残る誤差、試した描画環境を短く示す。
写真の不透明なキャンバスではIoUが1でも形状の一致を意味しない。
未指定の実画像に万能な閾値を置かず、生成・検査の状態を説明する。

## 適用例と境界

- 「このロゴをSVGに」：幾何候補と穴を整理して構築・実描画する。
- 「写真を忠実にベクター化」：陰影と細部を保ち、近似残差を明示する。
- 「SVGに白い筋がある」：幾何、位相、export、coverage、色を切り分ける。
- 「画像を明るくして」だけなら、このSkillの変換工程を強制しない。

## 研究結果の扱い

原資料の検算は限定条件の確認であり、任意画像への成功保証ではない。
box filter基準と一般の描画器のAAを同一視しない。
共有境界積分や色寄与率の式は適用条件とセットで使う。
通常SVGへ専用積分器の計算を強制できるとは説明しない。
元資料の正例・負例は [実行例](examples/usage.md) から参照できる。
