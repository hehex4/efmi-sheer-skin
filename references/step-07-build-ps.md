# 步 07：生成状态 PS 与检查版

## 目标

从忠实修补过的底子生成每个丝袜状态的正式 HLSL 和一份纯绿检查版，并让每份输出头部保留可复制的重建命令。

## 进入条件

- [ ] 步 05 的 V、N、注入点都有行号证据；默认高光切换所需 L、T、最终 N 也有证据，不能因启动档为 0 而省略。
- [ ] 步 06 已选定 A、B 或 C，并拿到肤色、袜色与 UV 框。
- [ ] 用户已确认哪些状态和哪些范围要透。

## 输入

| 占位符 | 是什么 | 从哪来 | 例子（2026-09 案例，勿照抄） |
|---|---|---|---|
| `<fixed HLSL>` | `fix_decompiler_defects.py` 的 `.fixed.hlsl` | 步 04 | `%TEMP%\efmi-sheer\fixed.hlsl` |
| `<PS输出目录>` | 状态 PS 的输出目录 | `<工作目录>` | `%TEMP%\efmi-sheer\overlay\res\sheer` |
| `<输出名>` | 文件名前缀，只用 ASCII | 自定并与 ini 一致 | `sheer_main` |
| `<状态一>` / `<状态二>` | `名@标签:键=值,…` | 用户状态 + 参数脚本 | `黑丝@black:ALPHA=0.45,W_MIN=0.65,W_MAX=1.0` |
| `<状态标签>` | `--state` 中 `@` 后的文件标签 | 用户状态 | `black` |
| `<肤色线性值>` | `r,g,b`，0–1 线性值 | 步 06 A 或对比档 | `1.0,0.624,0.565` |
| `<肤色槽>` | 生成 PS 将采样的空 `tN` | 步 09 预审计 | `t90` |
| `<肤色种类>` | `bareleg` 或 `baked` | 步 06 | `baked` |
| `<UV框>` | `u0,v0,u1,v1` | 步 06；独立整片可省该选项 | `0.12,0.48,0.61,0.98` |
| `<外观下标>` | IniParams 的 `N`，对应 ini 的 `xN` | 步 09 预审计 | `250` |
| `<最终法线证据>` | `寄存器.xyz@行号` | 步 05 | `r15.xyz@1268` |
| `<主光证据>` | `寄存器.xyz@行号` | 步 05 | `r17.xyz@1316` |
| `<染色常量>` | 注入锚点的染色 cb | 步 05 现场 grep | `cb6[6]`（2026-09 案例） |
| `<构建报告选项>` | 工作区要求报告时填 `--report`，默认留空 | 工作区约定 | `--report` |
| `<编译缓存目录>` | 生成/交付/反射共用的临时目录，不进入 overlay | 工作目录下新建 | `D:/work/compile-cache` |
| `<状态名>` | 参数建议标题 | 用户确认 | `黑丝` |
| `<肤色sRGB>` | 当前角色皮肤中位色 | 步 06 | `255,207,198` |
| `<袜色sRGB>` | 当前状态袜色中位色 | 步 06 | `76,64,66` |
| `<光腿固定乘数>` | 经光腿 PS 证明的固定线性 RGB；有限且非负 | 步 05/06 颜色链证据 | `1,0.8,0.7` |

## 操作

仅重建本次改动影响的状态。完整命令已使用 `--compiler d3dcompiler --compile-cache "<编译缓存目录>"`，目录取工作目录下 `compile-cache`，步 08 使用同一路径；已有相同条件编译结果由脚本校验复用，不另跑手工 fxc。若贴图文件改变但生成 HLSL 完全未变，不必重新生成 PS，回步 06/08 验受影响的来源与接线。完整重验范围见 [步 08](step-08-static-gate.md)。

生成前先独立完成步 09 第 2、3 项只读预审计，取得空的肤色槽和外观下标；此时不执行 INI 复制或接线，不要求尚未发生的步 08 反射结果。得到两个值后返回本步。

1. 每个状态先生成默认参数。B 路线也可把 `--bare`、`--variant`、`--box` 交给脚本；这里展示所有路线都能用的颜色输入：

   ```powershell
   python scripts/suggest_sheer_params.py --skin <肤色sRGB> --fabric <袜色sRGB> --name "<状态名>"
   ```

