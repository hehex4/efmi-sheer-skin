# 步 10：打包与交付

## 目标

得到一个通过 CRC 与条目数自检的 zip；默认放下载文件夹，工作区另有交付规则时按指定目录打包并完成同批启用/停用。

## 进入条件

**停止规则：任一 `reflect_check.py` 或 `check_sheer_delivery.py` 返回非 0、有 FAIL 或未验证项，先停在修复步骤，禁止创建交付 ZIP 或启用候选。写 BLOCKERS 报告不能代替通过验证。** 只有错误已修复并通过受影响检查，或已证实的检查器适配限制按步 08 完成全部逐项补证，才能恢复后续工作；实际产物错误或输入缺失不能用补证豁免。通用检查器仍 FAIL 时须保留原结论，另列补证结果，不称“工具全绿”。

- [ ] 步 08 每个实际编译签名组的代表正式 PS 已与原 shader 完成反射检查，所有检查通过。不能只看编译成功，也不能用交付接线检查代替原 shader 对照。

- [ ] 步 09 的 overlay 已包含接线 ini、HLSL 与肤色 DDS。
- [ ] overlay 中每个相对路径都与原 mod 内的目标位置一致。
- [ ] 七项检验清单前六项已经完成，全部目标 draw 与正式状态均有有效证据：交付检查通过，或仅其已证实的适配限制按步 08 逐项独立验证完成；没有未解决项，之后未修改输入或产物。

## 输入

| 占位符 | 是什么 | 从哪来 | 例子（2026-09 案例，勿照抄） |
|---|---|---|---|
| `<原mod文件夹>` | 含原 ini 的 mod 根目录 | 用户 U1 | `D:\3DMigoto\Mods\character\角色\OriginalMod` |
| `<overlay目录>` | 只含改动和新增文件 | 步 09 | `%TEMP%\efmi-sheer\角色\overlay` |
| `<交付名>` | zip 与包内顶层文件夹名，不带 `DISABLED_` | 默认由脚本生成；工作区可指定 | `OriginalMod_llx4` |
| `<交付目录>` | 工作区指定的包目录 | 工作区约定 | `E:\project\packages` |
| `<交付zip>` | 打好的 zip 完整路径 | `pack_mod.py` 输出 | `E:\project\packages\OriginalMod_llx4.zip` |
| `<角色目录>` | Mods 下该角色的直属目录 | 工作区约定 | `D:\3DMigoto\Mods\character\角色` |
| `<派生文件夹>` | 解压后新版本的完整路径 | `<角色目录>\<交付名>` | `D:\3DMigoto\Mods\character\角色\OriginalMod_llx4` |
| `<停用原版文件夹>` | 原版加 `DISABLED_` 后的完整路径 | 工作区命名规则 | `D:\3DMigoto\Mods\character\角色\DISABLED_OriginalMod` |
| `<ShaderFixes目录>` | 3DMigoto 的 ShaderFixes | 步 00 | `D:\3DMigoto\ShaderFixes` |
| `<PS哈希>` | 本次 U2 文件名中的目标 hash | 步 02 | `0123456789abcdef` |
| `<ShaderFixes备份目录>` | 只存目标 hash 标记导出文件 | 步 00 工作目录下新建 | `%TEMP%\efmi-sheer\角色\marked-shader-backup` |

## 操作

打包器的逐条读取/CRC/条目数检查执行一次即可。工作区还要求源字节或总字节对照时，只补打包器没有覆盖的那项；已有打包器逐字节对照结果可直接满足对应要求，不再另写第二套 ZIP 核验脚本。只有归档损坏、源文件在打包期间变化、打包器代码改动或核验失败才扩大检查。记录 SHA 是标识产物，不是要求再次跑一遍相同内容检查。

打包前核对步 08 的肤色来源与高光切换证据：有可用光腿状态身体贴图时优先 B；非单色不得用常数代替。默认包必须含可工作的 0/1 高光切换，启动为 0。只有用户明确取消高光功能才记录该例外；算法失败或缺少参数不构成例外。

1. 默认交付：不传 `--out`，脚本把 zip 放到系统真实“下载”文件夹；默认包名是原名去掉 `DISABLED_` 后加 ` Sheer`：

   ```powershell
   python scripts/pack_mod.py --src "<原mod文件夹>" --overlay "<overlay目录>"
   ```

2. 工作区指定 packages、命名或报告位置时，显式传 `--name` 与 `--out`：

   ```powershell
   python scripts/pack_mod.py --src "<原mod文件夹>" --overlay "<overlay目录>" --name "<交付名>" --out "<交付目录>"
   ```

3. 读最后一行，必须同时看到文件数与“自检通过”。默认交付回复固定写三句话：

   1. 解压 zip，只会得到一个顶层 mod 文件夹。
   2. 把它放进 `<角色目录>`，并给原版文件夹加 `DISABLED_` 前缀，或在 mod 管理器里停用原版。
   3. 完全退出游戏后重新启动；新增 ini 段不能只靠 F10 加载。

