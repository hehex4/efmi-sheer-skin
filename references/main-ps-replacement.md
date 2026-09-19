> 本文件取自 skill efmi-anisotropic-highlight(2026-09-11 快照),随透肉包分发。文中「本 skill」「SKILL.md 第 N 节」指原来那个高光 skill;做透肉以本包 SKILL.md 为准,INI 以本包 references/ini-template.md 为准。

# 通用「安全替换角色主 PS」方法论

这一份**不限于高光**。任何要替换或改写角色像素着色器的活(材质效果、色调、透明、
自定义光照)都按这套做:它解决的是「怎么把一份改过的 PS 只挂到指定 draw 的材质 pass
上、其他 pass 不受影响、编译和反射有证据、装机可回滚」。效果本身的数学放在别处。

---

## 1. 十二条原则(每条都对应一个真实踩过的坑)

1. **先确认主 PS 的 hash,绝不猜。** 来源优先级:用户明确给出 > 转储文件名 > 文件头 /
   Frame Analysis 记录 > 游戏内纯绿探针验证。猜出来的 hash 不得安装。
2. **按完整 draw 参数锁定物体。** 至少同时核对 `IndexCount`、`StartIndex`、`BaseVertex`;
   只用 `IndexCount` 会把相邻部件混在一起。
3. **复用该 PS 自己的数据。** N / L / V / T 必须在当前这份反编译里定位;**不得照抄另一个
   hash 的寄存器名**(错误 C)。
4. **不增加未经证明的绑定。** 原 PS 声明 `cb6[10]` 就不能读 `cb6[10]` 及更高;不新读贴图槽。
5. **主 pass 替换,其他 pass 回退。** `if ps == <标记>` 走替换着色器,**`else` 必须执行原
   draw**。漏掉 else = 阴影 / 深度 / prepass 全部消失。
6. **同一逻辑子网格的所有绘制入口都要处理**,LOD0/LOD1、跨 IB、不同 VS 分支;在回复里闭环
   `N = M + K`(总入口 = 已接 + 明确不接及理由)。
7. **同一 shader hash 在整个已启用配置里只能有一个 `filter_index`。** 它不是模组内变量。
8. **审计模组的贴图注入通道**(见第 6 节)。原 PS 能编译不等于 mod 材质还在。
9. **编译通过不等于变量映射正确。** `cb0[6].xyz` 和 `r21.xyz` 都是合法 `float3`,编译器分不出
   哪个是主光。没有探针或已验证档案的映射不得装正式效果。
10. **亮色用插值,不用白色加法。** HDR 目标上 `color += white * x` 必曝成白带。
11. **在 mod 的副本上施工**,只改用户指定的那一个模组目录;不动加载器、Core、RabbitFX、其他 mod。
12. **写入前备份,替换用原子操作,失败要回滚**;最后列出改了什么、没改什么。

---

## 2. 转储:怎么拿、怎么判忠实

替换 PS 的底子是 3DMigoto 导出的 `<hash>-ps_replace.txt`。拿法三选一,按侵入性从低到高:

| 途径 | 做法 | 代价 |
|---|---|---|
| 用户已有 | 群里 / 别人给的 replace.txt | 零 |
| 游戏内 hunting | `d3dx.ini` 开 `hunting=1`,用 previous / next 键切到目标 PS,按 mark 键导出到 ShaderFixes(默认绑小键盘,本机没小键盘要先改键) | 要改 `d3dx.ini`,**必须先问用户** |
| hunting 全量导出 | `export_hlsl = 1`(2 / 3 连原始或重编译 ASM 一起导),看到过的着色器全部落盘 | 量大,事后要清理;最后手段 |

Frame Analysis dump 里**没有**着色器源码(`analyse_options` 只管 RT / 贴图 / 缓冲),别指望它。

文件结构:前半是反编译 HLSL(`void main(...)`),末尾是**块注释包住的原始反汇编**。整份文件
本身是合法 HLSL,注释里的 asm 不参与编译。**改的是上面的 `main`,不要把注释里的汇编当第二份代码。**
反汇编那段留着别删 —— `reflect_check.py` 用它当「原 PS 声明」的真值来源。

### 忠实性判定:先原封不动严格编译一次

```
fxc /T ps_5_0 /E main /Ges /WX /O3 <转储原文>
```

