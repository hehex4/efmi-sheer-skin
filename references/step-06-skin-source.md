# 步 06：准备肤色来源 👁

## 目标

得到一种可追溯的肤色输入：B 光腿贴图、C 烘焙肤色贴图或 A 常数肤色，并记下生成 PS 要用的 `--skin-slot-kind`、`--skin-slot`、`--skin` 与 `--box`。

## 进入条件

- [ ] 步 01 已判定丝袜是画在身体贴图上，还是独立丝袜网格。
- [ ] 步 02 已列全要做的状态、draw、资源段与 diffuse。
- [ ] 步 05 已确认底子的透肉锚点。

## 输入

| 占位符 | 是什么 | 从哪来 | 例子（2026-09 案例，勿照抄） |
|---|---|---|---|
| `<mod ini>` | 含目标资源段的 ini | 步 02 | `D:\Mods\角色\mod.ini` |
| `<工作目录>` | 只放本案中间产物的目录 | 步 00 | `%TEMP%\efmi-sheer\角色` |
| `<光腿贴图>` | 同角色、同材质的无丝袜 diffuse 绝对路径 | mod 的状态分支 | `D:/Mods/角色/Textures/BodyBare.dds` |
| `<丝袜贴图>` | 当前丝袜状态的 diffuse 绝对路径 | 步 02 | `D:/Mods/角色/Textures/BodyBlack.dds` |
| `<范围图目录>` | `diff_texture_variants.py` 的出图目录 | `<工作目录>` 下新建 | `%TEMP%\efmi-sheer\角色\diff` |
| `<UV框>` | `u0,v0,u1,v1`，左上原点、左闭右开 | 范围图与脚本包围框 | `0.12,0.48,0.61,0.98` |
| `<差异阈值>` | 超过几级 sRGB 才算差异 | 默认用 8 | `8` |
| `<分析边长>` | 选取的不大于此值的 mip 边长 | 默认用 2048 | `2048` |
| `<丝袜资源一>` / `<丝袜资源二>` | 资源前缀，或 `ib=…,pos=…,uv=…` 三段 | 步 02 | `Component4` |
| `<丝袜draw一>` / `<丝袜draw二>` | `数量,起点,基顶点` | 原 `drawindexed`；instanced 取第 1、3、4 个数 | `12345,0,0` |
| `<身体资源>` | 真正画腿的身体资源 | 步 02 | `Body` |
| `<身体draw>` | 与丝袜 z 高度重叠的身体 draw | 步 02 | `54321,120,0` |
| `<身体贴图>` | `<身体draw>` 当次绑定的 diffuse | 步 02 | `Textures\Body.dds` |
| `<肤色DDS>` | 烘焙输出 | `<工作目录>` | `%TEMP%\efmi-sheer\角色\SheerSkin.dds` |
| `<肤色预览PNG>` | 烘焙预览 | `<工作目录>` | `%TEMP%\efmi-sheer\角色\bake_preview.png` |
| `<贴图边长>` | 烘焙 DDS 边长 | 默认用 2048 | `2048` |
| `<近邻数>` | 兼容旧参数名；现在为 AABB 树叶内最多三角形数，不是混色数量 | 默认用 8 | `8` |
| `<皮肤标签>` | `stocking_preview.py` 图上的标签 | 当前身体切片名 | `小腿皮肤` |
| `<皮肤资源>` | 用来量肤色的该角色身体资源 | 步 02 | `Body` |
| `<皮肤draw>` | 露出皮肤的 draw 三元组 | 步 02 | `54321,120,0` |
| `<皮肤贴图>` | 该 draw 使用的角色皮肤 diffuse | 步 02 | `Textures\Body.dds` |
| `<预览目录>` | 皮肤或丝袜 UV 预览目录 | `<工作目录>` 下新建 | `%TEMP%\efmi-sheer\角色\preview` |
| `<肤色sRGB>` | 岛内皮肤中位数 `r,g,b` | `stocking_preview.py` 数字输出 | `255,207,198` |
| `<袜色sRGB>` | 岛内袜色中位数 `r,g,b` | bake 的 `--stocking-tex` 输出或步 01 | `76,64,66` |
| `<状态名>` | 参数建议的标签 | 用户确认的状态 | `黑丝` |
| `<身体固定乘数>` | 光腿/身体 diffuse 采样后的固定线性 RGB，有限且非负；只有证明无额外乘数才填 1,1,1 | 步 05 真实身体颜色链 | `1,0.8,0.7` |
| `<颜色空间>` | auto/srgb/linear；auto 按明确格式，旧 DDS 无声明时报错后现场核实 | 贴图格式和原采样声明 | `auto` |
| `<质量JSON>` | 每组身体/丝袜配对的烘焙诊断文件 | 工作目录下独立文件 | `D:/work/bake-quality.json` |
| `<最大距离毫米>` | 全部覆盖像素的允许表面距离；薄丝袜默认 10 | 默认值或已量出的几何间隙证据 | `10` |
| `<寻址模式>` | unknown/clamp/wrap/mirror；只有原采样器已核实 clamp 才填 clamp | 原 PS 绑定采样器与 INI 的实际定义 | `unknown` |
| `<UV重叠策略>` | `--uv-twins` 的值：`fail` 报冲突并诊断；`auto` 只烘分离最明显那根轴正侧的一侧；`x+`…`z-` 指定轴和侧 | 首次填 `fail`；质量 JSON 的 `uv_twins.conflicts_in_twin_pixels` 等于 `conflict_pixels` 时改 `auto` 重跑 | `fail` |
| `<目标标签>` | 当前目标丝袜 draw 的唯一标签 | 步 02 状态表 | `black-leg` |
| `<颜色报告目录>` | 当前目标 draw 的颜色 JSON 和预览；不同 draw 分目录 | 工作目录下新建 | `D:/work/colour-black-leg` |

