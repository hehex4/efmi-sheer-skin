# 案例证据(2026-09 游戏版本)

> **⚠ 时效性:本文件的数全部是 2026-09 游戏版本的取证结果**(当时环境:RabbitFX 2.6、cmd_Decompiler 1.3.16、
> CrossIB 分类器 200–205 ABI)。hash、反编译行号、cb 常量编号与数值、贴图槽位号、filter_index 值、指令数、编译耗时,
> 换游戏版本或 RabbitFX 版本都可能变 —— **只能对照,不能照抄**。你自己的数一律按 [步 00「开工前」](step-00-intake.md)重新取证,或由用户提供。
>
> 「证据」一栏是**作者本机工作区**(下文 `<作者工作区>`)里的文件,不随 skill 分发,**非必读**;方法都已写进 SKILL.md。

---

## 通用时效数字(从 SKILL.md 正文挪来)

| 项 | 2026-09 的值 | 出处 / 换版本怎么重取 |
|---|---|---|
| 材质 pass 门控 | `vs == 202` | CrossIB 分类器 `CrossIBClassifier.ini` 里材质 CB2 那条 ShaderRegex 的 `filter_index = 202`;`audit_filter_index.py --gate` 重查 |
| RabbitFX 主门控 | `ps == 1718.1` | 共享 RabbitFX 的 `RabbitFX.ini` `[ShaderRegexMain] filter_index = 1718.1`(同文件还有 `global $RabbitFXMain = 1718.1`) |
| 注入锚点形态 | `rX = cb6[6].xyz * <diffuse 采样>`(布料族、皮肤族都是) | 反编译里 grep `cb6\[6\]` |
| 染色常量 `cb6[6]` | 两案目标 draw 都是 `1,1,1,1` ⇒ 肤色不用再乘 | 带 `dump_cb` 的转储里读 |
| 运行时编译(fxc `/Ges /O3`,last rite `eeb2d6fb`) | 原版 2158 ms;注入透肉(高光增益 0)2106 ms(误差内);探针档 1 852 ms | 自己用 fxc 计时 |
| 指令槽 / 采样指令(同上) | 原版 2215 / 35;注入透肉 2233(**+0.8%**)/ 36(多一张光腿图);探针档 1 579 / 3 | fxc 输出 |
| 庄方仪版(透肉 + 高光一起算) | 指令 +3.1% | 同上 |
| 作者本机 Mods 贴图槽占用(2026-09-10) | `t100` 被引用 3719 次;`t80–t99` 全空 | 每台机器自己 grep `ps-tN` |
| 作者本机 `d3dx.ini` 键位 | F10 热重载、Shift+F11 抓帧、Ctrl+F11 看原版 | 看自己的 `d3dx.ini` |
| 一帧完整转储(带 buf / 贴图,按 `lstat` 量) | 1.5 GB(角色菜单)到 4.9 GB(大世界) | — |
| EFMI 游戏 IB | 一整块共享缓冲,log 里 `IASetIndexBuffer … hash=` 几乎全是同一个值 ⇒ mod 的 `hash =` 不出现在 log 里 | `find_draw_shaders.py --ib` 靠读 ini 换算 |

---

## 案 1:庄方仪 SheerAB —— 独立丝袜网格 + 常数肤色 + 保留各向异性高光(2026-09-10)

