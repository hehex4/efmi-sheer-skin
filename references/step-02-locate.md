# 步 02：定位 draw、PS 与状态分支

## 目标

核对用户给的材质 PS hash，得到每个目标状态的完整 draw 入口、资源绑定和 LOD 覆盖范围，查清这个 PS 实际画了哪些 draw，并用这些证据准备第二轮问题。

## 进入条件

- [ ] 步 00 已取得 U1 与 U2 三件（用户给的 PS hash、点名的 PS 文件、目标状态帧）；PS 文件名里的 hash 与用户给的一致。
- [ ] 步 01 已判定 B / C / A 肤色路线，并列出疑似丝袜 draw。
- [ ] 只读定位可以开始；第二轮问题未答清时仍不修改 mod、不生成替换 PS。

## 输入

| 占位符 | 是什么 | 从哪来 | 例子（2026-09 案例，勿照抄） |
|---|---|---|---|
| `<mod 文件夹>` | 含目标 ini 的 mod 根目录 | 步 00 U1 | `E:\EMFI\Mods\character\yvonne\某个 mod` |
| `<目标 ini>` | 含候选 draw 的 ini 绝对路径 | 步 01 | `E:\...\Yvonne.ini` |
| `<目标 PS hash>` | 用户给的 16 位 PS hash；AI 只核对，不自己定 | 步 00 U2-1 | `0123456789abcdef` |
| `<工作目录>` | 本案中间产物目录 | 步 00 | `C:\Temp\efmi-sheer\case` |
| `<定位 JSON>` | `resolve_textures.py` 的机器可读输出 | 本步指定 | `C:\Temp\efmi-sheer\case\bindings.json` |
| `<底子 HLSL>` | U2 已经是 `_replace.txt`，或 bin 已反编译出的 HLSL | 步 00 / 04 | `C:\Temp\efmi-sheer\case\source.hlsl` |
| `<片标签>` | 状态与切片的唯一标签 | 步 01 | `白丝_状态1_片A` |
| `<资源前缀>` | Index / Position / Texcoord 的共同前缀，或 `ib=...,pos=...,uv=...` | 目标 ini | `BodyStocking` |
| `<draw 参数>` | `数量,起点,基顶点` | 目标 ini 的 draw 行 | `12345,0,0` |
| `<当前 diffuse>` | 该状态下实际绑定的漫反射 | resolve 输出 | `Textures\Diffuse_Stocking.dds` |
| `<LOD0 转储>` | 主控帧目录或它的 `log.txt` | 步 00 U2-3，必须项 | `E:\EMFI\FrameAnalysis\... [mod]` |
| `<LOD1 转储>` | 队友帧目录或它的 `log.txt` | 只有用户要求队友透肉时提供 | `E:\EMFI\FrameAnalysis\... [mod]` |
| `<ini 段名子串>` | 目标 TextureOverride / CommandList 的唯一名称片段 | resolve 输出 | `Stocking` |
| `<IB hash>` | 目标 TextureOverride 的 8 位 hash | 目标 ini | `89abcdef` |
| `<材质 VS hash>` | 材质 pass 的 VS hash | 帧转储输出 | `fedcba9876543210` |
| `<3DMigoto 根>` | 含 `Mods`、`d3dx.ini` 的根目录 | 从 U1 向上推出；推出失败时问用户 | `E:\EMFI` |

## 操作

1. 从 ini 展开状态分支、别名链、嵌套 CommandList 和 draw 前的贴图绑定，并保存 JSON：

   ```powershell
   python scripts/resolve_textures.py "<mod 文件夹>" --all --verbose --json "<定位 JSON>"
   ```

   对每条候选记录以下字段：原 ini 与行号、段名、draw 操作和完整参数、IB hash、到达条件、默认状态、每个贴图槽、资源名、最终文件路径、外部命令表。
2. 已有 HLSL 时，从着色器侧反查采样槽与漫反射染色行：

   ```powershell
   python scripts/resolve_textures.py "<mod 文件夹>" --all --ps-hlsl "<底子 HLSL>"
   ```

   输出带 `GetDimensions` 的高槽说明 RabbitFX 桥接存在。脚本把“采样结果随后被 `cb6[6]` 相乘”当作 2026-09 的漫反射启发式；找到时只记为候选。找不到时先在步 05 从 diffuse 采样向后追踪当前版本的染色常量，不能直接把 U2 判成非材质 PS。
