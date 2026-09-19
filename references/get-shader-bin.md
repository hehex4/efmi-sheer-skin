# U2 怎么拿：抓帧与同次 ShaderCache 优先

[步 00](step-00-intake.md)索取 PS 时优先要“目标状态帧转储＋同次运行的 ShaderCache”。**新取证直接从下文方法 C 开始**，不要求先做方法 A。方法 C 放在最前；A/B 名称仅兼容旧引用，不代表执行顺序。

帧目录可能只有 PS hash 或汇编，也可能有字节码，取决于配置；不能把“抓帧完成”等同于“已取得可修改的 PS”。先核验帧内文件是否为本次 draw 对应、RabbitFX 改写后的正确字节码；满足就直接复用，否则从同次 ShaderCache 取 `<hash>-ps_regex.bin`。不要求用户事先知道 hash，AI 从帧定位。

已有同版本、同状态有效资料优先复用，不强制重抓。方法 B 用于补齐缓存，方法 A 是无法抓帧或取证仍缺 PS 时的备用。默认只做主控；用户要队友才补对应帧并验证其 PS，不能默认共用。

## 方法 C：目标状态抓帧＋同次 ShaderCache（首选入口）

同一趟准备两类资料：帧转储用于定位 draw/PS、资源绑定及已转储的 cb；同次 ShaderCache 提供修改底子。二者不保证位于同一个文件夹。帧转储不能凭空还原没有绘制的身体源或未转储的常量。

### 先说明为什么抓、抓什么

AI 先读已有 mod/贴图/证据，按缺项列出本次需要的帧；每一帧都向用户说明目的、状态和需要保留的资源。已有同版本有效资料复用，不把下表当作每个案例必须全抓的清单。

| 取证目的 | 应抓的状态 | 需要的资料 |
|---|---|---|
| 定位丝袜材质 PS，确认目标 draw 与资源绑定 | 主控穿目标丝袜，正常绘制 | 帧 log＋同次 ShaderCache；帧内正确字节码可替代对应缓存。还需读材质参数时保留 cb |
| 从运行时取得裸腿肤色、身体资源及染色参数 | 同角色真实光腿状态，身体正常绘制；已有完整可信源时不补抓 | 光腿帧 log、实际 diffuse（dump_tex）、常量（dump_cb）；需建立/烘焙 UV 映射时还保留身体 vb/ib（dump_vb/dump_ib） |
| 核对另一丝袜状态的不同 PS/绑定/染色 | 对应黑丝/白丝等状态，注明切换变量和值 | 对应帧 log、相关 PS；需要读取的贴图/cb/网格一并保留。共享且已核验的状态不重复抓 |
| 核对队友 LOD | 用户明确要求时，目标角色作为队友正常显示 | 队友帧 log、对应 PS 与缺失资源，和主控分别记录 |

丝袜帧用于认丝袜，光腿帧用于认皮肤；光腿 PS 不能直接当成丝袜替换底子。若同一帧已实际绘制了可核验的完整身体源，可以复用，无须机械补光腿帧。只提供光腿帧而缺丝袜绑定时，仍需目标丝袜证据。

**不能用 skip 丝袜 PS/IB 制造光腿状态。** skip 只是跳过绘制，不保证下面有身体或正确光腿材质。mod 没有光腿状态时先核对包内或用户提供的真实身体源；没有就明确缺什么，不让用户反复抓无法产生源数据的帧。肤色取自实际 diffuse 与染色链，不从含光照/后期的游戏截图吸色。

**AI 先准备**(改 `<3DMigoto 根>\d3dx.ini` 前先备份,并告诉用户改了哪几行):

1. `cache_shaders = 1`(出厂 0);
2. `hunting` 不为 0；`analyse_options` 保留 `deferred_ctx_immediate`。先读 mod，预计需确认身体染色时同趟包含 `dump_cb`；需从帧提取身体几何/贴图时保留对应 buffers/textures。工作区已有全量配置不缩减，一帧可能几个 GB；只保留 log 无法补回被丢弃的资源。
3. 查出实际抓帧键(`analyse_frame`)与清除 hunting 选择键(`done_hunting`)告诉用户，不照抄别人的按键。若已知目标 hash 在 ShaderFixes 有残留，先说明原因并经用户同意移到备份目录；hash 未知时不全目录清理，定位后只处理相关文件(见方法 A 的 ⚠)。启用 hunting 功能不等于让目标保持 skip；无需为了抓帧先逐个寻找 PS。