| 项 | 值 |
|---|---|
| mod | `Zhuang Fangyi Ink Cheongsam full ver 4.8 fix`;施工目录 `DISABLED_… 4.8 fix SheerAB`(V4 用户验证基线的副本) |
| 目标 draw | 小腿片 `siwa1_001` C0 `56004@245133`;大腿袜 `siwa2` C4 `38925@204684` —— **从 C0 的 CommandList 跨 IB 画**(C4 自己的材质 pass 是皮肤族 `c6e55aaa + eeb2d6fb`,siwa2 不在那里画;C4 列表只在非材质 pass 里画它)。`find_draw_shaders.py --draw 38925,204684` 的输出正是这个结论(见脚本 docstring) |
| 材质 PS | `19c279d21b2035d5`(布料 VS `1479b2b5`);门控 `vs == 202 && ps == 1718.1` |
| 注入点 | 反编译底子 fidelity 293 `r5.xyzw = cb6[6].xyzw * r5.xyzw;` 之后;V = `r2.xyz`(182,regcheck 183..293 零写入);N = `normalize(v3.xyz)` |
| 肤色 | 常数 sRGB 227/206/193 → 线性 0.7682/0.6172/0.5333(body.dds 脸手三区中位);按切片 UV 实测光腿 228–230/207–212/193–199 ⇒ 腿与脸手同色;该 draw `cb6[6] = 1,1,1,1` ⇒ 不乘染色 |
| 范围 | 整片 draw 都是袜子;slice 2 用 UV 排除连在同一张图上的连体衣躯干(v > 0.525 或 u < 0.80 判为躯干,取自另一方案的离线测量,未独立复核) |
| 高光 | 保留 V4 的各向异性高光,按覆盖率耦合(`SHEER_SPEC_COUPLING = 1`) |
| 切换 | 全局 `$zf_sheer_route`,`[KeyZfSheerRoute] key = ctrl no_shift no_alt p`(0 = V4 原样 / 1 = 透肉) |
| 参数 | 出厂 0.25 / 0 / 0.9 / 1.0;用户试 ALPHA 0.45 后「黑丝被透成白的」→ 建议 W_MIN 0.65 / W_MAX 1.0(待用户定值) |
| 状态(截至 2026-09-10) | Gate 1 通过;调参中。**⚠ 底子 `19c279d2` 有 E6 / E6c / E7 位模式缺陷未修 ⇒ 丝袜无雨无雪**(V4、SheerAB、V5 同病) |
| 证据(作者本机,非必读) | `<作者工作区>\build\zhuangfangyi_siwa_sheer_lastrite_ab\`:`FINDINGS_A.md`、`build_zf_sheerA_ps.py`(参数段置顶 + 字节码对照)、`sync_sheer_params.py`、`wire_zf_sheer_ab.py`、`validate_zf_sheer_ab.py`;计划 `<作者工作区>\docs\superpowers\plans\2026-09-10-zhuangfangyi-siwa-sheer-lastrite-ab.md` |

**这一案学到的:**

- Gate 1 探针旁路:调用点若写 `lerp(o0, 高光返回值, 覆盖率)`,探针档 1 的纯绿会被覆盖率稀释,判据失效 ⇒ 探针档必须原样写出。
- 把参数段挪到文件顶上、删注释之后,正式档字节码与改前逐字节相同 —— 这是证明「只重排、没改逻辑」最硬的办法。
- 两片丝袜各一份 hlsl,顶部参数段要保持一致(同步脚本只动那一段);想让大腿和小腿不一样透时,故意不同步即可。
- 按键:F11 被 3DMigoto 占(Shift+F11 抓帧、Ctrl+F11 看原版);`VK_P` 不存在,字母键写裸字符。

---

## 案 2:last rite Ethereal Prayer —— 丝袜画在身体贴图上 + 光腿贴图当肤色 + 按黑白丝切参数(2026-09-10)

| 项 | 值 |
|---|---|
| mod | `last rite Ethereal Prayer 2.2_llx4` → 派生 `last rite Ethereal Prayer 2.2 Sheer` |
| 目标 draw | 身体 `.003`(11749 顶点,画着紧身衣 + 丝袜)。湿身案已把它改走皮肤路径:手部槽 `047d6e11` 段(LOD0,`drawindexed = 62955,6600,0`)/ `293cb5fa` 段(LOD1,`62955,918,0`)的 `if vs == 202 \|\| vs == 203` 块 |
| 材质 PS | `eeb2d6fb78e5a7a8`(皮肤族,VS `c6e55aaa`);LOD0 / LOD1 同 hash;七份转储 14 次 `.003` draw 零例外 |
| 注入点 | 反编译 270 `r3.yzw = cb6[6].xyz * r5.xyz;` 之后(r5 = t70 桥接的漫反射采样);V = `r2.xyz`(160–165) |
| 肤色 | 光腿版 `DiffuseMap` 逐像素:CustomShader 里 `ps-t90 = Resource-6360a178-1-DiffuseMap`,与原漫反射同采样器 `s1`、同 UV、同 bias,再 × `cb6[6]`。丝袜底下的光腿肤色中位 sRGB 255/207/198 |
| 范围 | 当前 ≠ 光腿(黑丝改动 1.83%、白丝 1.75% 整图)+ UV 框 u < 0.25、0.25 < v < 0.50(身体皮肤岛,躯干 / 手臂 / 腿都在框里;框只挡框外 168 个零散差异像素);框内 BC3 噪声 2.7–4.2%,改动 ≤ 3% |
| 状态切换 | `$stocking`(键 `i`,`global persist`):0 光腿 → 原 draw;1 黑丝 → `CustomShaderLrSheerBlack_LOD0/1`;2 白丝 → `…White…`。LOD ini 里写 `$\last rite\stocking` |
| 参数 | 黑 0.45 / 0.65 / 1.0 / 1.0(正对 ÷ 光腿 0.65,等比);白 0.25 / 0 / 0.9 / 1.0(= Last Rite 原值,比 1.00 / 1.03 / 1.05) |
| 位模式缺陷 | 修 8 处:E6 天气字 + 灯光字节 ×3、E6c 灯光类型 ×2、E7 正反面乘子 + 按位 NaN;修后编译回环与游戏字节码逐条同构 |
| 高光(2026-09-10 晚) | `SHEER_SPEC_GAIN` 0 → 1.0(黑 / 白两份),加丝袜像素标记 `_shStk` + `SHEER_SPEC_STOCKING_ONLY 1`(高光只打丝袜);reflect_check 20/20、探针矩阵 0–7 编译通过,指令 2206 → 2293 / 2296。**待实机**;高光的 Gate 2 变量探针未做 |
| 丝袜脚落雪(2026-09-11,常开) | 用户问「脱鞋后脚上没雪正常吗」:光脚走皮肤族,原版规则就不积雪(遮罩上限约 0.02,正常);丝袜在游戏逻辑里是布料(对照唐唐:丝袜在布料槽,脚背积雪),所以只对丝袜像素改布料公式。fidelity 1212 `r3.x = -r3.x * r9.y + 2;` 之后捕获 T;1225 皮肤族遮罩写好(`r9.y = r9.y * r9.w;` `r3.x = r9.y * r3.x;`)之后 `r3.x = lerp(r3.x, 布料遮罩, _shStk)`;N_up = `r17.y`、雪壳噪声 B = `r15.w`、正面 = `r9.w`(E7 已修);落雪量写死 0.55(≈ 本 mod 鞋 B 189;唐唐丝袜脚 B 246–255 ≈ 0.93–1.0;09-11 用户要求去掉可调变量);regcheck 捕获区间零写入。**待实机** |
| 跨 IB 接线(2026-09-10 发现) | LOD1 的跨 IB 段换完身体缓冲后漏了 `vb3 = vb0`(LOD0 有)⇒ 队友视角 TEXCOORD5 静止位置越界读 0,雨图三平面、落雪高度带都算错;派生版与现役都已补。丝袜走跨 IB 时,两个 LOD 的 ini 都要核对 vb3 |
| 状态(截至 2026-09-11) | 透肉 Gate 1、Gate 2 通过(用户:「效果很好」);雨已实机恢复;高光、丝袜脚落雪待实机 |
| 证据(作者本机,非必读) | `<作者工作区>\build\lastrite_ethereal_sheer_a\`:`FINDINGS.md`(§1 定位、§3b 位模式缺陷全表、§4 映射、§5.1 范围、§6 参数、§10 高光)、`fix_eeb2d6fb_fidelity.py`、`build_lr_sheer_ps.py`、`scope_uv.png` |

**这一案学到的:**

- 丝袜画在身体贴图上时,替换只能挂在整块身体的 draw 上 ⇒ Gate 1 整块绿是正常的;用户会问「为什么是全身」,先讲清楚「替换范围 vs 效果范围」,再用探针档 7 让他亲眼看。
- 光腿贴图同时解决了「肤色从哪来」和「哪里是袜子」两件事。
- 同样因为替换挂在整块身体上,开高光时必须让高光只乘丝袜像素;标记只看贴图差异,**不借** `_shScope`(那个随 `W_MIN` 变,`W_MIN` 调高时会把高光一起吃掉)。
- **用户第一句「效果很好」之后才报「丝袜上没雨了」**:位模式缺陷只在下雨时暴露。以后 [步 04](step-04-decompile-fix.md) 做完、并把「雨天看一次」写进实机门。
- 同一个 mod 用户会反复在 JASM 里切换原版 / 派生版,目录名会变;脚本里的路径每次现找,别写死。

---

## 生成脚本要点(两案的脚本不随 skill 分发;照这张清单自己写)

1. **两步分开**:先跑「忠实修补」脚本(修 E1–E7,输入是一字未改的反编译原件,已修过就拒绝),再跑「生成」脚本。
   所有路径走命令行参数,别写死 —— 用户会在 mod 管理器里切换原版 / 派生版,目录名会变(加 / 去 `DISABLED_`)。
2. **输出文件从上到下**:可调参数段(一组 `#define`,注释写清每个旋钮的方向和常用值)→ `assets/aniso_highlight_core.hlsl` 整段
   → `assets/sheer_core.hlsl` 的核心段 → 原 PS 本体。