3. 给每个状态分支下的每个丝袜切片各跑一组 `--piece`；一条命令可以重复追加多组 `--piece`，下面展示单片完整形式：

   ```powershell
   python scripts/stocking_preview.py --ini "<目标 ini>" --out-dir "<工作目录>" --piece "<片标签>" "<资源前缀>" "<draw 参数>" "<当前 diffuse>"
   ```

   状态分支不能因共用同一 diffuse 而合并：黑丝 / 白丝可能是同一图上的不同 UV 岛与不同 draw。
4. 用帧转储按段名核对 draw、命令与槽位：

   ```powershell
   python scripts/find_draw_shaders.py "<LOD0 转储>" --section "<ini 段名子串>" --cmds --slots --root "<3DMigoto 根>"
   ```

5. 段名不唯一或跨 IB 时，改用 IB hash 查找：

   ```powershell
   python scripts/find_draw_shaders.py "<LOD0 转储>" --ib "<IB hash>" --cmds --slots --root "<3DMigoto 根>"
   ```

   输出中 draw 行末尾 `← 段名 [hash]` 是这次 draw 实际挂载的 TextureOverride。跨 IB 部件必须按这个箭头归属，不能按资源文件名或角色部件名归属。
6. 从同一 draw 的多次绘制中找材质 pass：看 `--cmds` 展开的条件，材质 VS 门控为 true 的那次，记录它的 VS / PS。阴影、prepass、描边会有相同 draw 参数，但 VS / PS 不同。这次材质 pass 的 PS 必须等于用户给的 `<目标 PS hash>`；不相等就停下，把两个值告诉用户，请他回 hunting 确认，不自己换成帧里那个。

   再查这个 PS 在这一帧里实际画了哪些 draw，这是“这个 PS 是不是只画丝袜”的证据：

   ```powershell
   python scripts/find_draw_shaders.py "<LOD0 转储>" --ps "<目标 PS hash>" --cmds --root "<3DMigoto 根>"
   ```

   清单里出现目标丝袜以外的 draw，就是这个 PS 还画着别的部件；替换只接在目标丝袜的 draw 入口上，其它 draw 保持原样。用户对 Q1 的回答只当“是 / 否”信号，他列出的部位一律视为不完整，实际范围以这份清单为准。
7. 用户明确要求队友也透肉时，把 LOD0 / LOD1 一起核对并限定材质 VS：

   ```powershell
   python scripts/find_draw_shaders.py "<LOD0 转储>" "<LOD1 转储>" --section "<ini 段名子串>" --vs "<材质 VS hash>" --cmds --root "<3DMigoto 根>"
   ```

   汇总必须显示目标 LOD0 / LOD1 都只落到 U2 的 `<目标 PS hash>`。若出现多个 PS，LOD1 需要自己的 U2′ / U3，不能套用 LOD0 底子。
8. 把读到的状态变量、`key =`、默认值、每个值对应的 draw / diffuse、丝袜片清单写进 Q2 的预填。透肉范围默认丝袜本体，由 AI 自己定；只有步 01 或本步的证据显示同一次 draw 里连着丝袜本体以外的部件时，才准备 Q3 并填上部件名。Q1 是用户的 hunting 观察，只当“是 / 否”信号。
9. ⏸ 在这里发送步 00 的第二轮问题：Q1、Q2 必问，范围用一句话告知，Q3 触发了才问；一条回复发完。问题全部答清才进步 04（Q3 没触发视为已答）；等待期间可以并行完成步 03 的两条只读门控审计。

## 期望输出

本轮没有执行 Yvonne 夹具。下面是脚本源码中的固定标签拼成的输出结构示例，不是真实执行结果：

```text
RabbitFX 槽位映射 {...}  ← {来源}
[Constants] 默认值({数量} 个):...
====================================================================================================
draw  {ini}:{line}  [{section}]  drawindexed = {args}
      到达条件:{conditions}
      t...     Diffuse ... {resource} {file}
      ▶ 漫反射 默认状态下 = {resource};其它状态 ... 种(见上) ← 状态与贴图判据
```

帧转储工具的输出结构示例：

```text
== {dump}  (analyse_options: ..., ... 次游戏 draw, ... 次 mod draw, ini 根 ...)
... VS={vs-hash} PS={ps-hash} ... ← {TextureOverride} [{ib-hash}] ← 实际挂载点
        [{section}] {executed-command}
== 命中的 draw 共用 {count} 种 VS/PS 组合 ← LOD 结论
```

## 判定