- **通过** → 反编译产物忠实,直接以它为底。
- **只有个别错误** → 多半是反编译器的既有产物,不是你引入的。最常见的一处
  (Typhoeus 案 2026-09-06 实录,记作 **E1**):

  ```
  error X4115: Literal floating-point value out of unsigned range for conversion: -1.000000
  ```

  根因是转储开头 `#define cmp -`,`cmp(a < b)` 展开成 `-(a<b)`,真值是 `-1.0f`,后面
  `(uint)r18.y` 就是 `(uint)(-1.0f)`。忠实修法要对照注释里的 asm:对应指令是
  `bfi r12.x, l(31), l(1), r12.x, r18.y`(插入最低位),`lt` 真值 `0xFFFFFFFF` 最低位为 1
  ⇒ 改成 `((r18.y != 0 ? 1u : 0u) & ~bitmask.x)`,对 cmp 两种约定都等价。改完**不加任何效果**
  再编译一次,通过了才算底子干净。
- **大面积错误** → 反编译不可靠,退回 asm 注入路线(`ps = xxx.asm` 直接改汇编),那是
  另一套工作量,先报告再决定。

### ⭐ E2:编译得过、值却是错的 —— `and <比较结果>, l(N)` 退化

**严格编译全过不代表反编译忠实。** 有一类缺陷不报任何错,只把数算错,静态门全绿照样放行。
2026-09-09 庄方仪案实录(`19c279d21b2035d5`),DXBC 的「布尔真值 → 整数常量」惯用法:

```
asm:   lt  r14.w, |r24.x|, |r24.y|      ; 比较,真值 = 0xFFFFFFFF
       and r14.w, r14.w, l(1)           ; 与常量 -> 应得 1 / 0
hlsl:  r14.w = cmp(abs(r24.x) < abs(r24.y));
       r14.w = r14.w ? 0.000000 : 0;    ; ❌ 两个分支都是 0,常量 l(1) 丢了 -> 恒 0
```

与 E1 同源(都在把比较真值转成整数),区别是 E1 会触发 X4115、这个**一声不吭**。

**必查,而且要查全**:

```powershell
Select-String -Path "<反编译产物>" -Pattern '\?\s*0\.000000\s*:\s*0\s*;'            # 退化的三元
Select-String -Path "<asm>" -Pattern '^\s*and r\d+\.\w+, r\d+\.\w+, l\(\d+\)$'      # asm 里的惯用法
```

把两边**逐一配对,数量必须相等**;把这个断言写进修补脚本,数量对不上就停下核对,
不要只修 grep 到的那几处就算完。修法 = 按 asm 的常量还原:`rX = rX ? N : 0;`。

**为什么危险**:这些值几乎总是拿去当**数组 / cbuffer 索引**(本案是 `icb[r14.w+0]`、
`icb[r14.w+4]`,而 icb 恰好 = 4 项轴基向量 + 6 项 cubemap 面参数表,索引钉死成 0 ⇒
立方体面选择恒取同一面)。轻则画错,重则动态索引落到非预期位置。

**验证靠编译回环,不靠肉眼**:改完编译再 `cmd_Decompiler --disassemble-ms`,
原 asm 里的 `and rX, rX, l(N)` 必须重现(寄存器号可以不同,编译器自己分配)。
没修的那版会被编译器把 `? 0 : 0` 常量折叠掉,那两条 `and` **根本不会出现** —— 差别一目了然。

⚠ **探针档会掩盖这类缺陷**:`ANISO_DEBUG_MODE 1..5` 提前 `return`,编译器把后面整段
(常含光源循环)优化掉,bin 能从 75 KB 缩到 18 KB。所以它们**只在完整档 0 / 6 执行**。
「Gate 1、Gate 2 全过,一切到 Gate 3 就出事」是这类缺陷的典型时序 ——
**别据此以为是接线或性能问题**,回头查 E1 / E2 / E6 这一类「编译得过但值错」的地方(E6 见下一节)。

### E3 / E4 / E5:另外三类「编译不过」的反编译缺陷(cmd_Decompiler 1.3.16,通用)

和 E1 一样会被严格编译拦下,各有固定修法,**不要**因此判成「大面积错误」退回 asm 路线。
庄方仪 `19c279d21b2035d5`(2026-09-09)、last rite `eeb2d6fb78e5a7a8`(2026-09-10)两份**补丁后**字节码里都出现,
只是寄存器与行号不同:

