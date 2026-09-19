# 步 09：接入 mod INI

## 目标

在 overlay 的 ini 副本中把目标 draw 接到双层门控、状态分支、检查版、肤色贴图和外观切换，其他 pass 与未选状态逐字回退原 draw。

## 进入条件

第 2、3 项是只读的槽位预审计：步 05 完成后、步 07 生成之前先执行，记下肤色槽号和外观下标，再回步 07。其余接线操作必须满足下列条件后才执行。

- [ ] 步 07 的全部正式状态严格编译通过；步 08 的交付检查等本步接线完成再执行，不能形成先后互等。
- [ ] 原 draw 的完整操作名、等号和全部参数、颜色变量和值已从 mod ini 读取并经用户确认。
- [ ] 所有正式 HLSL、probe 与肤色 DDS 已在 overlay 的目标相对路径中。

## 输入

| 占位符 | 是什么 | 从哪来 | 例子（2026-09 案例，勿照抄） |
|---|---|---|---|
| `<原mod ini>` | 用户给的原 mod ini | 步 00/02 | `D:\Mods\角色\mod.ini` |
| `<overlay ini>` | 保持同相对路径的施工副本 | 步 00 工作目录的 overlay | `%TEMP%\efmi-sheer\角色\overlay\mod.ini` |
| `<INI备份>` | 工作区要求 `.bak` 时的 ini 备份路径 | 工作区约定 | `%TEMP%\efmi-sheer\角色\overlay\mod.ini.bak` |
| `<Mods根>` | 3DMigoto 的 Mods 目录 | 步 00 | `D:\3DMigoto\Mods` |
| `<3DMigoto根>` | 含 `d3dx.ini` 的目录 | 从 `<Mods根>` 上一级得到 | `D:\3DMigoto` |
| `<mod标识>` | 新段名后缀，只用 ASCII 且全局不撞名 | mod 名压缩 | `YvonneBikini` |
| `<颜色变量>` | mod 已有状态变量，不含猜测 | 步 02 | `swapkey` |
| `<状态值一>` / `<状态值二>` | 用户选中的状态值 | 步 02 | `1` / `2` |
| `<状态标签一>` / `<状态标签二>` | 步 07 输出标签 | 步 07 | `black` / `white` |
| `<原始完整draw>` | 原命令整行，包含操作名、等号和全部参数，逐字复制 | 原 ini | `drawindexed = 12345,0,0`；原来是 instanced 则保留其五个参数 |
| `<材质 pass 值>` | 当前材质 VS 的 filter_index | 步 03 已通过审计的值 | `202` |
| `<RabbitFX 主值>` | 当前目标材质 PS 的 filter_index | 步 03 已通过审计的值 | `1718.1` |
| `<输出名>` | HLSL 文件前缀 | 步 07 | `sheer_main` |
| `<肤色槽号>` | 未占用 `ps-tN` 的 N | 本步全局搜索 | `90` |
| `<肤色资源段>` | 绑定肤色 DDS 的 Resource 段名，不带方括号 | 自定 | `ResourceSheerSkinYvonne` |
| `<肤色贴图相对路径>` | 相对 `<overlay ini>` 的 DDS 路径 | 步 06 | `Textures\SheerSkin.dds` |
| `<外观下标>` | 未占用的 `xN` 下标 | 本步搜索 `x25N` | `250` |
| `<在场变量>` | mod 自己定义并在 `[Present]`/菜单使用的变量 | 原 ini | `object_detected` |
| `<外观键>` | 全局未占用的 3DMigoto key 写法 | 本步搜索 | `ctrl alt no_shift VK_OEM_PERIOD` |
| `<原mod目录>` | 包含原 INI 和全部原资源的 mod 根 | 用户 U1 | `D:/Mods/OriginalMod` |
| `<overlay目录>` | 保持 mod 相对路径的改动目录 | 本步施工目录 | `D:/work/overlay` |
| `<验收目录>` | 工作目录内尚不存在的独立目录，不能填原 mod/overlay | 工作目录中新取名字 | `D:/work/check-mod-01` |

## 操作

默认必须完成高光两档接线，不能只生成 shader 而漏掉按键或 IniParams 传值。初始 `$style = 0` 表示启动只透肉；`1` 必须真的打开高光。不得因没有定位 N/L/T、没有找到空槽或想简化交付而省略；补齐现场证据后完成。