**用户**:

4. 开游戏，启用目标 mod，切到上表指定状态；先完成下面检查，再按一次实际抓帧键（游戏会卡几秒）：
   - [ ] 用实际 `done_hunting` 清除 PS/VS/IB/VB 等 hunting 选择，恢复正常绘制；目标没有因 skip 消失、纯黑或被 pink/original 标记改变。恢复后等待画面稳定再抓。
   - [ ] 关闭本次人为开启的纯绿检查、范围探针和临时诊断替换，保留要研究的原 mod 正常效果。不要删除作者正常接线所需的 `handling = skip`；这里清除的是 hunting/诊断状态。
   - [ ] 主控/队友身份符合本帧目的，镜头能看到目标腿部或身体源，未被菜单或近景物体挡住。光腿帧确实显示正常皮肤，不是跳过丝袜后留下的空洞。
   - [ ] 记录帧目录与状态的对应关系，例如“主控黑丝/取目标PS”和“主控光腿/取身体源”，连同相关切换变量和值交给 AI。
5. 只有上表列出的缺项才补对应帧；每次切状态后重复抓前检查。让状态出现在画面里可能生成缓存，但不等于已经保存该状态的帧日志。
6. **完全退出游戏**,告诉 AI。

**AI 收尾**:

7. 提供 `FrameAnalysis-日期-时间` 与同次 ShaderCache 的目录路径；工作区要求归档时按其脚本立即归档，尚需 buffers/textures 时保留全量。AI 用 `scripts/find_draw_shaders.py` 查出材质 PS 的 hash：

```
python scripts/find_draw_shaders.py "<主控那帧>" --section "<ini 段名子串>" --cmds --slots --root "<3DMigoto 根>"
python scripts/find_draw_shaders.py "<主控那帧>" --ib "<TextureOverride 的 hash>" --root "<3DMigoto 根>"
```

按现场分类器和门控认材质 pass；`vs == 202` 只是旧案例，不照抄。用户要求队友时再把队友帧加入命令，按步 02 的材质 VS 限定比较；不能用阴影/prepass 的共同 PS 代替材质 PS。

8. 先核验帧内 PS；已是正确的补丁后字节码就复制复用。不足时在同次 `<ShaderCache>` 找 `<材质 PS hash>-ps_regex.bin`，核对本次生成时间及补丁状态后复制。缺缓存不能直接断言该 PS 没被改写：先查是否启用缓存、实际执行该 PS、存在 ShaderFixes 覆盖；只补缺项。仍缺底子才使用方法 A 的 bin/HLSL，按步 00 判定文件类型。
9. 本次临时改动按备份和工作区约定还原，不把用户原有全量配置改成默认配置。保留本次需要的帧资源和 PS 副本。

### 收到帧后的判定

| 发现 | 处理 |
|---|---|
| 目标被 hunting skip 或调试探针改变 | 不把该帧当正常外观/材质执行证据；已核验的 PS 文件可保留复用，恢复正常绘制后只补受影响的帧 |
| 所谓光腿帧只有空洞、仍穿丝袜或没有目标身体 draw | 不从袜色/背景猜肤色；切真实光腿状态，或补可核验的身体源 |
| 有 log，但缺所需 cb/贴图/vb/ib | 先查 mod 文件是否已足够；不足时说明具体缺项，调整转储选项后只补对应状态 |
| 身体与丝袜源均已定位，贴图/常量/映射所需数据齐全 | 继续步 02/05/06，不再要求重复抓帧；需提取的资源未保存前不能把帧瘦身到只剩 log |

### 读某次 draw 的 cb 常量(例如确认染色 `cb6[6]`)

角色的常量是**一整块共享缓冲、按偏移分给各次 draw**(log 里各 cb 槽的 hash 相同),直接看 dump 出来的 `.buf` 是整块、读不准。
按 log 里那个 cb 槽那一行的 `first_constant` / `num_constants` 截:偏移 = `first_constant × 16` 字节,长度 = `num_constants × 16` 字节,
每 16 字节 = 一个 `cbN[i]`(4 个 float)。方法来源:踩蘑菇社区《关于如何确定和修改材质中的常量参数》(caimogu.cc/post/2364332)。