| 类 | 游戏字节码(msasm) | 反编译写成 | 症状 | 忠实修法 |
|---|---|---|---|---|
| **E3** 不认 1D 贴图 | `dcl_resource_texture1d (float,float,float,float) t120`,之后 `ld … t120` | 漏掉 `t120` 的声明;`ld` 被写成**缺对象名**的 `.Load(float4(245,0,0,0))` | X3000 语法错 | 在其他贴图声明旁补 `Texture1D<float4> t120 : register(t120);`,每处改成 `t120.Load(int2(245,0))`(1D 的 Load 参数 = (x, mip)) |
| **E4** 带立即偏移的 load | `ld_aoffimmi(1,1,1) …, r43.xyxx, t61` | `t61.Load(r43.xy, int3(0, 0, 0))` —— 坐标少一维、**偏移丢成 0** | 编译报错(没有这种 Load 重载) | `t61.Load(int3(r43.xy, 0), int2(1, 1))`:坐标 = `int3(xy, mip)`,偏移照 asm 抄 |
| **E5** 跨块赋值 / 使用 | 寄存器在 if 块里赋值、块外使用 | 原样照搬 | `/WX` 下 X4000「可能未初始化」即错误 | 只给编译报告点名的寄存器在 `main` 开头显式赋 0(例 `r36 = 0; r40 = 0;`)。消的是编译器的保守警告,可达路径行为不变 —— 对照 asm 确认那几条路径本来都赋过值 |

- 两案里 E3 都出在 RabbitFX 注入的 `t120`(CutoutMask 哨兵 x245、开关 x172、发光 HSV x217),E4 出在 RabbitFX 的
  FXMap `t61` / GlowMap `t60` ⇒ **以补丁后字节码(ShaderCache 的 `<hash>-ps_regex.bin`)当底子时要预期遇到**。
- 修补写成脚本:输入必须是**一字未改的反编译原件**(已经含 `Texture1D` 就拒绝,防止重复修);每个锚点断言恰好命中 1 次;
  E1–E5 修完、**不加任何效果**再严格编译一次,0 告警才算底子干净。

### ⭐ E6 / E6c / E7:位模式与数值混用 —— 编译得过、晴天看不出,雨雪和灯光静默丢失

2026-09-10 last rite 案实录(`eeb2d6fb78e5a7a8`,透肉派生版上线、用户先说「效果很好」,之后才报「丝袜上的雨水没了」)。
反编译器把所有寄存器声明成 float4,整数结果按**数值**存。对小整数没问题,但下面三种情况会算错,
**严格编译、反射对照、探针、E2 回环全部放行**:

| 类 | 游戏字节码 | 反编译写成 | 后果 |
|---|---|---|---|
| **E6** 整数指令吃原始位 | `movc r4.x, …, cb2[r2.w + 13].x` 后 `and r4.w, r4.x, l(255)` / `ubfe` / `ushr l(24)` | `(int)r4.x & 255`、`(uint)r4.x >> 24` | 天气字(打包 uint)的位模式按 float 读约 1e-38,数值转整数 = 0 ⇒ 四字节恒 0 ⇒ **无雨无雪**;灯光 `cb4[..+6]` 的字节字段同理 |
| **E6c** 条件直接判原始位 | `if_nz cb4[r12.z + 6].w` | `if (cb4[r12.z+6].w != 0)` | 灯光类型是整数 1..16,位模式是非规格化数,浮点比较可能被冲成 0 ⇒ 带类型的灯光分支走错 |
| **E7** 整数指令造浮点位模式 | `and r9.w, v11.x, l(0x3f800000)`(正面 = 1.0) | `(int)v11.x & 0x3f800000` | 存成 1065353216.0,乘进落雪遮罩;「按位取绝对值再判 NaN」那一对指令同理 |

**查法(必做,两步)**:

```powershell
$env:PYTHONIOENCODING = 'utf-8'
python <skill>\scripts\audit_raw_int_ops.py "<游戏字节码反汇编>"          # 列出 E6 / E6c / E7 候选
Select-String -Path "<反编译产物>" -Pattern '0x3f800000|0x7fffffff|0x80000000|0x7f800000'   # E7 以这个为准
```

**逐条回反编译判定**(脚本只看字节码,看不到反编译是怎么写的):