## 操作

所有命令都从 skill 根目录执行。**优先 B：光腿状态身体贴图与目标 UV 对应时直接使用，保留肤色差异和材质细节。** 仅在目标 UV 不对应时做 C；非单色或无法证明单色时不能退回 A。B 路线的两张输入图先按目标 INI 所在目录解析为绝对路径；差异脚本没有 INI 参数，会把相对路径当作 skill 根下的文件。

1. B 路线：mod 有真实光腿变体，且目标 UV 对应同一腿部区域。光腿图本身非单色正是优先选它的理由；不要用中位肤色抹掉红晕、纹身和材质细节。先让脚本找差异范围并出图：

   ```powershell
   python scripts/diff_texture_variants.py --bare "<光腿贴图>" --variant "<丝袜贴图>" --thr <差异阈值> --maxdim <分析边长> --out "<范围图目录>"
   ```

2. 按 VP4 核对绿色差异区。把效果框收窄到腿部后再跑一次；整张变体在手套等框外也有差异，不代表 B 不可用。记录那些差异属于什么部件，确认目标 shader 只在袜区读取肤色并且框外保留原输出：

   ```powershell
   python scripts/diff_texture_variants.py --bare "<光腿贴图>" --variant "<丝袜贴图>" --box <UV框> --thr <差异阈值> --maxdim <分析边长> --out "<范围图目录>"
   ```

   B 的生成参数记为 `--skin-slot （步骤09选出的空槽） --skin-slot-kind bareleg --box <UV框>`。步骤 09 再把 `<光腿贴图>` 绑定到该空槽。光腿与丝袜颜色链相同才选 `--skin-tint-source shared`；光腿有独立固定乘数则选 `--skin-tint-source constant --skin-tint-linear` 并给步 05 证明的三个线性值。两条完整构建命令见步 07。光腿贴图中的肤色差异、效果框覆盖范围、采样后的真实乘数是三项独立核对，不能用其中一项代替另外两项。