| 看到什么 | 结论 | 下一步 |
|---|---|---|
| 输出明确列出状态条件、默认状态、draw 与漫反射 | ini 侧定位完整 | 继续逐片预览并预填 Q2 |
| `draw 前没有任何贴图赋值` | 贴图来自外部命令表或游戏原槽 | 展开输出的“外部”项；仍无证据时停下索取对应 ini / 根目录 |
| `没有匹配的 draw` | 筛选值错误或入口未展开 | 去掉 `--section` / `--ib`，保留 `--all` 重跑 |
| 帧中没有 TextureOverride 触发 | mod 未启用、原版帧，或日志缺 deferred context | 停下请用户重新提供装机帧；说明 `analyse_options` 必须含 `deferred_ctx_immediate` |
| LOD0 与 LOD1 的材质 pass 共用一个 PS | 同一 U2 可覆盖两种 LOD | 只有用户已明确要求队友透肉时才把 LOD1 纳入 |
| LOD1 绑定另一个 PS | 不能复用 LOD0 底子 | 回步 00 索取 U2′ / U3 |
| 材质 pass 的 PS 等于用户给的 hash | hash 核对通过 | 继续 |
| 材质 pass 的 PS 不等于用户给的 hash | 两者有一个不对 | 整条回复只发 SKILL.md 的【hash 对不上】并附两个值；不说哪个正确，不提议改用帧里那个，不自己换 |
| 用户答 Q1“还有别的”，并列了几样 | 清单视为不完整 | 不追问；以 `--ps` 清单为准确认实际范围 |
| 用户答 Q1“只有丝袜”，`--ps` 清单里还有别的 draw | 以帧为准 | 把查到的 draw 告诉用户；替换只接目标丝袜的 draw 入口 |
| 第二轮问题全部答清，Q3 没触发视为已答 | 范围与状态门通过 | 步 03 审计已完成时进步 04；否则先完成步 03 |
| 任一问题仍不明确 | 替换边界未锁定 | 停下，只重问对应的原问题 |

## 失败处理

| 症状 | 原因 | 修法 |
|---|---|---|
| 资源值有多层 `ref`，最终文件为空 | 跨 namespace 外部命令未被当前 mod 展开 | 提供 `<3DMigoto 根>`，读取共享 RabbitFX / EFMIv1 的实际定义后重跑 |
| 同一 draw 打印多个 diffuse 候选 | 状态条件含运行时变量 | 用 `[Constants]` 默认值与用户 Q2 回答逐分支标注，禁止选第一张文件 |
| PS hash 与 U2 文件名不一致 | U2 选错 pass，或转储不属于当前版本 | 回步 00 重新取本次材质 PS |
| 着色器侧提示“没找到 cb6[6]” | 2026-09 启发式未命中，cb 布局可能已变 | 继续步 05，从当前 diffuse 采样追到现场染色常量；找到非材质证据后才回步 00 |
| 只看部件自己的 IB 找不到跨 IB draw | draw 挂在另一个 TextureOverride | 以输出箭头所指段为入口，记录真实 IB 与来源 CommandList |
| LOD1 没有命中 | 队友帧没拍到目标，或队友走不同入口 | 请用户在队友可见状态重拍；不把“无命中”写成“与 LOD0 相同” |

## 产物

| 文件 / 变量 | 放哪 | 下一步谁用 |
|---|---|---|
| `<定位 JSON>` | `<工作目录>` | 后续复核绑定与状态 |
| 状态 → draw → diffuse → 条件映射 | 当前会话中的只读结论 | Q2、Q3 与步 07 / 09 |
| 每片 UV 拼板与建议框 | `<工作目录>` | 步 01、06 |
| 主控材质 VS / PS 组合 | 当前会话中的证据 | 步 03、09 |
| LOD1 是否共用 PS | 当前会话中的证据 | 是否需要 U2′ / U3 |
| 第二轮问题的用户答复与 `--ps` draw 清单 | 当前会话中的已确认输入与证据 | 步 04 起的正式施工 |

## 本步红旗

| 念头 | 现实 |
|---|---|
| “用户说还有上衣和手套，那这个 PS 就画了这三样” | 用户一次说不全；用 `--ps` 清单自己查 |
| “帧里的 PS 和用户给的不一样，用帧里的更准，问一句‘我用这个行吗’就好” | 这是替用户预判。只发【hash 对不上】，让他回 hunting 确认；可能是他翻错了，也可能帧不是这个状态 |
| “draw 参数一样就是同一个 pass” | 材质、描边、阴影和 prepass 会重用同一 draw 参数 |
| “部件叫 C4，所以入口一定在 C4” | CrossIB 可以从别的 TextureOverride 的列表发出这片 draw |
| “默认状态看见一张贴图，其他档可以忽略” | 只改一个分支会让切换后的丝袜失效或套错颜色 |
| “没有 LOD1 转储就先假定相同” | 默认成品只接 LOD0；要接 LOD1 必须有 hunting 或转储证据 |