- E6:反编译已写 `asint()` / `asuint()` → 无害;写成 `(int)` / `(uint)` → 缺陷。
  例外:游戏字节码里本来就是 `ftou` / `ftoi` 的地方(如 `ftou r16.w, cb4[..].w`),`(uint)cb4[..]` 是对的。
- E6c:判断的是**真浮点**(贴图尺寸、贴图像素、IniParams)→ 位非零 ≡ 浮点非零,无害;判断的是**整数字段**(灯光类型之类)→ 缺陷。
- E7:脚本误报很多(「比较掩码 & 浮点值」惯用法已被正确译成 `cond ? x : 0`);以 grep 位技巧常数为准,前面是 `(int)` / `(uint)` 的就是缺陷。
- `icb` 里本来就是数值整数的项(如 cubemap 面表的 2 / 1 / 0),`(int)icb[..]` 是对的。

**修法**(照字节码逐位还原):

```hlsl
// E6 天气字:直接从常量缓冲按位取,不经过 float 寄存器
{ uint _ww = (0.5 < cb1[117].x) ? asuint(cb1[117].y) : asuint(cb2[r2.w+13].x);
  r12.x = (float)(_ww & 255u);          r12.y = (float)((_ww >> 8) & 255u);
  r12.z = (float)((_ww >> 16) & 255u);  r12.w = (float)(_ww >> 24); }
// E6 灯光字节:   r25.x = (asuint(cb4[r20.x+6].w) >> 16) & 255;
// E6c 灯光类型:  if (asint(cb4[r12.z+6].w) != 0) {
// E7:           r9.w = asfloat(v11.x & 0x3f800000u);
//               r21.w = asfloat(asint(r20.w) & 0x7fffffff);   r21.w = cmp(0x7f800000u < asuint(r21.w));
```

**验证靠编译回环**:修后编译,字节码里的 `if_nz cb4` / `and v11.x, l(0x3f800000)` / 天气字的 `and 255 → ubfe → ushr 24`
必须原样重现,`ftou` / `ftoi` 条数下降(last rite:修前 38 / 22,修后 34 / 20,游戏 4 / 6;余下是无害的「整数存 float 再转回」往返)。
修补脚本里的残留断言**只查去掉注释的代码** —— 修补行的注释会引用旧写法,全文计数会把自己卡成 FAIL。

- ⚠ **连锁**:E7 的正反面乘子以前被 E6 盖住(天气字恒 0,落雪永不触发),修好 E6 才暴露,必须同批修。
- ⚠ **只有雨天 / 雪天实机能验证**,晴天所有门都过。替换过材质 PS 的 mod 报「没湿身 / 不落雪」,先查这一节,再按 efmi-wetskin 查槽位。
- ⚠ 已知受影响:`19c279d21b2035d5`(庄方仪 V4 底子,反编译 350–357、1207、1837 / 1974、1849 / 1850 / 1854、1945–1946,**未修**);
  `eeb2d6fb78e5a7a8` 已修(作者本机的一次性修补脚本第 6–8 类;通用版见本包 `scripts/fix_decompiler_defects.py`)。
  hunting 导出的 `_replace.txt` 出自 3DMigoto 同一个反编译器,同样要查。

---

## 3. INI 双层框架

`[ShaderOverride]` 给该 hash 的**所有** draw 打标,本身不能按 draw 缩小范围。真正的 draw
限制由「目标原绘制入口 + CommandList」完成。**禁止把 `ps = replacement.hlsl` 直接放进
`[ShaderOverride]` 或全局 `[TextureOverride]`** —— 那会把深度 / 阴影 / 其他材质 pass 一起换掉。

### 3a. 标记主 PS:先看有没有现成的

> ⛔ **`ps == 1718.1` 永远不能单独当门控 —— 必须与 `vs == 2xx` 联合。**
> 2026-09-09 庄方仪案实机卡死换来的:`1718.1` 是 RabbitFX `[ShaderRegexMain]` 用正则贴到
> **一整族**材质着色器上的标,**它不认 hash**;而**同一个 draw 在一帧里会绑好几个 PS**。
> 该案丝袜的同一 draw 绑了 4 个 PS,其中材质 pass(`vs==202`)与描边 pass(`vs==203`)
> **都带 1718.1**,但描边那个 **没有 cb7、只有 7 个 interpolant**,而替换 PS 读 `cb7[160]`
> 和 11 个输入 ⇒ 读未绑定常量缓冲 + 动态索引 ⇒ 访问未映射显存。
> 正确写法:`if vs == 202 && ps == 1718.1`。判据见下方 3c。