3. C 路线：真实光腿/身体贴图不能直接对应目标 UV，必须先烘焙；独立丝袜通常属于此类。资源有三种等价写法：资源前缀对应 `_Index/_Position/_Texcoord`；资源前缀对应 `_IB/_VB0/_VB1`；或明写 `ib=（IB段）,pos=（Position段）,uv=（Texcoord段）`。同名资源的不同 draw 切片可以配对，不能仅因资源名相同而拒绝。一片丝袜执行：

   ```powershell
   python scripts/bake_skin_to_stocking_uv.py --ini "<mod ini>" --stocking "<丝袜资源一>" --stocking-draw "<丝袜draw一>" --body "<身体资源>" --body-draw "<身体draw>" --body-tex "<身体贴图>" --colour-space <颜色空间> --body-tint-linear <身体固定乘数> --max-distance-mm <最大距离毫米> --uv-twins <UV重叠策略> --quality-json "<质量JSON>" --stocking-tex "<丝袜贴图>" --out "<肤色DDS>" --size <贴图边长> --k <近邻数> --preview "<肤色预览PNG>"
   ```

4. 多片丝袜采样同一 diffuse、UV 岛不互压且落在同一身体 draw 的 z 范围时，成对重复 `--stocking` 与 `--stocking-draw`：

   ```powershell
   python scripts/bake_skin_to_stocking_uv.py --ini "<mod ini>" --stocking "<丝袜资源一>" --stocking-draw "<丝袜draw一>" --stocking "<丝袜资源二>" --stocking-draw "<丝袜draw二>" --body "<身体资源>" --body-draw "<身体draw>" --body-tex "<身体贴图>" --colour-space <颜色空间> --body-tint-linear <身体固定乘数> --max-distance-mm <最大距离毫米> --uv-twins <UV重叠策略> --quality-json "<质量JSON>" --stocking-tex "<丝袜贴图>" --out "<肤色DDS>" --size <贴图边长> --k <近邻数> --preview "<肤色预览PNG>"
   ```

   先比较每片丝袜与身体 draw 的 z 最小值、最大值；不同 z 段的丝袜必须配覆盖该段腿部的身体 draw。一个命令只接受一组 `--body/--body-draw`：身体被拆成互不相同的切片时，每个配对单独输出 DDS，并在步骤 09 给对应 draw 绑定自己的 DDS。

5. 烘焙按目标像素取 3D 位置，用 AABB 三角形树找真实身体表面最近点，再按重心 UV 采样原分辨率贴图，避免顶点混色抹掉三角形内部纹理。`--batch-pixels` 默认 4096，内存紧张时减小；`--k` 现在只影响树叶大小，不应靠增大它消除纹理。确需同资源同 draw 烘焙时，先确认真实光腿源，再加 `--body-tex-is-bare`；已能直接用 B 则优先 B。

   颜色解码统一用线性空间插值，写 sRGB DDS 只编码一次。`auto` 对普通 PNG 按 sRGB、DX10 DDS 按明确格式读取；旧 DDS 无明确颜色空间会拒绝猜测，须从原资源格式/采样证据核实后显式填 srgb 或 linear。不能按“哪种看起来顺眼”选择。

   同一片丝袜里左右腿共用一套 UV（镜像或重复几何）时，每个纹素会被两片三角形写入，一张图只能存一种肤色。质量 JSON 的 `uv_twins.conflicts_in_twin_pixels` 等于 `conflict_pixels`，就说明冲突全部来自这种重合：把 `<UV重叠策略>` 改成 `auto` 重跑同一命令，脚本只烘分离最明显那根世界轴正侧的一侧，另一侧的顶点读同一批纹素；`uv_twins.other_side` 记录未烘那侧与结果的 sRGB 级差和 >16 级像素的包围框，交判定与 VP2。冲突不全在重合三角形上，才是要拆 draw / 修 UV 的情况。

   质量 JSON 记录全覆盖像素的距离、最坏位置与冲突。默认 10 mm 适合薄丝袜；只有量出真实厚衣/几何间隙且身体切片正确，才能调整并记理由，不能为了通过而放大。失败会写诊断与同名 `.mask.png`，不产正式 DDS；按失败表修好输入后重跑同一条命令。已有旧 DDS 不代表本次成功。

   读数字自检，再按 VP2 看预览。C 的生成参数为 `--skin-slot （步骤09选出的空槽） --skin-slot-kind baked`，不再乘丝袜染色。烘焙用 `--body-tint-linear` 在采样前应用身体固定乘数一次。默认 1,1,1 只是脚本约定，不是身体无染色的证据；运行前必须从步 05 得到实际值。动态 tint/叠层须先捕获光腿状态的颜色源、取值及生命周期，完成专门映射后再生成；不能猜 1,1,1、改选 A 或省掉高光来绕过。`cb6[6]` 只是案例，现场读取当前 PS。

