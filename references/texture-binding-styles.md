# 找丝袜贴图:从槽位反推到文件,再按 draw 的 UV 岛看

> 2026-09 Typhoeus 实例(失败一次才写下这页):黑丝 `.001` 和白丝 `.005` 是**同一张 8K 图上的两片网格、两块 UV 岛**,
> 靠 `$swapkey3` 切换;四张 `ZF1–ZF4` 只是整套身体贴图的四个配色变体,袜子那块几乎一样。第一次做的人
> ①拿整张图集的中位色当袜色(得到的是「中间色」,黑白都错);②只接了 `$swapkey3 == 1` 一个分支,白丝根本没触发。
> 这两个错都不是「看得不够仔细」,是**看的对象错了**:该看 draw,不该看文件。

## 0. 三步定位,顺序不能反

| 步 | 做什么 | 工具 | 产物 |
|---|---|---|---|
| 1 | 从 ini 找出**每次 draw 实际绑的贴图**:哪个槽、经什么写法、哪个文件、哪个状态下 | `scripts/resolve_textures.py <mod>` | 屏幕表(每次 draw 一段,`▶ 漫反射 = …` 一行结论) |
| 2 | 把候选 draw 的三角形按 UV 光栅化,**只在岛内取色**,出带标签的拼板 | `scripts/stocking_preview.py --ini … --piece …` | `stocking_sheet.png`(一眼分出袜子 / 手套 / 领子 / 光腿) |
| 3 | 需要整张看、看 alpha、放大某块 UV 时 | `scripts/dds_view.py <文件或文件夹> --out …` | 拼板 PNG |

看图用你的看图工具打开 PNG;别读 DDS 的字节猜颜色,别拿文件名当答案(`ZF1` / `H3` / `base2` 什么都说明不了)。

## 1. 槽位 → 贴图的四条路,互相印证

游戏 PS 自己读的槽号**每个 PS 都不一样**(同一角色见过材质 t16/17/18、另一材质 t18/19/20、描边 t13),所以没有「t15 = 漫反射」这种表。
可靠的是 draw 前**实际执行**的赋值:

| 写法 | ini 里长什么样 | 槽从哪来 | resolve_textures 怎么标 |
|---|---|---|---|
| ① 槽位式 | `ps-t16 = ResourceX` 直接写 | 就是写的那个槽(游戏 PS 原生槽) | `ps-t16  Diffuse?  …`(角色靠文件名 / 格式猜,带 `?`) |
| ② RabbitFX 式 | `Resource\RabbitFx\Diffuse = ref ResourceX` + `run = CommandList\RabbitFx\SetTextures` | RabbitFX 固定高槽:Diffuse t70 / Lightmap t71 / Normalmap t72 / DiscardMap t73 / Rainmap t74;`\Run` 里 GlowMap t60 / FXMap t61 | `ps-t70  Diffuse  …(经 RabbitFx\Diffuse)`;映射从 `<Mods 根>` 的 RabbitFX.ini 读,找不到用内置表并注明 |
| ③ 中转别名 | `ResourceRFXCur_Diffuse = ref Resource-4` … 再 `Resource\RabbitFX\Diffuse = ref ResourceRFXCur_Diffuse` | 同 ② | 别名链自动跟到文件;`--verbose` 打印链 |
| ④ 换 hash | `[TextureOverride…] hash = <8 位贴图 hash>` + `this = Resource_Texture7` | 由游戏决定(替换的是游戏自己那张图) | 单独一节「换 hash 式贴图替换」,角色按文件名 / 格式猜 |

第五条路是**着色器那头**:`--ps-hlsl <底子.fixed.hlsl>` 列出所有 `tN.Sample*`,标出「它写的寄存器随后被 `cb6[6]` 染色」的那一次 = 漫反射槽;
RabbitFX 改写过的底子还会对 t70 做 `GetDimensions` 探测(绑了高槽读高槽,否则回落游戏槽)。ini 那头说 t70、着色器那头说 t70 桥接到 t15,两头对上才算定案。

## 2. 状态分支:每个分支都是一片要处理的袜子

- `resolve_textures` 对每次 draw 打印「到达条件」(祖先 `if`)和每个绑定的条件(之前关掉的 `if` 块),并用 `[Constants]` 的
  `global [persist] $x = 默认值` 算出**默认状态下生效**的是哪张。