| 情况 | 做法 |
|---|---|
| 装了共享 RabbitFX,且它的 `[ShaderRegexMain]` 匹配到这份 PS | 复用 `ps == 1718.1`,不加 `[ShaderOverride]`;**但必须再加 `vs == <材质 pass 号>` 一起用**(见上方警告) |
| 没有 RabbitFX,或它的正则没匹配到 | 自己加一段,值必须先全局审计(第 4 节): |

```ini
[ShaderOverrideAnisoSourcePS]
hash = <MAIN_PS_HASH>
filter_index = <全局统一值;确实不存在才分配新值>
allow_duplicate_hash = overrule
```

注意 `1718.1` 是**正则**打的标,一次贴到十几个不同 hash 的材质 PS 上;它不是「一个角色一个值」。
门控写 `ps == 1718.1` 能排除阴影 pass(阴影 pass 的规则打的是 `1718.2`),**但排除不了描边 pass**(它也带 1718.1) ⇒ 必须再加 `vs == <材质 pass 号>`,见上方 ⛔。
反过来这也意味着**门控不认 hash**:同一切片在别的 LOD 若绑了另一个材质 PS,替换 PS 会被
套到错误的二进制上。接每一个入口前都要证明它绑的 hash 与转储一致。
证明「正则会匹配这份 PS」:把 `[ShaderRegexMain]` 的正则转成 Python(`\h`→`[ \t]`、
`(?<n>`→`(?P<n>`)对转储内嵌反汇编跑一遍;或看 `d3d11.log` 的 matches 行。

### 3c. 必做:用归档帧转储证明「这个 draw 只在目标 hash 上命中门控」

**接线前跑一遍,别等实机。** 帧转储 `log.txt` 里
`PSSetShader(...) hash=X` 与 `DrawIndexedInstanced(...)` **共享同一个 6 位 call 编号**,
据此能精确还原「每次目标 draw 当时绑的是哪个 PS、哪个 VS」。做三件事:

1. **列出目标 draw 绑过的全部 PS**。不止一个是常态(材质 / 描边 / prepass / pose 各一个)。
2. **逐个判断它们带不带同一个标**:看 `E:\EMFI\ShaderCache\<hash>-ps_regex.bin` 在不在,
   再反汇编比对**注入特征**——读同一组 IniParams 槽 = 被同一条正则处理 = 带同一个 filter_index。
3. **比对资源需求**:`dcl_constantbuffer` 列表与 `dcl_input_ps` 个数。
   只要有任何一个「同标但少 cb / 少 interpolant」的 PS,单靠 `ps ==` 就是不安全的。

然后用 `vs == <材质 pass 号>` 把它钉死,并验证:该 vs 在全部转储里与目标 PS **一一对应**。
本项目里 mod 自带的 Fresnel overlay 若已用 `vs == 202` 且长期稳定,那就是现成的活证据。

⚠ **探针档全绿证明不了这件事**:`ANISO_DEBUG_MODE 1..5` 提前 return,编译器把 cb7、
高编号 interpolant 全优化掉,**退化后的资源需求恰好和那个"同标小 PS"兼容**,所以套错了
也不越界。只有完整档才暴露。这正是庄方仪案 Gate 1/2 全过、Gate 3 卡死的机理。

### 3b. 每个目标 draw 一个 CustomShader + 一个 CommandList

段结构示例见本包 references/ini-template.md(原入口换成 `run = CommandList…`,CommandList 里
`if ps == <标记>` 走 CustomShader、`else` 回退原 draw)。规则:

- 段名带 mod 标识和部件名,两个 mod 同时用不撞名。
- 同一逻辑部件在 LOD / 多个 VS 分支里重复出现的入口,**调用同一个 CommandList**。
- `else` 里的 draw 必须和原行逐字一致。
- 改 ini 全程**走字节**:作者注释常是 GBK,CRLF 也不能翻成 LF;整体解码再写回会静默损坏。
- 交付 `ps = .\res\xxx.hlsl` **源文件**,不交付 `.bin`:CustomShader 的 hlsl 按 F10 即时重编译,
  便于调参;bin 只是本轮编译 / 反射的校验产物。