4. 工作区要求直接装机时，先确认 `<派生文件夹>` 尚不存在，再用一个 PowerShell 进程完成解压与原版停用；这是同一批操作，不能留下两个启用版本：

   ```powershell
   pwsh -NoProfile -Command { $role = [IO.Path]::GetFullPath("<角色目录>").TrimEnd('\'); $source = (Resolve-Path -LiteralPath "<原mod文件夹>").Path.TrimEnd('\'); $derived = [IO.Path]::GetFullPath("<派生文件夹>").TrimEnd('\'); $disabled = [IO.Path]::GetFullPath("<停用原版文件夹>").TrimEnd('\'); if ([IO.Path]::GetDirectoryName($source) -ne $role -or [IO.Path]::GetDirectoryName($derived) -ne $role -or [IO.Path]::GetDirectoryName($disabled) -ne $role) { throw "原版、派生版和停用目标必须直属角色目录" }; if (Test-Path -LiteralPath $derived) { throw "派生文件夹已存在" }; if (Test-Path -LiteralPath $disabled) { throw "停用原版目标已存在" }; Expand-Archive -LiteralPath "<交付zip>" -DestinationPath $role; if (-not (Test-Path -LiteralPath $derived)) { throw "解压后没有得到预期派生文件夹" }; Move-Item -LiteralPath $source -Destination $disabled }
   ```

   执行后按工作区规则写报告、manifest、checksum。新版 `pack_mod.py` 一次读回已核对 CRC、全部条目及源字节/总字节，直接记录该结果，不再重复读 ZIP；这些自动检查不替代报告与实机观察。

5. U2 来自 ShaderFixes 标记导出时，测试前只挪走目标 `<PS哈希>-ps.*` 文件，不动别的 hash。先建备份目录，再在同一个 PowerShell 中移动目标文件：

   ```powershell
   pwsh -NoProfile -Command { New-Item -ItemType Directory -Force -Path "<ShaderFixes备份目录>" | Out-Null; Get-ChildItem -LiteralPath "<ShaderFixes目录>" -Filter "<PS哈希>-ps.*" -File | Move-Item -Destination "<ShaderFixes备份目录>" }
   ```

   保留这些文件会让 3DMigoto 加载它们作为替换，并丢掉 RabbitFX ShaderRegex 的命令列表，透肉门控可能永远不触发。

## 期望输出

以下是输出结构示例，不是本案真实 stdout：

```text
顶层文件夹 / zip 名:（交付名）
文件（数量）个,（容量）MB;来自 overlay:覆盖（数量）、新增（数量）
写好:（zip 路径）  （容量）MB,（数量）个文件,自检通过  ← 放行行
安装:解压得到一个文件夹,放进（Mods 角色目录）;原版停用;完全重启游戏。
```

## 判定

状态描述必须对应已核实的事实：文件生成不等于静态验证通过，静态验证不等于已安装，已安装不等于游戏已重载或实机通过。按步 08 保留未完成项，不以“候选”“待 review”等称呼代替启用状态检查。

候选应放在游戏实际扫描范围之外，或经核实被加载器排除。文件放进 Mods 的可扫描路径且未被排除时，应视为可被加载；不能声称“没有装机/不会影响游戏”。启用后尚未得到用户反馈，只能报告“已启用，待实机验证”。

| 看到什么 | 结论 | 下一步 |
|---|---|---|
| overlay 覆盖/新增数符合预期，最后一行自检通过 | 默认包可交付 | 给三句安装说明，进步 11 |
| 工作区的 BASELINE、manifest、checksum、逐条读回均通过 | 工作区包可装机 | 同批启用派生版并停用原版，进步 11 |
| “overlay 里没有任何文件进包” | 相对路径放错 | 停止交付，修正 overlay 结构后重打 |
| zip 内顶层名带 `DISABLED_` | 分享命名错误 | 改 `<交付名>` 重打 |
| ShaderFixes 目标 hash 仍有 `-ps.bin/-ps.txt` | 会遮挡 ShaderRegex | 只挪目标 hash 后完全重启 |

## 失败处理

| 症状 | 原因 | 修法 |
|---|---|---|
| 同名 zip 已存在 | 默认模式保护旧文件 | 接受脚本生成的 `(2)` 名，或工作区传新的完整输出路径 |
| 解压后出现两层同名目录 | 交付目录层级又包了一次 | 以 zip 自带的单一顶层文件夹为准，重新解压到 `<角色目录>` |
| 装机命令报派生/停用目标已存在 | 当前目录状态与预期不同 | 停止，不覆盖；先按 CRC/hash 识别现役版本再定新名字 |
| 游戏里完全没触发 | ShaderFixes 标记文件仍在或没有重启 | 核对目标 hash 备份目录，再完全重启 |

## 产物

| 文件 / 变量 | 放哪 | 下一步谁用 |
|---|---|---|
| 默认 zip | 用户下载文件夹 | 用户安装、步 11 |
| 工作区 zip | `<交付目录>` | manifest、装机、步 11 |
| ShaderFixes 目标备份 | `<ShaderFixes备份目录>` | 回滚与更新后清理 |
| 安装三句话 | 交付回复 | 用户 |

## 本步红旗

| 念头 | 现实 |
|---|---|
| “直接复制 overlay 就是完整 mod” | overlay 只有差异，必须与原 mod 合包 |
| “分享包也带 `DISABLED_`” | `DISABLED_` 只属于本机停用目录 |
| “把 ShaderFixes 整目录清空最省事” | 只挪目标 hash，其他标记文件不在本案范围 |
| “装上新版后以后再停原版” | 工作区装机要求两个动作同批完成 |