## 方法 A：hunting 标记导出（备用）

前提(`<3DMigoto 根>\d3dx.ini`):`hunting` 不为 0;`marking_mode = skip`;要从 ShaderFixes 拿文件时,`marking_actions` 里要带 `regex`。
按键看 `d3dx.ini` 里 `toggle_hunting`、`previous_pixelshader`、`next_pixelshader`、`mark_pixelshader` 那几行。

1. 游戏里**操作这个角色**(做 U3 时:操作别的角色,让它当队友出现在画面里),穿着丝袜,镜头对着丝袜。
2. 用上一个 / 下一个像素着色器键翻,直到丝袜变成**没有任何明暗的纯黑剪影**,别的部位照常:
   - 这是「上色那一步」被跳过的样子 —— 形状还在,因为别的 pass(深度等)照常画它;
   - 翻 IB 时 skip 是整片消失,那是模型的编号,不是着色器。
3. 确认没选错:
   - 切成**白丝** —— 白丝也变纯黑就对了(黑丝本来就黑,纯黑不好认),也顺带证明黑白丝用同一个着色器;
   - 往旁边翻一个,丝袜恢复;翻回来又变黑。
4. 按标记键:hash 复制到剪贴板;`marking_actions` 带 `regex` 时,同时往 `ShaderFixes` 导出 `<hash>-ps.bin`(改写后的字节码)
   和 `<hash>-ps.txt`(汇编,文件头写着套用了哪些 `[ShaderRegex…]`)。2026-09 实测 `marking_actions = clipboard hlsl asm regex`
   一按标记,这两个文件同时出现;bin 反汇编和 txt 的指令条数一致。
5. 交给 AI 的:`ShaderFixes\<hash>-ps.bin`,或者方法 B 的 `<hash>-ps_regex.bin`。
   ⚠ **别交同时导出的 `<hash>-ps.txt`** —— 那是汇编,当不了底子(注入在 HLSL 上做)。
   **被 ShaderRegex 改写过的 PS,标记时只出这个汇编、不出 HLSL**(补丁打在汇编层,3DMigoto 就是这么做的),
   所以只拿到 `-ps.txt` 时别反复按标记键,改走方法 B 取 `-ps_regex.bin`。

⚠ **标记导出的文件不能留在 ShaderFixes**:之后每次启动,3DMigoto 都会把 `<hash>-ps.bin` / `-ps.txt` 当成这个着色器的替换版加载。
3DMigoto 出厂 `d3dx.ini` 对 `regex` 这个动作的说明就写着会丢掉 ShaderRegex 附带的命令列表;门控要的 `ps == 1718.1` 多半也跟着没了
⇒ 透肉永远不触发。这个 hash 在 ShaderCache 里也不会再生成 `_regex` bin。AI 复制一份后,实机测试前征得用户同意挪到备份目录(不删);游戏或 RabbitFX 更新后这份就失效了,到时删掉。

## 方法 B:ShaderCache

1. `d3dx.ini` 里 `cache_shaders = 1`(出厂 0),**游戏启动前**改好;EFMI 包 / 启动器更新会把 `d3dx.ini` 洗回出厂。
2. 开游戏,让穿着丝袜的角色出现在画面里(着色器第一次被创建时才写缓存)。
3. 退出游戏,取 `<ShaderCache>\<hash>-ps_regex.bin`,**修改时间必须是这次**(旧的 = 冻结了旧着色器)。
4. hash 用方法 A 找,或者用方法 C 的帧转储查。ShaderFixes 里还留着这个 hash 的标记导出文件时,这里不会生成(见上面 ⚠)。
5. 拿完把 `cache_shaders` 改回 0(调参期开着缓存,可能读到过期的着色器)。

`<hash>-ps_regex.bin` 只有「`cache_shaders = 1` + 这次运行真用到了这个 PS + 它被 ShaderRegex 改写过」三条同时成立才会生成。
标记键出厂只复制 hash(`marking_actions = clipboard`);导出 HLSL 时,被改写过的 PS 也只出汇编、不出 HLSL。

