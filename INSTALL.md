# 安装与使用

这是一个 Agent Skill：给 AI 的逐步操作手册，附 Python 脚本、HLSL 模板和反编译器。只需要本目录，不需要另外安装三个效果 skill。

## 能做什么

给终末地 EFMI / 3DMigoto 角色 mod 的丝袜、薄纱做随视角变化的透肉：正对镜头透出肤色，轮廓保留袜色。可按黑丝、白丝分别调参；默认必须交付 0 只透肉 / 1 透肉加各向异性高光的切换，启动为 0。只有用户明确取消才可省略高光。

原贴图不改；光腿贴图与目标 UV 对应时优先直接用 B，UV 不对应才另烘焙 C。非单色或不确定不能降级为常数肤色。默认只做主控；当队友也要透肉，需要额外确认其像素着色器。

**先确认值不值得做：**透肉是把丝袜底下那条腿的皮肤透出来。AI 会在第一条回复的开头提示你留意两件事；它只是提示，要不要做由你决定。查法：游戏里切到不穿丝袜的档位，或在 Blender 里隐藏丝袜网格。

| 留意什么 | 不满足时的效果 |
|---|---|
| ① 丝袜原来盖住的地方，腿是否完整（有的作者会删掉被遮住的身体） | 没有东西可透，几乎没有效果 |
| ② 膝盖、脚踝这些位置和周围皮肤有没有明显的颜色差 | 整条腿一个颜色时，做出来只像丝袜变浅了，看不出透的是腿 |

袜色和肤色太接近（比如肉色丝袜）同样看不出效果，这一条不用你判断：AI 拿到文件后会实测色差，小于 30 个 sRGB 级才提醒你，没问题就不会提。AI 自己查到上面任何一条时，也只提醒一次，做不做仍由你决定。其它前提见 [步 01](references/step-01-decide.md)。

## 安装

解压 ZIP，顶层应只有一个 `efmi-sheer-skin` 文件夹。把它放到工具读取 skill 的目录：

- 支持 Agent Skills 公共目录的工具：`~/.agents/skills/efmi-sheer-skin/`。
- 只读取 Claude skills 的工具：`~/.claude/skills/efmi-sheer-skin/`。

`~` 是你的用户目录。多工具共用时，保留一份真实文件夹，其余入口指向它；不要维护两份会各自变动的副本。重新打开会话，说“给这个 mod 的黑丝做透肉”。

## 依赖与编码

1. 安装 Python 与 `numpy`、`Pillow`。在终端运行 `python -m pip install numpy pillow`，再运行 `python -c "import numpy, PIL; print('ok')"`。Pillow 负责常用 DDS 解码，解不开才用可选的 texture2ddecoder 或 texconv。
2. 本包脚本会打印中文。**每个终端会话在跑任何脚本之前先运行一次** `$env:PYTHONIOENCODING = 'utf-8'`（PowerShell）；不要等看到乱码再补。执行本说明里的命令前，切到本 skill 根目录。
3. 编译器自动选择：有 Windows SDK 的 fxc 就使用它；没有则使用系统 d3dcompiler_47.dll。不要为了本 skill 先安装一套 SDK。
4. cmd_Decompiler 及 d3dcompiler_46.dll 已随包提供。来源、版本和原始许可见 [SOURCE.md](tools/cmd_Decompiler/SOURCE.md)，许可文件保留在同一目录。
5. 游戏里需要共享 RabbitFX 和全局唯一 CrossIB 分类器。先按 [步 03](references/step-03-gate.md) 读取当前门控值并审计；确实缺分类器时才从 assets 安装一份。不要照抄案例的数值。

可运行 `python scripts/resolve_textures.py --help` 检查脚本能否启动。`regcheck.py --help` 会打印用法并返回 2，这是它现有的接口；实际寄存器检查参数见 [步 05](references/step-05-anchors.md)。

## 需要你提供什么

| 输入 | 内容 |
|---|---|
| U1 | mod 文件夹路径，包含目标 INI 的那一层 |
| U2-1 | 丝袜材质像素着色器的 hash（16 位十六进制）：游戏里开 hunting，翻到丝袜变成纯黑剪影的那个，按标记键复制。**hash 由你来给，AI 只核对，不替你猜** |
| U2-2 | 点名的文件：3DMigoto 根目录下 `ShaderCache\<你的 hash>-ps_regex.bin`，修改时间要是这一次运行的；没有时给 `ShaderFixes\<你的 hash>-ps.bin`。不要给 `-ps.txt`（汇编，用不了） |
| U2-3 | 启用目标 mod、主控穿目标丝袜、画面正常时抓的一帧转储目录，并注明状态；AI 用它核对你给的 hash、读 draw 和贴图绑定 |
| 可选图 | 黑丝、白丝、光腿的截图或贴图；没有图也能先做只读定位 |