6. A 路线：仅在步 01 已完整核实目标腿部材质为单色时可用。缺光腿图、缺身体缓冲、距离失败或检测不完整都不能当作单色证据。先对真实腿部皮肤 draw 运行以下检查；输出非单色或无法证明单色时，回到 B/C，补源或修映射后继续，禁止取中位数代替纹理：

   ```powershell
   python scripts/stocking_preview.py --ini "<mod ini>" --piece "<皮肤标签>" "<皮肤资源>" "<皮肤draw>" "<皮肤贴图>" --out-dir "<预览目录>" --size 1024 --colour-space <颜色空间> --address-mode <寻址模式>
   ```

   取脚本打印的岛内中位 sRGB，交给参数脚本换算和定默认值：

   ```powershell
   python scripts/suggest_sheer_params.py --skin <肤色sRGB> --fabric <袜色sRGB> --name "<状态名>"
   ```

   记录输出中的线性肤色作为 `--skin`。A 的 `--box` 使用丝袜那次 `stocking_preview.py` 打印的建议框；常数肤色不乘 `cb6[6]`。

7. 所有路线都为每个目标 draw 生成交付检查用的颜色报告。每条命令的第一组是目标丝袜资源、原 draw 和该状态原 diffuse；第二组是实际肤色来源，不用烘焙结果替代原材质或身体源检测。相同 draw 的其它材质状态各用其贴图运行到独立目录。B 的完整命令（光腿图已与目标 UV 对应，使用同一目标几何采样）：

   ```powershell
   python scripts/stocking_preview.py --ini "<mod ini>" --piece "<目标标签>" "<丝袜资源一>" "<丝袜draw一>" "<丝袜贴图>" --piece "bare-source" "<丝袜资源一>" "<丝袜draw一>" "<光腿贴图>" --out-dir "<颜色报告目录>" --size 1024 --colour-space <颜色空间> --address-mode <寻址模式>
   ```

   C 的完整命令（使用真实身体几何与身体贴图）：

   ```powershell
   python scripts/stocking_preview.py --ini "<mod ini>" --piece "<目标标签>" "<丝袜资源一>" "<丝袜draw一>" "<丝袜贴图>" --piece "body-source" "<身体资源>" "<身体draw>" "<身体贴图>" --out-dir "<颜色报告目录>" --size 1024 --colour-space <颜色空间> --address-mode <寻址模式>
   ```

   身体和丝袜的 draw 数量、起点、基顶点可以不同，第二组填身体自己的真实三元组，不能为了匹配改成丝袜值。报告至少一组必须匹配目标丝袜 draw/resource；其余组提供来源证据。目标标签不能与 `bare-source` / `body-source` / `skin-source` 重名。

   A 的完整命令（同时验证目标材质和真实皮肤来源均为单色）：

   ```powershell
   python scripts/stocking_preview.py --ini "<mod ini>" --piece "<目标标签>" "<丝袜资源一>" "<丝袜draw一>" "<丝袜贴图>" --piece "skin-source" "<皮肤资源>" "<皮肤draw>" "<皮肤贴图>" --out-dir "<颜色报告目录>" --size 1024 --colour-space <颜色空间> --address-mode <寻址模式>
   ```

   将输出 `<颜色报告目录>` 中的 `colour_detection.json` 交步 08。v2 自动记录原 INI、draw、资源和全部输入 SHA，不手写或编辑。unknown/wrap/mirror 不会证明单色；原 shader 动态采样还需加 `--dynamic-sampling`。B/C 可保留 unknown 并完成真实源核对，A 必须在目标材质与真实皮肤两处均有完整单色证据。修改输入后重跑，不复用旧报告。

## 期望输出

以下是输出结构示例，不是本案真实 stdout：