---

## 4. `filter_index` 全局审计(P0,比编译着色器更早)

```powershell
python scripts\audit_filter_index.py "<真实 Mods 根目录>" --gate "ps == 1718.1"
```

必须扫**真实**的 Mods 根目录,副本上的「绿」没有意义。判定:

```
只有一个已有值      -> 复用它
多处定义但值相同    -> 可以继续
同一 hash 出现不同值 -> P0 冲突,禁止安装,先统一(让自己的 mod 复用已存在的值)
完全没有定义        -> 才分配新值,分配后再全局搜一遍确认
```

`allow_duplicate_hash = overrule` 不会合并两个不同标记,后加载的覆盖前一个,至少一边永远进
else,表现为**「一切看起来都对但完全没效果」**。P0 没解决时,着色器里任何调参都不会显示。

---

## 5. 编译与反射(静态门,全绿之前不进游戏)

```powershell
python <skill>\scripts\reflect_check.py "<mod>\res\<replacement>.hlsl" `
    --original "<转储.txt>" `
    --matrix ANISO_DEBUG_MODE=0,1,2,3,4,5,6 `
    --require <mod 实际注入的槽,如 t70 t71 t72 或 t15 t16 t17>
```

它做的事和为什么:

| 检查 | 为什么 |
|---|---|
| 原转储原文严格编译 | 判忠实性(第 2 节) |
| 替换 PS 出厂档 `/Ges /WX /O3` | 警告即错误;不许关 `/WX` 掩盖 |
| 开关矩阵全组合 | **没打开的 `#if` 分支里藏的错误**在游戏里只表现为角落一行红字,极易被当成「没效果」 |
| t# / s# 集合与类型和原 PS 一致 | 少了 = 被优化掉或你删了采样;多了 = 新增未证明的绑定 |
| cb 声明一致 + 立即索引不越界 | 原 `cb6[10]` 最高合法索引是 9 |
| 输入 / 输出签名一致 | `SV_IsFrontFace`、MRT 数量和掩码不能变 |
| `--require` 的槽真的反射出来 | 只在 HLSL 里声明、没实际采样会被优化掉,不算通过;`--require` 列出的槽自动视为允许比原 PS 多出 |

指令数只看不判定,编译器优化会让它浮动。默认不另记 SHA-256、不写报告文件:生成的 hlsl 头部带重建命令和底子 sha,那就是全部记录。**工作区要求报告 / 校验和时按工作区规矩**,把 SHA-256 和本次结论写进它指定的报告与校验和文件。

---

## 6. 贴图注入审计

原游戏 PS 读自己的槽,mod 把贴图放哪一槽是另一回事,两种风格:

| mod 风格 | 特征 | 替换 PS 要做的 |
|---|---|---|
| **RabbitFX SetTextures** | draw 前 `run = CommandList\RabbitFx\SetTextures`,贴图注入 `ps-t70/t71/t72` 等高槽 | 声明并**实际采样**高槽,`GetDimensions != 0` 就用高槽,否则回落原槽;反射里必须看到 t70/t71/t72 |
| **槽位式** | draw 前直接 `ps-t15 = ResourceXXX` 一类,写进原 PS 本来就读的低槽 | 逐字复制转储 PS 即自动兼容;**不新增任何绑定** |

**替换 PS 绕过 ShaderRegex**:游戏里实际跑的是正则打过补丁的 PS,转储是补丁前的原件,
`ps = xxx.hlsl` 也不再被正则处理。该切片上 RabbitFX 注入的一切(高槽切换、湿身 / 落雪、
审查开关)都会消失。需要保留的功能要手工并进替换 PS,在回复里写明「这个切片失去了什么」。

判断方法:看目标 draw **之前**实际执行了哪些 `ps-t#` 赋值,列出 Diffuse / LightMap / NormalMap /
Mask 的真实槽位。**具体原始槽从当前 PS 确认,不能假设所有 shader 都是 t16/t17/t18。**
⚠ 永远不要把效果贴图塞进 `ps-t0/ps-t1`(几何材质槽),本项目实测会让 GPU 崩溃。

RabbitFX 桥接写法:

