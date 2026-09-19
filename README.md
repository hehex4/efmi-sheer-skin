# efmi-sheer-skin

给《明日方舟:终末地》EFMI / 3DMigoto 角色 mod 的丝袜、薄纱做**着色器透肉**的 Agent Skill:正对镜头透出肤色,轮廓保留袜色,随视角连续变化;原贴图不改,可一键撤销。

An Agent Skill (for Claude Code, Codex and other tools that read `SKILL.md`) that makes stockings / sheer cloth on Arknights: Endfield (EFMI / 3DMigoto) character mods show the skin underneath through a view-dependent pixel shader. Documentation is in Chinese.

## 这是什么

Agent Skill = 给 AI 编程助手看的逐步操作手册,外加它要用到的 Python 脚本、HLSL 模板和反编译器。你不需要自己读懂着色器:装好之后对 AI 说一句「给这个 mod 的黑丝做透肉」,它会按手册一步步取证、生成着色器、接线、检查并打包。

- 入口:[SKILL.md](SKILL.md)(路由、硬规矩、总流程)
- 安装、依赖、需要你提供什么:[INSTALL.md](INSTALL.md)
- 十二个步骤:`references/step-00` … `step-11`

## 先确认能不能做

透肉透出来的是丝袜底下的腿。**丝袜底下没有腿的模型和皮肤的 mod(作者删掉了被丝袜遮住的身体,或腿上没有皮肤材质),这个 skill 做不出能看见的效果,调参数也救不回来。** 查法:游戏里切到不穿丝袜的档位,或在 Blender 里隐藏丝袜网格,看丝袜原来盖住的地方腿是否完整、有皮肤。AI 也会在第一条回复的开头先问这件事,确认没有腿就直接告诉你做不了,不会让你白抓帧。肉色丝袜(袜色和肤色太接近)同样看不出效果。

## 安装

**下载 zip(推荐):**到 [Releases](https://github.com/hehex4/efmi-sheer-skin/releases/latest) 下载最新的 `efmi-sheer-skin_<日期>.zip`,解压后顶层只有一个 `efmi-sheer-skin` 文件夹,把它放到工具读取 skill 的目录:

- 只读取 Claude skills 的工具:`~/.claude/skills/efmi-sheer-skin/`
- 支持 Agent Skills 公共目录的工具:`~/.agents/skills/efmi-sheer-skin/`

**或者用 git:**仓库根目录就是 skill 目录,直接克隆过去(文件夹名必须是 `efmi-sheer-skin`):

```bash
git clone https://github.com/hehex4/efmi-sheer-skin.git ~/.claude/skills/efmi-sheer-skin
```

之后的依赖安装(Python + numpy + Pillow)和编码设置见 [INSTALL.md](INSTALL.md)。

运行环境:Windows;游戏侧需要共享 RabbitFX 和全局唯一的 CrossIB 分类器(步 03 会先审计,缺了才装)。

## 注意

- 文档里出现的 hash、槽位、门控值、寄存器编号都是 **2026-09 的案例值,不能照抄**;游戏或 RabbitFX 更新后要按步 03 现场重读。
- 非官方项目,与游戏的开发、发行方无关。mod 只改你自己电脑上的渲染,使用风险自负。
- 仓库不含任何游戏文件,也不含任何 mod 作者的原包;`tests/` 只用合成输入。

## 第三方组件

下列文件**不是**本仓库作者写的,**不受**本仓库 LICENSE 约束,各按其原有条款:

| 文件 | 作者 / 来源 | 说明 |
|---|---|---|
| `tools/cmd_Decompiler/cmd_Decompiler.exe` | [bo3b/3Dmigoto](https://github.com/bo3b/3Dmigoto) 1.3.16 官方 release | MIT;上游的 `COPYING.txt`、`LICENSE.MIT.txt`、`LICENSE.GPL.txt` 原样放在同目录,来源与哈希见 [SOURCE.md](tools/cmd_Decompiler/SOURCE.md) |
| `tools/cmd_Decompiler/d3dcompiler_46.dll` | Microsoft | D3D 编译器可再发行运行库,3Dmigoto 官方包随带;按微软的条款 |
| `assets/CrossIBClassifier.ini` | Velo(namespace `VeloCrossIB_…`) | CrossIB 分类器的原样快照,未做任何改动,权利归原作者;仅在你的游戏里确实没有分类器时才安装。作者发布新版时一律以作者的版本为准。原作者如不希望在此随附,请提 issue,我会移除 |

透肉的覆盖率曲线参照了游戏原版「白纱」材质的表现,`assets/sheer_core.hlsl` 是自写实现。

## 许可

自写部分(`SKILL.md`、`INSTALL.md`、`references/`、`scripts/`、`tests/`、`assets/*.hlsl`)按 [MIT](LICENSE) 许可。第三方组件见上表。

## 反馈

欢迎提 issue。本仓库是作者本机 skill 源目录的单向镜像,PR 的改动会先并回源目录再同步过来,所以合并记录可能不是原始 PR 提交。
