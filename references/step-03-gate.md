# 步 03：审计双门控与更新失效点

## 目标

证明材质 VS 标签与 RabbitFX 主 PS 标签都有人定义且无全局冲突，并明确仍需由正则命中证据和实机纯绿检查补上的边界。

## 进入条件

- [ ] 步 02 已记录主控材质 VS / PS 组合与目标 PS hash。
- [ ] 已从 U1 推出真实 `<Mods 根>`；推不出时已经向用户索取。
- [ ] 本步只扫描启用中的 ini，不修改 mod 或共享组件。

## 输入

| 占位符 | 是什么 | 从哪来 | 例子（2026-09 案例，勿照抄） |
|---|---|---|---|
| `<Mods 根>` | 3DMigoto 的真实 Mods 根目录 | 从 U1 向上推出，失败时问用户 | `D:\3DMigoto\Mods` |
| `<材质 pass 值>` | CrossIB 分类器给材质 VS 的 filter_index | 从当前分类器 / 帧命令现场读取 | `202` |
| `<RabbitFX 主值>` | RabbitFX 主材质 ShaderRegex 的 filter_index | 从当前 RabbitFX.ini 现场读取 | `1718.1` |
| `<分类器目录>` | 全局唯一 CrossIB 分类器目录 | `<Mods 根>\character\others\CrossIBClassifier` | `D:\3DMigoto\Mods\character\others\CrossIBClassifier` |
| `<已装分类器 ini>` | 当前启用的 CrossIBClassifier.ini | 扫描 `<Mods 根>` 后找到 | `D:\...\CrossIBClassifier.ini` |
| `<作者新版分类器 ini>` | 用户取得的工具作者当前版本 | 游戏更新后才进入此分支 | `C:\Temp\CrossIBClassifier.ini` |
| `<RabbitFX ini>` | 当前启用的共享 RabbitFX.ini | 审计输出路径 | `D:\3DMigoto\Mods\BufferValues\RabbitFX.ini` |
| `<底子 HLSL>` | 目标 PS 的补丁后 HLSL | 步 00 / 04 | `C:\Temp\efmi-sheer\case\source.fixed.hlsl` |
| `<目标 PS hash>` | U2 文件名中的 PS hash | 步 00 | `0123456789abcdef` |
| `<d3d11 日志>` | 本次启动产生、含 ShaderRegex matches 的日志 | 用户提供或当前 3DMigoto 根 | `E:\EMFI\d3d11.log` |

## 操作

1. 从当前启用的分类器和 RabbitFX.ini 读取实际 filter_index。计划中的数字只能当 2026-09 示例；命令必须使用现场读到的值。
2. 审计材质 VS 门：

   ```powershell
   python scripts/audit_filter_index.py "<Mods 根>" --gate "vs == <材质 pass 值>"
   ```

3. 审计 RabbitFX 主 PS 门：

   ```powershell
   python scripts/audit_filter_index.py "<Mods 根>" --gate "ps == <RabbitFX 主值>"
   ```

4. 两次输出都要同时检查三件事：扫描的是实际 `<Mods 根>`；没有同一 hash 被赋不同 filter_index 的 P0 冲突；门控值至少有一处启用定义。多个定义使用同一个值可以继续；同 hash 不同值必须停下统一。
5. CrossIB 分类器确实不存在时，只安装本包原样文件，全局只保留一份。先告知用户安装位置，再创建目录：

   ```powershell
   pwsh -NoProfile -Command "New-Item -ItemType Directory -Force -Path '<分类器目录>'"
   ```

   再复制分类器：

   ```powershell
   pwsh -NoProfile -Command "Copy-Item -LiteralPath 'assets\CrossIBClassifier.ini' -Destination '<分类器目录>\CrossIBClassifier.ini'"
   ```

   完全重启游戏后重跑第 2 项。分类器已存在时不得复制第二份。游戏更新后若用户提供作者新版，先读取版本注释并比较文件；确认作者新版后用作者文件替换，不把本包快照当更新源。
6. 记录审计边界：`audit_filter_index.py` 只证明 ini 里“有人声明这个值”，不能证明 `[ShaderRegexMain]` 仍匹配目标 PS。用本次 `-ps_regex.bin`、帧转储 `--cmds` 的执行记录或 `d3d11.log` 的 matches 行证明实际命中。
7. 有本次 `d3d11.log` 时先定位目标 hash，再人工确认同一 matches 记录指向 RabbitFX 主规则：

   ```powershell
   pwsh -NoProfile -Command "Select-String -LiteralPath '<d3d11 日志>' -Pattern '<目标 PS hash>' -Context 3,3"
   ```

   只有“目标 hash 与主规则命中出现在同一记录”才算正则证据。只搜到 hash、只搜到规则名、或只有门控声明都不算。