3. **锚点**:每处用「整行去掉首尾空白后逐字比对」查找,断言恰好 1 处:`main` 开头的声明(`_shCov` / `_shScope` / `_shStk`)、
   注入块(染色漫反射那一行之后)、调用点(最终颜色写入 `o0` 之后、原 PS 收尾写出之前)、需要提前捕获的 V / N。
4. **按状态各出一份**(黑丝 / 白丝 …),只差参数段;同一状态有多片丝袜时各一份,顶部参数段用一个同步小脚本抄一致(只动参数段那几行)。
5. **出完只验一次**:挑一个状态文件跑 reflect_check(正式档,不跑开关矩阵;各状态只差参数段);纯重排 / 加死代码时,正式档字节码必须与改前逐字节相同。
6. **用户在游戏里手调过参数后**,先把装机文件的参数段抄回生成源,再重新生成,否则出厂值会覆盖用户的数。

---

## 案 3:Yvonne bikini —— 独立丝袜网格 + 烘焙肤色(2026-09-11)

| 项 | 值 |
|---|---|
| mod | `Yvonne：bikini V2 & Gui_Animation`(KudouDrive,EFMIv1 骨骼合并导出);施工目录 `… Sheer` |
| 目标 draw | 独立丝袜网格 LOD0 `d5cc14a2-6192-0`(`drawindexedinstanced = 213024,INSTANCE_COUNT,0,0,FIRST_INSTANCE`,在 `if $swapkey5 == 0` 里);颜色 `$swapkey150` 0 白 / 1 黑;只做主控 |
| 材质 PS | `846c48def5c66329`(布料 VS `1479b2b5`);底子 = hunting 标记导出的改写后 bin(`[RabbitFX\Main][ZfStandaloneCutoutMain]`) |
| 修补 | 通用 `fix_decompiler_defects.py`:E1 1 / E2 2 / E3 3 / E4 2 / E6 19 / E6c 3 / E7 2 / E8 9 行,0 处手工,编译回环位运算逐项相等 |
| 肤色 | 先用常数(身体顶点按丝袜体素取样,中位 207/177/168)→ 用户:「有作用,但不明显」→ 改烘焙:丝袜每顶点取身体最近 8 顶点反距离加权,丝袜到皮肤中位 0.5 mm;出 2048² sRGB DDS,`t90` 采样 |
| 参数 | 黑 0.45 / 0.71 / 1.0;白 0.25 / 0 / 0.9(白丝贴图是 BC7_UNORM,游戏按原值当线性用,等效 sRGB 223/213/213,与肤色只差 16/36/45 级 ⇒ 白丝天生只能淡淡一层粉) |
| 外观切换 | `x252` / Ctrl+Alt+.;高光 N = `r12.yzw`(法线分支闭合后)、L = 真 3D `r17.xyz`(主光构造处),**映射未做探针验证** |
| 教训 | 独立丝袜网格的「不明显」一半来自常数肤色(平色、无层次),一半来自默认参数偏暗端 / 袜色与肤色差太小;前者靠烘焙解决,于是烘焙成为独立网格的默认 |
| 证据(作者本机,非必读) | `<作者工作区>\build\yvonne_bikini_sheer_20260911\`:`bake_skin_to_stocking_uv.py`(原型)、`wire_yv_sheer*.py`、`pp_style_skin.py`、`bake_preview.png` |

## 案 4:Typhoeus sorceress —— 黑丝 / 白丝是同一张图上的两块 UV 岛(2026-09-12,第一版被驳回后重做)

- 部件 `a4bb34f9-94791-0`(Component 8,20 个子网格),漫反射经 RabbitFX `Resource\RabbitFx\Diffuse = ref ResourceD1…D4` → t70,
  四张 `ZF1–ZF4` 由 `$swapkey19` 选,是整套身体的配色变体,袜子那块四张几乎一样。
- 黑丝 = 子网格 `.001`,`drawindexed 65388,799671,0`,只在 `$swapkey3 == 1` 下画;白丝 = `.005`,`drawindexed 65388,27426,0`,`$swapkey3 == 0`(默认)。
  两片顶点数相同(11,540)、到身体距离中位 0.1 mm,但 UV 岛不同:按岛取色中位 sRGB 黑 (78,69,68) / 白 (224,199,206);
  同一命令表里的 `.011`(48276,368718,0)是连体衣、`.009`(62796,534504,0)是领子,中位 (123,103,103) / (120,100,100),不是袜子。
- 第一版的两个错:①拿整张 8K 图集的中位色当袜色,三片共用 `W_MIN 0.85`,黑丝几乎不透;②只接了 `$swapkey3 == 1`,白丝从未触发。
  重做后按岛各出一份参数(黑 ALPHA 0.45 / W_MIN 0.73 / W_MAX 1.0;白 0.25 / 0 / 0.9)。方法与脚本见 texture-binding-styles.md。
- 这个 mod 还带菜单调色(`CommandListSuperSet_*` 计算着色器改写漫反射):磁盘上的 DDS 是默认色,用户调过色后袜色不同,参数要按调后的颜色再调。