2. 每个透肉 mod 默认都做“0 只透肉 / 1 透肉 + 高光”的外观切换。把每个状态的 `SPEC_GAIN` 设为 `1.0`；运行时第 0 档会把高光乘成 0。脚本要求显式提供经审计的 `--style-index` 及 N/L 证据，缺少就报错；只在用户明确取消切换时才可改用互斥的 `--no-style-switch`。不得猜槽或用零增益假装完成切换。A 常数路线生成两个材质状态；没有第二材质状态就删掉第二个 `--state`，仍须保留 0/1 高光切换：

   ```powershell
   python scripts/build_sheer_ps.py "<fixed HLSL>" --out-dir "<PS输出目录>" --name "<输出名>" --state "<状态一>" --state "<状态二>" --skin <肤色线性值> --box <UV框> --style-index <外观下标> --aniso-n "<最终法线证据>" --aniso-l "<主光证据>" --tint-cb "<染色常量>" <构建报告选项> --compiler d3dcompiler --compile-cache "<编译缓存目录>"
   ```

3. C 烘焙贴图路线生成；同时给 `--skin` 会生成 `SHEER_SKIN_FROM_TEX` 对比开关，默认 1 用贴图、改 0 仅用于诊断对比。非单色正式交付必须保持 1，不能用常数档代替 B/C：

   ```powershell
   python scripts/build_sheer_ps.py "<fixed HLSL>" --out-dir "<PS输出目录>" --name "<输出名>" --state "<状态一>" --state "<状态二>" --skin <肤色线性值> --skin-slot <肤色槽> --skin-slot-kind baked --box <UV框> --style-index <外观下标> --aniso-n "<最终法线证据>" --aniso-l "<主光证据>" --tint-cb "<染色常量>" <构建报告选项> --compiler d3dcompiler --compile-cache "<编译缓存目录>"
   ```

4. B 光腿贴图路线使用 `bareleg`，并加 `--spec-stocking-only` 把高光限制在袜区。光腿与丝袜颜色链相同且已有步 05 证据时，使用完整的 shared 命令：

   ```powershell
   python scripts/build_sheer_ps.py "<fixed HLSL>" --out-dir "<PS输出目录>" --name "<输出名>" --state "<状态一>" --state "<状态二>" --skin <肤色线性值> --skin-slot <肤色槽> --skin-slot-kind bareleg --skin-tint-source shared --box <UV框> --style-index <外观下标> --spec-stocking-only --aniso-n "<最终法线证据>" --aniso-l "<主光证据>" --tint-cb "<染色常量>" <构建报告选项> --compiler d3dcompiler --compile-cache "<编译缓存目录>"
   ```

   光腿与丝袜染色不同，但光腿乘数是已证明的固定值时，运行此 constant 命令。该值只乘肤色，袜色仍用原锚点；不要改全局 tint 同时染两者：

   ```powershell
   python scripts/build_sheer_ps.py "<fixed HLSL>" --out-dir "<PS输出目录>" --name "<输出名>" --state "<状态一>" --state "<状态二>" --skin <肤色线性值> --skin-slot <肤色槽> --skin-slot-kind bareleg --skin-tint-source constant --skin-tint-linear <光腿固定乘数> --box <UV框> --style-index <外观下标> --spec-stocking-only --aniso-n "<最终法线证据>" --aniso-l "<主光证据>" --tint-cb "<染色常量>" <构建报告选项> --compiler d3dcompiler --compile-cache "<编译缓存目录>"
   ```

   固定乘数随材质状态不同，就按步 02 状态表拆成多次构建，每次只传对应的 `--state` 并保持文件名不冲突。动态 tint/叠层回步 05 获取来源和生命周期，完成专门映射后再生成；不能选择 shared 或填 `1,1,1` 跳过。

5. 核对每份正式 HLSL 顶部的重建命令包含本次所有 `--state`、肤色来源、框、槽位和高光证据。脚本默认还会生成 `<输出名>_probe.hlsl`：它固定 `ANISO_DEBUG_MODE 1`，只用于步骤 11 的纯绿检查。

6. `--state` 可写透肉模板中的参数名，`SHEER_` 前缀可省：`ALPHA`、`W_MIN`、`W_MAX`、`GAIN`、`SPEC_GAIN`、`SPEC_COUPLING`。`--report` 只在工作区要求报告时使用；`--out-dir` 永远显式给出。`--skin-slot` 只给一个贴图槽；B/C 语义由 `--skin-slot-kind` 区分。

