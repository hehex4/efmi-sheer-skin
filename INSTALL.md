# 安装与使用

这是一个 Agent Skill：给 AI 的逐步操作手册，附 Python 脚本、HLSL 模板和反编译器。只需要本目录，不需要另外安装三个效果 skill。

## 能做什么

给终末地 EFMI / 3DMigoto 角色 mod 的丝袜、薄纱做随视角变化的透肉：正对镜头透出肤色，轮廓保留袜色。可按黑丝、白丝分别调参；默认必须交付 0 只透肉 / 1 透肉加各向异性高光的切换，启动为 0。只有用户明确取消才可省略高光。

原贴图不改；光腿贴图与目标 UV 对应时优先直接用 B，UV 不对应才另烘焙 C。非单色或不确定不能降级为常数肤色。默认只做主控；当队友也要透肉，需要额外确认其像素着色器。

**先确认能不能做：**透肉透出来的是丝袜底下的腿。丝袜底下没有腿的模型和皮肤（作者删掉了被丝袜遮住的身体，或腿上没有皮肤材质）的 mod，本 skill 做不出能看见的效果，调参数也救不回来。AI 会在第一条回复的开头先问这件事；确认没有腿就直接告诉你做不了，不让你白抓帧。查法：游戏里切到不穿丝袜的档位，或在 Blender 里隐藏丝袜网格，看丝袜原来盖住的地方腿是否完整、有皮肤。

袜色和肤色太接近（肉色丝袜）同样看不出效果，其它前提见 [步 01](references/step-01-decide.md)。

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
| 首选取证资料 | 启用目标 mod、主控穿目标丝袜的帧转储＋同次运行的 ShaderCache 目录路径，并注明状态；AI 从帧定位 PS |
| U2 | 从上述资料取得的丝袜材质 PS，优先补丁后 bin；帧内已有正确字节码或已有有效 PS 时直接复用 |
| 可选图 | 黑丝、白丝、光腿的截图或贴图；没有图也能先做只读定位 |

索取 PS 时优先同一趟取得帧转储和 ShaderCache，不要求先手动 hunting 找 PS。帧目录不保证包含可修改的 PS，可能只有 hash 或汇编；AI 会核验并从当次缓存补齐。已有同版本、同状态的有效资料先复用，缺哪项才补哪项；暂时无法抓帧或仍缺 PS 时，按 [取证说明](references/get-shader-bin.md) 使用备用方法。

AI 会先说明每帧用途：**穿丝袜的正常帧取丝袜 PS/绑定；真实光腿帧取缺失的皮肤贴图、身体与染色参数。** 抓前按实际配置清除 hunting 选择、关闭调试探针；不能用 skip 丝袜来代替光腿。已有完整可信肤色源不用补光腿帧，具体状态与资源要求见 [抓帧目的表及检查清单](references/get-shader-bin.md)。

交完文件后，AI 会把能从 INI 读出的内容预填，集中问你三件事：

1. 这个 PS 是否只画丝袜；skip 它时还有哪些部件变黑。
2. 按哪个键切、几档各是什么、是否连着换其它部件、要做哪几档。
3. 选中档位里哪些部位要透，吊带、蕾丝及同 PS 的其它部件是否排除。

三问没答清不正式施工。参数由脚本根据贴图给初值；不是让你先学会着色器才能使用。完整入口见 [SKILL.md](SKILL.md)。

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