**先定位命令归属，再编辑。以下规则适用于新增透肉与返修接线：**

- 对每个目标 draw 记录：所属 section、完整 draw 操作及实参、全部外层分支条件、该路径实际 ib/vb 绑定、目标材质 pass。相同 draw 文本会在深度、材质、描边等 pass 重复；不得用全文件首次匹配或无上下文的 `replace(..., 1)` 决定修改位置。
- 把调用方条件与被调用 CommandList 的条件合在一起判断可达性，包含 `elif`/`else` 隐含的前支不成立条件。外层限定某个 VS 值、内层要求另一个 VS 值时，路径不可达；不能通过删除材质 VS 门控来让它命中。必须改到真实目标材质 draw，保留其它 pass。
- `[Section]` 一出现就结束前一段，缩进和空行不会保护原段。新增 CommandList/CustomShader/Resource/Key 优先追加到文件末尾；若放在别处，必须是原段完整结束后的段间位置。不能插在原段未完成的绘制命令中间，也不能插在尚未闭合的条件中间。
- 合并重复 `[Constants]` 或 `[Present]` 时，必须迁移**完整段体**到保留的同名段，保留原命令顺序，再移除被合并段；不能只删除段头。逐项确认变量声明仍属于 Constants、每帧命令仍属于 Present，Resource 段没有吞入绘制、控制流或变量声明。
- 改后按 section 比较改前/改后命令：除点名替换的 draw 与新增功能外，其余命令的段归属、执行条件和顺序必须保持。每段分别检查条件闭合，并核对整条调用路径；**全文件 if/endif 总数相等、HLSL 编译成功、反射通过，都不能替代这项接线检查**。复用已完成且输入不变的证据，不另跑无关 shader 或烘焙验证。

1. 复制原 ini 到 overlay，再只改副本：

   ```powershell
   pwsh -NoProfile -Command { Copy-Item -LiteralPath "<原mod ini>" -Destination "<overlay ini>" }
   ```

   工作区明确要求 `.bak` 时，在第一次编辑前从未改的原 ini 再复制一份到 `<INI备份>`：

   ```powershell
   pwsh -NoProfile -Command { Copy-Item -LiteralPath "<原mod ini>" -Destination "<INI备份>" }
   ```

   这份 `.bak` 只回滚本步对 ini 的接线修改；HLSL、DDS 与整个 mod 的回滚由工作区自己的 BASELINE/包负责。工作区指定 `.bak` 必须放在现役或工作副本旁时，把 `<INI备份>` 填成它要求的确切位置。

2. 搜全 Mods 的像素贴图槽，挑一个没有结果的 `<肤色槽号>`：

   ```powershell
   pwsh -NoProfile -Command { Get-ChildItem -LiteralPath "<Mods根>" -Filter "*.ini" -File -Recurse | Select-String -Pattern '^[ \t]*ps-t[0-9]+[ \t]*=' }
   ```

3. 搜外观用的高段 IniParams；`build_sheer_ps.py --style-index <外观下标>` 与 `x<外观下标>` 必须是同一个数：

   ```powershell
   pwsh -NoProfile -Command { Get-ChildItem -LiteralPath "<Mods根>" -Filter "*.ini" -File -Recurse | Select-String -Pattern '^[ \t]*x25[0-9]+[ \t]*=' }
   ```

4. 搜 mod 键和 `d3dx.ini` 已占键，再确定 `<外观键>`。字母键写裸字符，例如 `key = K`；不要写 `VK_K`。OEM 键照 3DMigoto 名称写：

   ```powershell
   pwsh -NoProfile -Command { $files = @(Get-ChildItem -LiteralPath "<Mods根>" -Filter "*.ini" -File -Recurse); $files += Get-Item -LiteralPath "<3DMigoto根>\d3dx.ini"; $files | Select-String -Pattern '^[ \t]*(key|back|reload_fixes|reload_config|analyse_frame|toggle_hunting|done_hunting|previous_\w+|next_\w+|mark_\w+|show_\w+|take_screenshot)[ \t]*=' }
   ```