```text
改动像素 = 整图（百分比）%;差异包围框（u/v 范围）  ← B 的候选框
框内（百分比）% / 框外（像素数）像素               ← 记录差异所属部件，确认效果不改框外
丝袜[（资源名）]:表面距离中位（毫米）mm，P99（毫米）mm，最大（毫米）mm  ← C 的关键自检
重叠:…重叠处肤色差中位（级数）、P95（级数）        ← 重叠有需保留的颜色差异就拆图
丝袜[（资源名）]:UV 重合三角形（数量）个（（组数）组），只烘（轴）（侧）一侧，丢弃（数量）个；组内分离中位（毫米）mm  ← 只在 --uv-twins 不是 fail 时出现
丝袜[（资源名）]:未烘那一侧与烘焙结果的 sRGB 级差：>4 级（像素数）像素，>16 级（像素数）像素，最大（级数）；>16 级像素框（坐标）  ← 两侧差异证据
写出（输出路径）:（尺寸）、（mip 数）级 mip;岛内肤色中位 sRGB（数值）(线性（数值）)
预览（输出路径）(暗处 = 丝袜 UV 岛以外,只是外扩填充)
```

## 判定

| 看到什么 | 结论 | 下一步 |
|---|---|---|
| B 的腿部 UV、光腿颜色链正确，效果遮罩不改框外 | 光腿贴图可做逐像素肤色 | 记录 `bareleg`、贴图与框，进步 07 |
| B 整图框外其它部件有差异，但效果框只含目标袜区 | B 仍可用 | 记录框外部件，保留 B；不要为消除整图差异而改 C/A |
| B 效果框内包含用户排除部件 | 当前框会误改别处 | 收窄框再跑；仍分不开就停下问用户：“这些相连区域也要透吗？” |
| C 所有覆盖像素在距离门内、无颜色冲突且覆盖完整 | 映射数字门通过 | 再过 VP2 检查局部和源颜色，进步 07；中位数不作放行门 |
| C 任一覆盖像素超过距离门 | 身体 draw、坐标布局或底下几何需修正 | 根据质量 JSON 的位置/三角形核对单位、坐标及身体切片，修正后同命令重烘；不得转 A |
| 身体切片、单位、配准都已核对无误，超距像素仍连成一片，质量 JSON 的 mask 显示那一片底下没有身体表面 | 丝袜底下没有腿：P0 不成立 | 停工，整条回复只发 SKILL.md「前提闸门 P0」的【无法完成】；不放宽距离门、不转 A、不拿别处的肤色填 |
| C 两边资源同名或共用 buffer | 尚不能判断是同一片几何 | 核对实际 draw 切片与源贴图；B 可直接用则优先 B，否则正确配对后烘焙 |
| `UV_COLOUR_CONFLICT` 且 `uv_twins.conflicts_in_twin_pixels` 等于 `conflict_pixels` | 左右腿（或重复几何）共用一套 UV，一张图只能存一侧 | 把 `<UV重叠策略>` 改成 `auto` 重跑同一命令；再看 `uv_twins.other_side`：>16 级像素只是小块且 VP2 正常就继续；大面积不同则回步 02 核对两侧是否真是同一部件 |
| 同片或多片重叠处有颜色冲突，且冲突不全在重合三角形上 | 同一 UV 无法存下两个肤色 | 拆成可独立接线的 draw/DDS 或修 UV 后重烘；只拆文件但仍绑同一 draw 不解决冲突 |
| A 已证明腿部单色，得到本角色该区域 sRGB 与线性值 | 常数输入成立 | 带 `--skin` 与建议框进步 07；非单色不得通过此行 |

## 看图点

| 编号 | 图 | 什么时候看 | 问句与答案 schema |
|---|---|---|---|
| VP4 | `<范围图目录>` 中的范围图 | B 首次出图后 | 见 [vision-subagent.md](vision-subagent.md) VP4；按 JSON 结果决定是否收窄 `<UV框>` |
| VP2 | `<肤色预览PNG>` | C 的数字自检通过后必看 | 见 [vision-subagent.md](vision-subagent.md) VP2；任何坏项都回本步失败处理 |

## 失败处理