7. 丝袜走皮肤族材质时，落雪布料修正是手工步骤，默认常开且不做切换。皮肤族遮罩写好后插入 `遮罩 = lerp(遮罩, 布料遮罩, 丝袜像素标记)`。以下仅是 2026-09 案例的公式结构：`smoothstep(saturate((N_up·0.65 + 雪壳噪声 B + 0.35 − T)·2.857)) × 落雪量 × 正面`；`0.65`、`0.35`、`2.857` 及其余数值必须从当前原版落雪 PS 读取后替换。`T = 1+(1−I)²` 必须在原代码覆盖它之前捕获；落雪量用现场确认的常数充当布料 `LightMap.B²`，不能抄旧案例。N、雪壳噪声 B、T、正面、原皮肤遮罩和写回点的寄存器与行号都按当前 hash 定位，并用 `regcheck.py` 证明各自从捕获到使用之间没有覆写。检查版不改；完成后重新严格编译，并在步骤 08 检查正式档。

## 期望输出

以下是输出结构示例，不是本案真实 stdout：

```text
== 锚点(行号 = 底子 .fixed.hlsl 的行号;每个都恰好命中 1 次)
V        第（行号）行 …
N / T    几何法线（寄存器）、切线（寄存器）
注入点   第（行号）行 …
== 输出
（输出目录）\（输出名）_（状态标签）.hlsl
（输出目录）\（输出名）_probe.hlsl  ← 检查版
== 编译自检
（文件名）: 严格编译通过,（字节数）B,sha256（值）  ← 每份都必须通过
```

## 判定

| 看到什么 | 结论 | 下一步 |
|---|---|---|
| 所有锚点恰好 1 次、所有正式档与 probe 严格编译通过 | 生成完成 | 进步 08 |
| `SHEER_SKIN_FROM_TEX` 为 1 且 `--skin`、`--skin-slot` 同时给出 | 正式档保留逐像素肤色，0 仅诊断对比 | 非单色交付确认仍为 1，进步 08 |
| B 重建命令的 shared/constant 与步 05 颜色链证据一致 | `bareleg` 语义正确 | 进步 08；constant 还须核对三个线性值 |
| C 输出显示肤色不乘染色常量 | `baked` 语义正确 | 进步 08 |
| 锚点命中 0 次或多次 | 底子或现场映射不成立 | 回步 05，不手填旧行号 |
| 任一文件编译失败 | 本轮没有可接线产物 | 按第一条 error 修正输入，再重跑本步 |
| 高光缺 N/L 行号证据 | 外观第 1 档不可生成 | 回步 05 按 [variable-mapping.md](variable-mapping.md) 定位 |

## 失败处理

| 症状 | 原因 | 修法 |
|---|---|---|
| 报已注入过透肉或高光 | 输入不是干净 `.fixed.hlsl` | 回步 04 取未注入底子 |
| 报 `--style-index` 缺 N/L | 外观切换依赖未给齐 | 补 `--aniso-n`、`--aniso-l` 的现场证据 |
| 报状态键不存在 | `--state` 参数名拼错 | 对照 `assets/sheer_core.hlsl` 的参数段改名 |
| 探针版资源槽少于正式档 | 纯绿提前 return 后被编译器优化 | 这是检查版预期行为；步骤 08 不对 probe 跑 reflect |
| 手工落雪后编译失败 | 抄入位置或类型不符 | 对照当前原版落雪 HLSL 的变量类型逐项修正，不改原数值 |

## 产物

| 文件 / 变量 | 放哪 | 下一步谁用 |
|---|---|---|
| `<输出名>_<状态标签>.hlsl` | `<PS输出目录>` | 步 08、09 |
| `<输出名>_probe.hlsl` | `<PS输出目录>` | 步 09、11 |
| 重建命令 | 每份 HLSL 头部 | 返修时直接重建 |
| 构建报告 | `<PS输出目录>`，只在工作区要求时 | 工作区报告与 review |

## 本步红旗

| 念头 | 现实 |
|---|---|
| “probe 也跑 reflect 更保险” | 纯绿路径会优化掉大段资源，反射差异没有判定价值 |
| “高光寄存器照抄另一个 hash” | 每个 hash 都必须在自己的底子里取证 |
| “落雪数字沿用旧案例” | 手工公式的数值只抄当前原版落雪着色器 |
| “输出能编译就不用看头部” | 头部重建命令是默认环境里的唯一返修记录 |
