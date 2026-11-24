# 字体来源与许可

中台字幕字体全部为 SIL Open Font License 1.1，可商用、可随成片分发。

## 英文字体（100 款）

来源：Google Fonts 官方仓库 `github.com/google/fonts`（`ofl/` 目录），全部 SIL OFL 1.1，
逐款许可证见同目录 `LICENSE-<字体 id>.txt`（如 `LICENSE-anton.txt`）。

`static/fonts/fonts.json` 里每款英文都带 `group` 字段，剪辑台字幕字体下拉框按组显示：

| 分组 | 数量 | 代表 |
| --- | --- | --- |
| 英文 · 无衬线 | 42 | Inter、Roboto、Lato、Montserrat、Poppins、Open Sans |
| 英文 · 窄体标题 | 7 | Oswald、Bebas Neue、Anton、Archivo Black、Fjalla One |
| 英文 · 衬线 | 17 | Playfair Display、Merriweather、EB Garamond、Bodoni Moda |
| 英文 · 手写 | 14 | Caveat、Dancing Script、Great Vibes、Pacifico、Sacramento |
| 英文 · 展示 | 14 | Bungee、Black Ops One、Bowlby One、Creepster、Rye、Sigmar One |
| 英文 · 等宽 | 6 | JetBrains Mono、Roboto Mono、Space Mono、Fira Code |

固化规则（libass 按族名+字重匹配，可变字体容易被选到非 Regular 实例）：

- 可变字体用 `fontTools.varLib.instancer` 固化为静态实例：`wght=400`、`wdth=100`、`opsz≈16`、`slnt=0`；
- 重写 `name` 表（nameID 1/2/3/4/6/16/17）、`OS/2.usWeightClass=400`、`fsSelection` Regular 位、
  `head.macStyle=0`，族名与 `fonts.json` 的 `family` 完全一致；
- 构建后逐款校验：`fvar` 已消失、字重 400、ASCII 全覆盖、无中日韩字形。

## 中文字体

`SourceHanSansSC`、`ZCOOLKuaiLe`、`ZCOOLXiaoWei`、`MaShanZheng`、`LongCang`、
`LiuJianMaoCao`、`ZhiMangXing` 同为 SIL OFL 1.1，归入「中文」分组。

英文字体不含中日韩字形，中英混排字幕请选中文字体（或分别指定字体）；选中英文字体时中文
由 fontconfig 回落显示，属预期行为。
