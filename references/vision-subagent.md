# 视觉判定协议

这份协议让主模型、视觉子代理和用户手工判断使用同一问句、同一 JSON。看图只确认脚本数字无法裁决的视觉事实，不替代脚本的数值门。

## 五条原则

1. **先文字后图。** 每个看图点对应的脚本先打印数字结论，主模型先按步骤文件的判定表走。只在三种情况看图：脚本打印“判不了 / 混合”；用户主动给了截图；步骤明确写“必看”。
2. **主模型能看图就自己看。** 打开原图，使用该 VP 的原问句，并只产出对应 schema 的 JSON。
3. **主模型不能看图就派视觉子代理。** 输入只包含：图的绝对路径、该 VP 的问句原文、答案 schema。子代理只回 JSON；主模型只消费 schema 中的字段。
4. **无效答案只重问一次。** 字段缺失、类型错误、枚举值越界或不是合法 JSON，都把同一问句和 schema 原样重发一次。第二次仍失败就按“看不清”走保守分支，把原问句交给用户手工填写。
5. **工具没有子代理能力就直接请用户填 JSON。** 不把自然语言印象冒充结构化结论，也不因缺图跳过步骤明确标成必看的 VP。

## 通用调用包

调用任何工具前，先从下表取出一行，组成这段完整输入：

```text
图的绝对路径：（绝对路径）
只回答合法 JSON，不要 Markdown，不要解释，不要添加 schema 外字段。
答案 schema：（该 VP 的 schema）
问题：（该 VP 的问句原文）
```

收到结果后按顺序检查：能否解析为单个 JSON object；必需字段是否齐全；bool/number/string/array 类型是否正确；枚举值是否只来自 schema；数值是否在范围内。通过后才查“用法”列。

## Claude Code 示例

`model` 只在主模型本身不能看图且你已确认某个可看图模型时填写；主模型能看图时省略该参数。

下面是工具调用参数示意，不是在终端执行的 Python 程序。

```text
Agent(
  subagent_type="general-purpose",
  model="vision-model-name",
  run_in_background=false,
  prompt="""用 Read 工具打开这张图：（图的绝对路径）
只回答下面的 JSON，不要任何解释：
（该看图点的 schema）
问题：（该看图点的问句原文）"""
)
```

## Codex 示例

通用做法是用当前可用的视觉模型；继承默认模型时省略 `model` 与 `reasoning_effort`。下面只是当前 GPT-5.6 Luna low 验收调用示例，不是通用模型规则。显式指定 Luna low 时必须用 `fork_turns: "none"`，再把完整视觉上下文放进 `message`：

```javascript
collaboration.spawn_agent({
  task_name: "vision_check",
  fork_turns: "none",
  model: "gpt-5.6-luna",
  reasoning_effort: "low",
  message: `用图像查看工具打开：（图的绝对路径）
只回答合法 JSON，不要 Markdown，不要解释，不要添加 schema 外字段。
答案 schema：（该看图点的 schema）
问题：（该看图点的问句原文）`
})
```

子代理返回后由主模型做 JSON 校验和步骤判定；子代理不修改文件、不运行 mod、不延伸诊断。

## 无子代理时

把“图的绝对路径 + 问句原文 + schema”原样发给用户，请用户只填 JSON。用户无法访问该路径时，把已经显示在当前会话中的同一张图连同问句一起给用户；路径无法访问且图也未显示，就把该 VP 记为“缺图”，执行步骤文件的保守分支。

## 看图点清单

| 编号 | 图 | 问句 | schema | 用法 |
|---|---|---|---|---|
| VP1 | `stocking_preview.py` 出的 `stocking_sheet.png` / `<标签>_island.png` | 这张图是一次 draw 的三角形按它自己的 UV 光栅化出来的。回答：岛大约覆盖整张图百分之几；岛内主色是袜子花纹还是皮肤色；从上到下颜色是否明显分成不同部件 | `{"coverage_pct": 0-100, "dominant": "fabric"\|"skin"\|"mixed", "multi_part": true\|false, "notes": ""}` | `coverage_pct<40 && dominant=="fabric" && !multi_part` → 独立网格；`coverage_pct>=60 \|\| multi_part` → 整个身体；其余 → 问用户 |
| VP2 | `bake_skin_to_stocking_uv.py --preview` 出的 PNG | 暗处 = UV 岛外。岛内有没有纯黑 / 纯白的洞；颜色是不是均匀肤色（允许明暗渐变）；有没有彩色噪点 | `{"holes": bool, "skin_like": bool, "noise": bool, "notes": ""}` | 三项分别对应：身体 draw 漏了切片 / 身体贴图选错 / K 太小；任一为坏 → 回步 06 失败处理表 |
| VP3 | `dds_view.py` 拼板（用户给的黑丝 / 白丝 / 光腿图） | 拼板每格标签下的图分别是黑丝、白丝、光腿还是其它 | `{"tiles": [{"label": "", "kind": "black"\|"white"\|"bare"\|"other"}]}` | 与步 02 按 ini 判出的状态对表；不一致以用户图为准并重跑步 02 |
| VP4 | `diff_texture_variants.py` 出的范围图 | 效果框内是否只含用户选定袜区；框外其它部件的差异分别属于什么 | `{"box_only_selected_region": bool, "outside_parts": [str], "uncertain": bool}` | 框内范围正确且无不确定项 → 保留 B；框外其它部件变化只记录归属，不能因此拒绝 B。框内混入排除部件才收窄 `--box` |
| VP5a | 用户实机截图（检查开关 = 1） | 丝袜是否整块纯绿；其它部位是否正常 | `{"stockings_green": bool, "others_normal": bool}` | 绿 = 替换挂对；不绿 → 步 03 门控 / ShaderFixes 陷阱；其它部位也绿 → 丝袜画在身体贴图上（正常）或范围错（看 VP1） |
| VP5b | 用户实机截图（正式档） | 正对镜头处是否透出肤色；轮廓处是否接近袜色；有没有黑块 / 紫块 | `{"sheer_visible": bool, "edge_fabric": bool, "artifacts": bool}` | 三项分别对应：参数 / 肤色来源错、W_MAX、寄存器覆写（步 05 regcheck） |

## JSON 校验后的保守分支

| VP | “看不清”或第二次仍无效时 |
|---|---|
| VP1 | 停在步 01，把问句交给用户；不猜独立网格/整个身体 |
| VP2 | 停在步 06，不让烘焙 DDS 进入正式 PS |
| VP3 | 保留 ini 的文字初判，把每格标签问用户；用户答案优先 |
| VP4 | 停在步 06，不扩大 UV 框；请用户圈出腿部范围 |
| VP5a | 停在步 11，不宣称接线命中；请用户手工回答两个 bool |
| VP5b | 保持案件未结，不调参；请用户手工回答三个 bool |