- 同一块几何在 `if $swapkey3 == 0` / `== 1` 下各有一次 draw(两组不同的 `drawindexed` 参数)时,**它们是两片袜子**,各要一份替换 PS、各接一次线。
  漏一个分支 = 那种颜色永远不触发。把所有分支列成表再开工。
- 条件里出现 `ps ==` / `vs ==` / `$object_detected` 这种运行时量时,脚本标「视运行时条件」,不替你判;材质 pass 用 `vs == 202 && ps == 1718.1`(见 [步 03](step-03-gate.md) 与 [步 09](step-09-ini.md))。
- draw 前跑了名字像 `SuperSet` / `Color` / `Recolor` 的命令表、写了 `ps-uN`、有 `Dispatch`:贴图可能被计算着色器**运行时改过色**(菜单调色 mod 常见)。
  这时磁盘上的 DDS 只是默认色;袜色以默认状态为准,并在回复里提醒用户「调过色的话袜色不同,参数要按调后的颜色再调」。

## 3. 按 draw 的 UV 岛取色

`stocking_preview.py --ini <mod.ini> --out-dir <工作目录> --tex <默认漫反射> --piece <标签> <资源前缀> <数量,起点[,基顶点]> …`

- 资源前缀 = `[Resource_<前缀>_Index/_Position/_Texcoord]`(骨骼合并导出)或 `_IB/_VB0/_VB1`(SSMT / LoyalTools 导出)的 `<前缀>`;
  也可明写 `ib=<段>,pos=<段>,uv=<段>`。`drawindexedinstanced` 的参数取第 1、3、4 个数。
- 每片打印:岛像素占比、UV 包围框、建议 `--box`(行列直方图取 90% 像素的紧框,喂 `build_sheer_ps.py --box`)、岛内袜色中位、深 / 中 / 浅、
  **像肤色**警告(光腿 / 皮肤别当袜子)、按高度 z 四段的中位色(一段颜色差 > 40 ⇒ 这片连着饰件 / 袜口,要用 `--box` 只框袜子本体)。
- 拼板 `stocking_sheet.png`:一格一片,色块 + 标签 + draw 参数。Typhoeus 那次拼板一眼就看出 `.011` 是连体衣、`.009` 是领子,只有 `.001` / `.005` 是袜子。
- 袜色中位直接喂 `suggest_sheer_params.py --fabric`;深浅档决定用黑丝还是白丝配方。

## 4. 向用户要图,但不等图

第一条回复里**顺带**问一句:「黑丝 / 白丝 / 光腿三种状态的图(游戏截图或贴图文件都行)有的话发我,没有我按 ini 和贴图自己判。」
不把它列为必需项,也不等。自己按 [步 01](step-01-decide.md) 的三步定下来先走。用户**之后**给了图:

- 贴图文件(DDS / PNG)→ `dds_view.py` 出拼板看内容,和自己找到的比:同一张就照旧;不同张 ⇒ 以用户的为准,重跑第 2、3 步。
- 游戏截图 → 看颜色对应哪个状态、哪个 `$变量` 值,修正「哪片是黑丝 / 白丝」的判断;截图本身不进流程。
- 图和自己的判断矛盾时,先在回复里一句话说明两者差在哪、按谁走,再往下做。

## 5. 别这么做

| 念头 | 为什么错 |
|---|---|
| 「整张 diffuse 的平均色 / 中位色就是袜色」 | 图集上还有手套、内衣、领子;Typhoeus 8K 图上袜子只占 1.8% |
| 「文件名叫 ZF1–ZF4,肯定是四种袜子」 | 那是四套身体配色;袜子那块四张几乎一样。看 draw,不看文件名 |
| 「找到一次画袜子的 draw 就够了」 | 另一个 `$swapkey` 值下还有一次;每个分支都要接 |
| 「t15 是漫反射,查表就行」 | 槽号每个 PS 不同;以 draw 前实际赋值 + 着色器里被 `cb6[6]` 染色的那次采样为准 |
| 「先让用户告诉我哪张是黑丝再开工」 | 默认自己判;用户给图是补充,不是前置 |