8. 组合门写成 `vs == <材质 pass 值> && ps == <RabbitFX 主值>`。PS 半门不能单独使用：同一 draw 的描边 pass 也会带 RabbitFX 主值，替换材质 PS 套到资源更少的描边 pass 会访问未绑定输入。
9. 游戏或 RabbitFX 更新后，严格按这个顺序复查：

   1. 判断已装 CrossIB 分类器是否为作者当前规则；有作者新版就先更新，全局仍只留一份。
   2. 重跑第 2、3 项两条审计。
   3. 装上检查版，在游戏里确认目标丝袜整块纯绿；不绿先查门控、ShaderFixes 残留与正则命中。
   4. 在新底子里重新定位“当前染色常量 × 漫反射”锚点，不能复用旧 cb 编号或旧行号；`cb6[6]` 只是一条 2026-09 案例线索。
   5. 从当前 RabbitFX.ini 重读高槽映射，再与底子里的 `t70`–`t74`、`t60` / `t61` 桥接逐项核对。

## 期望输出

本轮没有扫描现役 Mods。下面是 `audit_filter_index.py` 源码定义的输出结构示例，不是真实执行结果：

```text
MODS ROOT : {absolute-root}
已扫描启用中的 ini: ... 个(路径含 DISABLED 的已跳过)
按 hash 声明 filter_index 的着色器: ... 个
无 hash 的 ShaderRegex filter_index 取值: ...
----------------------------------------------------------------------------
OK: 没有发现「同一 hash 被赋予不同 filter_index」的冲突。 ← P0

门控 `{gate}` 的可满足性:
  找到 ... 处按 hash、... 处按 ShaderRegex 声明 filter_index = ... ← 声明存在
----------------------------------------------------------------------------
```

如果失败，固定结构会出现 `P0 冲突:` 或 `!! 没有任何启用中的 ini 声明 filter_index = ...`。这仍不代表正则已命中目标 PS；正则命中必须另有第 6 项证据。

## 判定

| 看到什么 | 结论 | 下一步 |
|---|---|---|
| 两条审计都无冲突且各自找到定义 | 双门具备声明基础 | 继续检查正则证据；然后进步 04 |
| 同一 hash 出现不同 filter_index | P0 全局冲突 | 停止安装；让本 mod 复用已存在的统一值后重跑两条审计 |
| 材质 pass 值没有定义 | 分类器缺失、停用或值已变 | 核对作者当前分类器；确实没有时从本包安装一份并完全重启 |
| RabbitFX 主值没有定义 | RabbitFX 缺失、停用或值已变 | 停下请用户启用当前 RabbitFX，或从当前 RabbitFX.ini 读取新值后重跑 |
| 审计找到声明，但没有 matches / `_regex.bin` / `--cmds` 命中证据 | 正则仍可能未匹配目标 PS | 不宣称门控完成；步 11 纯绿失败时先回本步 |
| 只有 PS 半门 | 描边 pass 无法被排除 | 禁止接线；补上材质 VS 半门 |
| 更新后检查版不绿 | 组合门或正则链断开 | 按第 9 项从分类器版本开始逐项重查 |

## 失败处理

| 症状 | 原因 | 修法 |
|---|---|---|
| 脚本报“不是一个目录” | `<Mods 根>` 指到了角色或单个 mod | 改成含所有 mod 的真实 `Mods` 目录后重跑 |
| 多个 ShaderRegex 产出同一值 | namespace 后解析者会覆盖先解析者 | 查看它们是否匹配同一目标 PS；命中重叠时保留唯一权威规则 |
| 分类器装了仍找不到材质值 | 游戏未完全重启，或分类器规则已过期 | 完全退出游戏；仍失败就换作者新版，禁止自己猜 VS hash 表 |
| `_regex.bin` 不生成 | ShaderFixes 同 hash 残留覆盖，或主正则不匹配 | 按步 00 移走残留再重启；仍无则使用补丁后 `_replace.txt` 并记录失配 |
| 门控表达式为真但其它部件也触发 | 入口范围过宽，或同 PS 画多个部件 | 回步 02 以原 draw 入口 + CommandList 收窄，Q1 / Q3 重新确认 |

## 产物

| 文件 / 变量 | 放哪 | 下一步谁用 |
|---|---|---|
| `<材质 pass 值>` 与定义路径 | 当前会话中的现场证据 | 步 09 组合门 |
| `<RabbitFX 主值>` 与定义路径 | 当前会话中的现场证据 | 步 09 组合门 |
| P0 审计结论 | 当前会话；工作区要求报告时写入项目报告 | 步 09、11 |
| 正则命中证据或“待纯绿验证”标记 | 当前会话 | 步 08、11 |
| 全局唯一分类器 | `<分类器目录>`；只有缺失时安装 | 后续材质 VS 标签 |

## 本步红旗

| 念头 | 现实 |
|---|---|
| “审计找到 1718.1 就证明正则命中” | 审计只读声明，目标 PS 可能已经不再匹配该正则 |
| “PS 门能排掉所有非材质 pass” | 描边也可能带同一个 RabbitFX 主值，必须加材质 VS 门 |
| “分类器多装一份更保险” | 全局重复规则会覆盖或漂移，始终只保留作者规则的一份 |
| “更新后沿用旧槽号和旧行号” | 游戏与 RabbitFX 会同时改变 shader、锚点和高槽映射 |