5. 在 `<overlay ini>` 的现有 `[Constants]` 内加入 `$sheer_debug_<mod标识>` 和 `$sheer_style_<mod标识>`；同名 `[Constants]` 只能有一个。在该段追加以下两行，不加 `persist`：

   ```ini
   global $sheer_debug_<mod标识> = 0
   global $sheer_style_<mod标识> = 0
   ```

   把目标主控 draw 原行替换为：

   ```ini
   run = CommandListSheer_<mod标识>
   ```

6. 加入 CommandList。第一层只让目标材质 pass 进入替换；第二层选择 probe 或用户点名状态。两个 `else` 都逐字写回原 draw：

   ```ini
   [CommandListSheer_<mod标识>]
   x<外观下标> = $sheer_style_<mod标识>
   if vs == <材质 pass 值> && ps == <RabbitFX 主值>
     if $sheer_debug_<mod标识> == 1
       run = CustomShaderSheerCheck_<mod标识>
     elif $<颜色变量> == <状态值一>
       run = CustomShaderSheerState1_<mod标识>
     elif $<颜色变量> == <状态值二>
       run = CustomShaderSheerState2_<mod标识>
     else
       <原始完整draw>
     endif
   else
     <原始完整draw>
   endif
   ```

   门控行可以再加 `$变量 == 数字` 形式的状态限制，任意顺序、用 `&&` 连接：本 mod 在别的档位（例如 LOD1 队友）给同一 draw 绑另一套缓冲时，写成 `if $lod_level == 0 && vs == <材质 pass 值> && ps == <RabbitFX 主值>`（变量名以本 mod 自己的定义为准）。除 vs / ps 与 `$变量 == 数字` 外的表达式不能进门控。

7. 正式 PS 只能写在 CustomShader。B/C 路线的每个 CustomShader 都绑定同一个已审计空槽；A 路线删掉 `ps-t<肤色槽号>` 和 Resource 段：

   ```ini
   [CustomShaderSheerState1_<mod标识>]
   ps = .\res\sheer\<输出名>_<状态标签一>.hlsl
   ps-t<肤色槽号> = <肤色资源段>
   <原始完整draw>

   [CustomShaderSheerState2_<mod标识>]
   ps = .\res\sheer\<输出名>_<状态标签二>.hlsl
   ps-t<肤色槽号> = <肤色资源段>
   <原始完整draw>

   [CustomShaderSheerCheck_<mod标识>]
   ps = .\res\sheer\<输出名>_probe.hlsl
   ps-t<肤色槽号> = <肤色资源段>
   <原始完整draw>

   [<肤色资源段>]
   filename = <肤色贴图相对路径>
   ```

8. 加外观切换。`condition` 必须用该 mod 自己已定义的 `<在场变量>`。`$active0` 只在原 mod 定义它时可用；未定义变量会让整个 Key 段失效。EFMI 生成 mod 常见 `$object_detected`，也必须先从本 mod 的 `[Present]` 或 `[KeyMenu]` 读到再填：

   ```ini
   [KeySheerStyle_<mod标识>]
   condition = $<在场变量> == 1
   key = <外观键>
   type = cycle
   $sheer_style_<mod标识> = 0,1
   ```

9. 检查 `if`/`endif` 成对、每个 `run`/`ps`/`filename` 引用存在，并确认只替换用户选中的主控 draw。把步 02 状态表逐项对照本 INI，不能漏掉第二种颜色或其它选定档位。接线检查须能读取全部原资源；overlay 只有改动文件时，在临时目录合并原 mod 和 overlay：

   ```powershell
   pwsh -NoProfile -Command { if (Test-Path -LiteralPath "<验收目录>") { throw "验收目录已存在，请使用新的工作目录子目录" }; Copy-Item -LiteralPath "<原mod目录>" -Destination "<验收目录>" -Recurse; Get-ChildItem -LiteralPath "<overlay目录>" -Force | Copy-Item -Destination "<验收目录>" -Recurse -Force }
   ```

   现在回到 [步 08](step-08-static-gate.md) 的完整 `check_sheer_delivery.py` 命令，INI 和所有正式 HLSL 路径都指向这份验收目录，颜色 JSON 仍引用未改的原输入。按步 08 的改动范围确定本次待验项：首次对每个目标 draw、每种原状态 diffuse 的颜色报告各运行一次，并且每次列全该 draw 的正式 HLSL；返修复用输入不变的通过证据，只重验受影响项。检查器退出 0、无未验证项且每个资源签名组反射通过后才进步 10；仅已证实的检查器适配限制可按步 08 完成全部逐项补证后进入，不能自称已获工具 PASS。若修正了 overlay，再取新验收目录合并并检查，不能只修验收副本导致实际包仍错误。新 ini 段与 Key 段要完全重启游戏，F10 只重载 HLSL。