```hlsl
Texture2D<float4> t70 : register(t70); // Diffuse
Texture2D<float4> t71 : register(t71); // LightMap
Texture2D<float4> t72 : register(t72); // NormalMap
uint w, h;
t70.GetDimensions(w, h);
float4 diffuse = (w != 0 && h != 0) ? t70.SampleBias(s2_s, uv, bias) : t16.SampleBias(s2_s, uv, bias);
//                                                                        ^ 原槽(此处 t16 只是示例,以当前 PS 为准)
```

---

## 7. 安全安装

1. 写入范围只在用户指定的 mod 目录;目标路径必须满足 `FullPath(target).StartsWith(FullPath(MOD_ROOT) + "\")`。
2. 安装前重新读目标文件 SHA-256,与最初快照不一致就停(游戏自动重编译了缓存,或用户同时在改)。
3. 首次施工建 `<file>.bak_preaniso`(永远是最初状态,不覆盖);之后每次再装另建时间戳备份
   `<file>.bak_preaniso-YYYYMMDD-HHMMSS`。
4. 先复制到同盘 stage 文件并核对 SHA-256,再用 `File.Replace`(原子)替换;**不要先删再复制**。
5. HLSL / ini 任一替换失败,立即用备份回滚已替换的文件。
6. 安装后再核对目标 SHA-256,并确认加载器、Core、其他 mod 零变化。
7. 派生版建**独立 mod folder**,原版加 `DISABLED_` 停用,两者不同时启用。

---

## 8. 「不要这样做」清单

| | 错误 | 后果 / 正解 |
|---|---|---|
| A | 只写一个全局 `if ps == hash` | 只证明 PS 被标记,不证明目标 draw 用了替换 shader。必须改入口 + CommandList |
| B | 用 `pow(1 - NdotV, n)` 冒充随光移动的亮带 | 那是 Fresnel 边缘光,永远只在轮廓;中部亮带必须 `H = normalize(L + V)` |
| C | 把别的 hash 的 `r13 / r21 / v4` 直接复制 | 另一份 PS 里同名寄存器可能是颜色、深度或未初始化值 → 紫色 / 黑块 / 游动条纹 |
| D | `o0.rgb += white * highlight` | HDR 累加曝成白带;先限权重再 `lerp` 到目标色 |
| E | 为了修黑色把常量调很大 | 整片乌黑先查 transmission / 法线空间 / 原色变量 / alpha 分支,不是强度 |
| F | 编译成功就当替换成功 | 还要反射、ini 命中、filter_index 命中、游戏内四道门 |
| G | 只改 LOD0 一处 | 队友位强制走 LOD1,远近切换效果消失;全文搜完整五字段逐个判断 |

---

## 9. 失败审计优先级

「按模板改了但没效果」时按这个顺序查,**P0 没解决前不讨论视觉参数**:

```
P0:相同 hash 是否在其他启用 mod 里被打了不同 filter_index?
P0:目标当前是否实际走被修改的 LOD / VS / IB 入口?
P1:replacement 是否实际读取 mod 注入的贴图槽?
P1:L 是否来自已验证的主光捕获点,而不是随便一个 float3?
P1:纯绿命中测试是否真的由用户在游戏里确认?
P2:严格编译、反射、缓存是否一致?
P2:非主 pass 是否仍回退原 draw?
```

---

## 10. 完成判定与回复格式

只有同时满足才算完成:全局同 hash `filter_index` 统一;指定 draw 在材质 pass 用替换 PS;
非主 pass 回退原 draw;入口闭环 `N = M + K`;反射证据与注入槽一致;四道门通过;严格编译 /
反射 / SHA-256 全过;只改指定 mod 且有时间戳备份。

回复用这个骨架,**「已完成」和「未安装」二选一**,不用「应该可以」代替证据:

```text
已完成 / 未安装

主 PS:<hash>,filter_index:<值>(来源:RabbitFX 复用 / 自加 ShaderOverride)
已处理目标:
- <部件>:<完整 draw>,命中 <N> 个入口 = 已接 <M> + 不接 <K>(理由)
视觉算法:H = L + V 各向异性核心 + halo + 浅棕 lerp;不是轮廓 Fresnel
验证:fxc 严格编译 <通过/失败>;反射 <通过/失败>;HLSL / ini SHA-256:<…>
备份:<绝对路径>
未修改:加载器、Core、RabbitFX、其他 mod
实机:Gate 1 <绿/未测> → Gate 2 <…> → Gate 3 <…> → Gate 4 <…>
```