建议的顺序：启动游戏前把 `d3dx.ini` 的 `cache_shaders` 设为 1 → 进游戏先抓帧 → 再 hunting 找 hash（这样帧里不会带着 skip）→ 退出游戏取文件。已有同版本、同状态的有效资料先复用，缺哪项才补哪项；细节见 [取证说明](references/get-shader-bin.md)。

AI 会先说明每帧用途：**穿丝袜的正常帧取丝袜 PS/绑定；真实光腿帧取缺失的皮肤贴图、身体与染色参数。** 抓前按实际配置清除 hunting 选择、关闭调试探针；不能用 skip 丝袜来代替光腿。已有完整可信肤色源不用补光腿帧，具体状态与资源要求见 [抓帧目的表及检查清单](references/get-shader-bin.md)。

交完文件后，AI 会把能从 INI 读出的内容预填，再问你第二轮问题：

1. 这个 PS 是不是只画丝袜：回答“只有丝袜”或“还有别的”就行，不用列全。它实际还画了什么，AI 会自己从帧里查。
2. 按哪个键切、几档各是什么、是否连着换其它部件、要做哪几档。
3. 只在需要时才问：丝袜那次 draw 连着吊带、蕾丝袜口这类部件时，要不要一起透（默认不透）。透肉范围默认就是丝袜本体，不用你来指。

问题没答清不正式施工。参数由脚本根据贴图给初值；不是让你先学会着色器才能使用。完整入口见 [SKILL.md](SKILL.md)。

## 做完之后你电脑上多了什么

默认多一个下载文件夹中的 mod ZIP，以及临时目录中的中间产物。原 mod 不动，不留额外报告或 `.bak`；返修读取生成 HLSL 头部的重建命令与 INI。

**工作区另有规矩时以工作区为准**：报告位置、包的位置、备份、校验和、安装和停用原版都按该工作区要求处理；AI 会在开头说明实际适用项。

首次交付需要在游戏里查看透肉、切换键以及雨雪；后续已有通过基线时按 [步 11](references/step-11-ingame.md)只重验受影响项。工作区首次要求完整四道门时照做，不把无关参数调整也机械扩成完整复测。静态检查通过不等于实机通过。

## 文件表

| 文件 | 用途 |
|---|---|
| SKILL.md | 路由、硬规矩、默认值优先级与总流程 |
| references/step-00–11-*.md | 十二个步骤，每步有输入、命令、判定和失败处理 |
| references/vision-subagent.md | 看图问句、JSON schema、工具调用与手工降级 |
| references/_step-template.md | 改说明书时使用的模板 |
| references/cases.md、lastrite-sheer-math.md | 案例与数学证据，具体数值不能当成当前固定值 |
| references/tuning.md、gating.md、get-shader-bin.md | 调参、门控原理、取文件操作 |
| references/ini-template.md、texture-binding-styles.md | INI 接线与不同资源绑定写法 |
| references/main-ps-replacement.md、variable-mapping.md、ingame-gates.md | 主 PS 替换、变量捕获与完整实机门 |
| scripts/ | mod 处理、交付检查、说明书 lint 与共用颜色解码模块 |
| tests/ | 可长期运行的合成回归，不包含作者原包 |
| assets/ | 透肉核心、高光核心和分类器安装件 |
| tools/cmd_Decompiler/ | 反编译器、依赖、来源与许可 |

维护说明书后运行 `python scripts/check_runbook.py .`；退出 0 表示结构、相对链接和命令引用检查通过，仍须人工核对内容与实机行为。

修改跨脚本公共逻辑后，从 skill 根运行一次 `python -B -m unittest discover -s tests -p 'test_*.py'`；局部修改只跑相关测试。这是合成输入验证，不等于作者原包端到端或游戏内验收。测试输出中的跳过项必须按其原因单独记录，不能计为通过。

上述 unittest 是维护 skill 脚本的开发测试，不是每次做 mod 的前置步骤。只改文字检查 lint/相关文档契约即可；局部脚本改动跑相关测试，公共逻辑改变再跑一次全套。已有基线的 mod 按 [步 08 改动表](references/step-08-static-gate.md)重验，三个 shader 工具共用临时 `--compile-cache`，不重复手工编译或重复核验同一 ZIP。

