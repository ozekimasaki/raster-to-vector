# 実行環境とCLI

## 配置

Skillフォルダ単体で利用する。パスは全て明示し、Windowsのパスは引用符で囲む。
Python 3.10+。入力はPNG/JPEG/WebP、最大25MP。SVGは10MB、100,000要素、辺8192px以内。
これは同梱ツールの資源制限。大きい入力は明示的に作業コピーを準備し、変更寸法を記録する。

```text
python "SKILL_ROOT/scripts/r2v.py" doctor
```

doctorはモジュールだけでなくChromiumの起動とCairoSVGのimportを確認する。外部アクセスはしない。
ブラウザが別の場所なら環境変数CHROMIUM_PATHへ実行ファイルを明示する。
Pythonのパッケージとブラウザは環境依存。制限環境で実行時のpipやネットワークを前提にしない。
利用可能ならローカル仮想環境へrequirements-core.txtとrequirements-render.txtを導入する。
CFV-Xを使う場合だけrequirements-cfvx.txtも必要。システム全体にインストールしない。
Claude APIのように追加導入できない環境では、既存ツールで同じ契約を満たすか未検証として返す。

## 呼び出し

```text
python scripts/r2v.py analyze input.png --out work/input
python scripts/r2v.py analyze animation.webp --frame 0 --out work/frame0
python scripts/r2v.py propose-regions input.png --colors 64 --out work/p64
python scripts/r2v.py cfvx-draft input.png --out work/draft --colors 22 --tolerance 0.65
python scripts/r2v.py inspect-svg candidate.svg --out work/structure.json
python scripts/r2v.py render candidate.svg --renderer chromium --out work/render
python scripts/r2v.py render candidate.svg --renderer chromium --scale 0.75 --phase 0.5 0.5 --background white --route img --out work/profile
python scripts/r2v.py compare input.png --rendered work/render/render.png --out work/compare
python scripts/r2v.py check input.png --svg candidate.svg --renderer auto --out work/check
```

`render --renderer auto`はChromium→CairoSVG。失敗理由と実際に使った描画器を保存する。
`--route img`はChromiumのみ。plus-lighterもChromiumのみを検証経路とする。
CairoSVGで加算が検証できない場合、通常合成の画像を加算成功として返さない。
scale/phaseはdevice pixel基準、DPR=1。キャンバスの外側へ移動した部分は切れる。
compareは同寸法を要求。元rasterの拡大補間を高倍率の正解と呼ばない。

## 保存名

analyze: normalized.png / thumbnail.png / alpha.png / analysis.json。
propose-regions: regions.png / labels.npy / alpha.png / palette.json。
labelsは色ラベルで、透明画素=-1。連結成分やfaceのIDではない。np.loadはallow_pickle=False。
render: render.png / render.json。
compare: comparison.png / comparison-{white,black,color}.png / difference.png / alpha-difference.png /
worst-crop.png / comparison.json。比較パネルは行が白・黒・有彩色、列が原画像・描画・4倍差分。
check: report.json / preview.png / comparison.png、およびrender/とcomparison/。
同じ出力ディレクトリは再実行で更新される。入力と重ならない新しい作業先を使う。

## 納品名への整理

最終checkのpreview.png、comparison.png、report.jsonをresult.preview.png、result.comparison.png、result.report.jsonにコピー。
result.svgとresult.sidecar.jsonはLLMが構築した最終版。CLIは意味や手動評価を捏造しない。
check後にSVGを変えた場合は再checkする。

## 失敗

exit 0は実行成功。2は入力・構造拒否、3は依存・実行機能不足。
cfvx-draftはドラフトが残った場合もdraft-status.jsonのprocess_exitとcandidate_existsを読む。
描画workerは45秒、CFV-Xは180秒で停止する。大量入力は明示的に分割する。
安全なSVGサブセットの範囲はsvg-output.mdを読む。未対応の正規SVGを規格違反と呼ばない。

## 配布

推奨は `npx skills add ozekimasaki/raster-to-vector`。Cursor / Claude Code / Codex ほか対応エージェントへ配置する。
手動配置も可。Claude Code: ~/.claude/skills/またはプロジェクトの.claude/skills/。Codex: ~/.codex/skills/。
claude.ai: Skillフォルダを最上位に持つZIPをアップロード。依存が実行環境にあるかは別途確認する。
Skillの仕様互換と実際の依存・描画器の利用可否を区別する。自動アップロードは行わない。