## 期望输出

本步以文件检查为主。以下是输出结构示例，不是本案真实 stdout：

```text
（Mods 根）\…\mod.ini:（行号）:ps-t（数字） = …
（Mods 根）\…\mod.ini:（行号）:x25（数字） = …
（3DMigoto 根）\d3dx.ini:（行号）:key = …
```

搜索结果用来排除已占槽和已占键；空槽本身不会产生一行“可用”的 stdout。

## 判定

| 看到什么 | 结论 | 下一步 |
|---|---|---|
| 段归属与完整路径正确，两层门控、两个 `else`、引用和状态分支闭合，步 08 交付检查或其规定的逐项补证完成 | ini 接线静态验证完成 | 进步 10；实机尚未通过 |
| `ps-t<肤色槽号>` 或 `x<外观下标>` 已出现在别的启用 ini | 槽位有冲突 | 选另一个无结果的号，并同步重建 PS/ini |
| `<在场变量>` 在本 mod 有定义且运行中会置 1 | Key 条件有效 | 进步 10 |
| 步 08 的 `D28` 点名一条带条件的路径（如 `$lod_level == 1`）绑了别的缓冲 | 那个档位也会进入替换 | 在门控加区分该档位的 mod 自有变量（如 `$lod_level == 0 &&`），不改绑定，回步 08 重跑 |
| 只找到别的 mod 的 `$active0` | 本 mod 不能引用它 | 从本 mod 的 `[Present]`/菜单找自己的变量；找不到就停下问用户：“切换键要始终生效，还是由哪个现有状态限制？” |
| 字母键写成 `VK_K` | 键名格式错误 | 改成裸字符 `K` |
| 目标键已被 Mods 或 `d3dx.ini` 占用 | 会同时触发别的功能 | 换未占键后重新搜索 |

## 失败处理

| 症状 | 原因 | 修法 |
|---|---|---|
| 阴影、深度或描边消失 | 外层 `else` 没逐字回退 | 恢复第二个 `<原始完整draw>` |
| 未选颜色状态消失 | 内层 `else` 漏了 | 恢复第一个 `<原始完整draw>` |
| 新 PS 对多个 draw 生效 | `ps =` 写进 ShaderOverride/TextureOverride | 移回目标 draw 的 CustomShader |
| 切换键完全无效 | `condition` 引用了未定义变量，或 ini 未重启 | 换本 mod 在场变量并完全重启 |
| 皮肤贴图未采样 | 槽号与生成 PS 的 `--skin-slot` 不一致 | 两处改成同一个槽并重跑步 08 |
| `D28` 实际网格绑定未获证明 | 某条可达路径上 CustomShader draw 时的 ib/vb0/vb1 不对应颜色报告 | 检查器沿 run / 回调 ref 链继承绑定并按分支分别核对：报的是别的档位路径就加门控变量；否则保留原绑定，从原 INI 核实实际 Index/Position/Texcoord，用真实目标重跑 preview；不能猜填绑定或更换网格来换 PASS |

## 产物

| 文件 / 变量 | 放哪 | 下一步谁用 |
|---|---|---|
| 接线后的 ini | `<overlay ini>` | 步 10 打包 |
| 可选 `.bak` | `<INI备份>`，只在工作区要求时 | 回滚与 review |
| 已确认空槽、外观下标、键和在场变量 | ini 与当前上下文 | 步 11 实机 |

## 本步红旗

| 念头 | 现实 |
|---|---|
| “只写 `ps == 1718.1` 就够” | 描边 pass 也会带该标；必须同时门控材质 VS |
| “一个 else 足够” | 门控失败与未选状态是两条独立退路 |
| “别的 mod 有 `$active0`，这里也能用” | ini 变量不凭名字自动存在 |
| “F10 会加载新 Key 段” | ini 结构变化必须完全重启游戏 |
| “找到同样的 draw 就替换第一处” | 先核对所属段与全部外层条件，选择实际材质 pass |
| “删掉重复段头就算合并” | 必须迁移段体并检查每条命令归属 |