| 症状 | 原因 | 修法 |
|---|---|---|
| DDS 解不开 | Pillow 不支持该格式或文件不是 diffuse | 核对文件；按 INSTALL.md 补解码依赖后重跑同一命令 |
| `--stocking` 与 `--stocking-draw` 数量不等 | 多片参数没有成对重复 | 每片各写一组，数量严格相等 |
| 稀疏网格或旧算法提示身体顶点少于 K | 顶点距离不能代表三角形表面距离 | 使用本包表面烘焙算法；仍失败核对切片/坐标，补源后继续，不改 A |
| VP2 有纯黑/纯白洞 | 身体 draw 漏了切片 | 补齐对应 z 段后重新烘焙 |
| VP2 有彩色噪点 | 源贴图、身体切片或跨表面配对错误 | 核对真实光腿源及两腿的独立配对，修正后重新烘焙 |
| VP2 不是肤色 | `<身体贴图>` 不是该 draw 的 diffuse | 回步 02 核对绑定 |
| `DISTANCE_LIMIT` | 至少一个覆盖像素离身体过远 | 读质量 JSON 和 mask 指向的三角形，核对身体切片、单位、配准；修后重跑，不只看中位数。核对无误仍成片超距 = 丝袜底下没有腿，按判定表的 P0 行停工 |
| `UV_COLOUR_CONFLICT` / `CROSS_PIECE_UV_CONFLICT` | 同一 UV 对应不同肤色 | 先读质量 JSON 的 `uv_twins`：冲突全在重合三角形上就用 `auto` 重跑；否则拆可独立接线的 draw/DDS 或修 UV；不把黑白平均成灰色 |
| `UV_RANGE` | 当前 UV 超出支持范围 | 核对原寻址与 UV 映射，正确展开到目标 UV 后重烘；不能静默 clamp |
| 旧 DDS 要求指定颜色空间 | 格式没有可信 sRGB/linear 标记 | 从原采样/资源证据核实后填 `--colour-space`，不猜 |
| `COLOUR_PRECISION` / `FORMAT_UNSUPPORTED` | 当前解码器不能保真读取源格式 | 保留原文件，取得有证据证明保真的 RGB8 颜色副本后重跑；HDR 需先证明映射方式，不擅自截断或降级常数 |
| `BODY_TINT_RANGE` | 身体乘数使颜色超出当前输出范围 | 核对实际线性乘数及颜色链，修正输入或扩展输出格式后重烘；不静默 clamp |

## 产物

| 文件 / 变量 | 放哪 | 下一步谁用 |
|---|---|---|
| B：光腿贴图、`bareleg`、UV 框 | `<工作目录>` 的施工笔记或当前上下文 | 步 07、09 |
| C：`<肤色DDS>`、`baked`、预览结论 | `<工作目录>` | 步 07、09 |
| A：线性肤色与 UV 框 | 当前上下文 | 步 07 |
| 袜色 sRGB | 当前上下文 | 步 07 的参数建议 |
| `colour_detection.json` v2 与原输入文件 | `<颜色报告目录>`；输入保持可读取 | 步 08 全状态交付检查 |

## 本步红旗

| 念头 | 现实 |
|---|---|
| “距离 0 mm，所以源贴图不用检查” | 零距离不证明肤色正确；同几何的真实光腿源可用，袜色源不能抄给自己 |
| “烘焙报 UV 冲突就是网格坏了” | 镜像腿共用 UV 是常见建模；先看 `uv_twins`，只烘一侧是正确做法，不是妥协 |
| “这一片底下没有身体，把距离门放宽，或拿旁边的肤色填上” | 没有腿就没有可透的肤色；发 P0 的【无法完成】并停工 |
| “烘焙不稳定，先用单色保证安全” | 非单色必须保留 B 或完成 C；修正输入/算法，不允许常数降级 |
| “烘焙图也乘丝袜染色” | B 按证明选 shared/constant；C 在烘焙时应用身体乘数一次，生成 PS 不再乘袜子 tint |
| “多片都塞进一个命令就行” | UV 互压会平均掉两片颜色；有需保留的差异就拆图，不只看 P95 |
| “常数抄别的角色” | A 必须量当前角色自己的皮肤贴图 |

