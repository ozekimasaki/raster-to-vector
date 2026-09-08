# Skill実装・検証結果

2026-09-08、Windows / Python 3.14.2 / Chromium 151.0.7922.34 / CairoSVG 2.9.0。
公式Skill形式の検証を通過。日本語を扱うvalidatorは `python -X utf8` で実行した。

## 実装した内容

日本語のSKILL.md、用途別参照8文書、３理論文書の無変更コピー、補助CLI8コマンド、
既存CFV-Xの任意ドラフト経路、原実験コード、固定サンプル、単体・受け入れ試験を収録。
既存資材は変更せず、source-manifestで同梱コピーのハッシュを照合した。
SVGサブセット検査、実描画、背景別差分、alpha欠損・過剰、品質の未検証状態を実装。

## 確認した結果

- 挙動テスト22件合格。ICC・EXIF・フレーム選択・透明色・alpha保存・異常入力・参照拒否・timeout・環境不足を含む。
- CFV-X基礎レビューの検算を再実行。WVR 1の12検算、WVR 2の7種類の検算も再実行。
- ロゴ、線画、合成フラットイラスト、写真で、入力からSVGの実描画とレポート出力まで実行。
- ２図形×３倍率×２位相×４背景×２読み込み経路 = 96描画を実行。inline/imgの差は全48組で0。
- ただし解析的box coverage基準に対し、alpha・色の最大差4/255以内は16/96条件。
  最大alpha差は約0.4961、premultiplied色差は約0.3451。外周接合を含む残差であり、全条件合格ではない。
- 誤った下地はalphaだけでは見つからず色誤差で検出。実overlapへのADDはalpha過剰約0.2371を検出。
- Chromiumの実行ファイルを利用不能にした実試験でCairoSVGへ切り替わり、失敗理由を保持した。
- `python -S`で依存を除いたdoctorも、0件成功とせずindeterminateを返す。
- ZIPを元資料のない日本語・空白を含む別ディレクトリへ展開し、同梱ファイル一致・参照リンク・22テスト・画像解析・CairoSVG実描画を確認した。

## 実画像の意味

フラットイラストは合成図でCFV-Xのドラフト経路を検査した。第三者キャラクター画像は公開リポジトリから除外した。
写真は32→64→128色でpremultiplied RGB RMSEが0.03988→0.03210→0.02569へ低下。
一方、陰影の段差と細部の誤差は残り、最大色差は単調減少しない。
写真のIoU=1は全画素が不透明なためで、忠実度の証拠にはならない。
これらは処理経路と残差検出の実証であり、LLMによる高度な仕上げや写真品質の保証ではない。

## 利用範囲

Skill形式はClaude/Codex共通。現在のCodexから補助処理を実行したが、
Claudeへのアップロード、自動選択、モデル横断の独立評価は実施していない。
任意SVGの全機能、汎用DCEL、arrangement、連続誤差上界は未実装。
filter/mask/text/use等は同梱安全サブセットの対象外で、対応済みと表示しない。

## 再検証

```text
python -m unittest discover -s tests -v
python tests/acceptance.py --out /absolute/work/results
python tests/acceptance.py --out /absolute/work/results --matrix-only
python tests/profile_oracle.py --matrix /absolute/work/results/matrix --out /absolute/work/results/negative
```

最後の２コマンドはChromiumが必要。環境に応じてCHROMIUM_PATHを設定する。
受け入れ試験の数式にはShapelyも必要（元ハーネス依存）。
96条件の測定と写真の候補生成は明示実行用で、普通のSkill使用時に毎回走らせない。
