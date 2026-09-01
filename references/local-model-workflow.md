# 自然语言与受控执行工作流

适用 WorkBuddy、Codex 和其他能执行本地命令的 Agent。模型负责理解用户、映射本期变化和判断信息重点；程序负责时间计算、确定性排版和文件导出。不因模型不同而预设它只能做机械提取。

Skill 内置官方 Logo 和可分发字体。正常工作不联网，也不让模型每期重写 CSS。

## 首轮先读材料，再决定是否问

先检查当前消息、图片、附件和文件名。已有事实不再问。再按完整俱乐部名称查找 profile；没有旧会单或 profile 也要继续初始化。

只有会单语言、固定信息选择或已出现环节的真实负责人等关键信息仍无法判断时，才用一条普通消息合并询问并结束当前轮。不要先运行命令、创建半成品或把字段名扔给用户。

## 绝对不要做

- 不要求用户自己写 JSON；
- 不要求每期提供旧会单；
- 不手算开始时间、结束时间、转场或剩余分钟；
- 不让用户选择 renderer、模板、CSS 或 Python 权限；
- 不把会议类型、时长或剩余面积当作版式路由；
- 不跳过文字确认和样式确认；
- 不用图片模型重排会单文字，也不生成或修复二维码；
- 不用宽泛主目录搜索寻找 Skill、profile 或历史会单；
- 当前消息明显有真实缺项时，不先检查源码和运行环境。

## 第 1 步：提取本期事实

只生成内部 `meeting.json`：

- `meeting`：期数、日期、正式开始/结束、本期地点、主题、今日一词、会议经理、会长；
- `roles`：接龙中真实出现的功能角色，保留顺序；
- `prepared_speeches`：每篇将演讲者、题目、时长、同编号点评人放在同一对象；
- `impromptu`：即兴主持、即兴点评人；用户没给时长就保留 `null`；
- `backstage`：拍照、场控/PPT、投票链接等，不进时间轴；
- `special_segments`：工作坊、微课等本期特殊环节，必须有负责人、时长和相对位置；
- `participant_pathways`：仅在用户提供真实 Pathways 进展时，用姓名映射到 `PM L1` 等文字。

接龙明确顺序优先。若自动环节与接龙顺序不同，用 `agenda_overrides.after` 表达；不要改源码或接受错误顺序。字段和空值语义不清楚时，只读 [输入结构](input-schema.md)。

## 第 2 步：生成文字会单

```bash
python3 "$SKILL_DIR/scripts/run_agenda.py" draft meeting.json \
  --club-profile "俱乐部完整名称" \
  --output-dir output
```

- 退出 `0`：读取 `output/agenda.md`，向用户展示并确认姓名、顺序、时长、地点和固定信息；此目录不应有 HTML。
- 退出 `2`：只按 `errors` 中的缺失或冲突处理；超时只询问准确分钟数。
- 内容反馈修改 meeting JSON 后重跑 `draft`。用户确认内容前停止，不进入视觉层。

Python 不可用时，先保留已识别的会议事实并用人话说明“当前电脑暂时不能完成可靠的时间重算”；不要把未经计算的手排时间冒充闭合会单。

## 第 3 步：生成样式确认稿

内容确认后，根据 [V3 视觉意图](v3-view-intent.md) 生成内部 `output/agenda.view.json`：

- 主议程永远是第一使用重点；
- 最多强调一个真实环节，不因时长长自动强调；
- 只有计算结果存在真实数据时才显示 Pathways 等辅助列；
- 每个固定组件恰好出现一次，并分入运营信息或背景信息；
- view 不包含模板名、左右位置、列宽、CSS、HTML、隐藏、截断和整体缩放。

需要导出时只检查一次环境：

```bash
python3 "$SKILL_DIR/scripts/run_agenda.py" doctor
```

随后运行：

```bash
python3 "$SKILL_DIR/scripts/run_agenda.py" preview output/agenda.computed.json \
  --view output/agenda.view.json \
  --output-dir output
```

必须打开真实 `agenda.preview.png`，检查整页层级、主流程原始字号、负责人列、对齐、裁切、重叠、空卡和组件内部死空白。再把预览给用户确认是否好看。自动检查通过不等于用户已经认可。

Chrome/Chromium 不可用时，文字会单仍然有效；保留它并给一个最短环境建议，不交付未经真实渲染的视觉成品。

## 第 4 步：导出确认后的文件

用户确认样式后运行：

```bash
python3 "$SKILL_DIR/scripts/run_agenda.py" final output/agenda.preview.html \
  --output-dir output
```

必须看到 `ok: true`、`stage: finalized` 和 `pages: 1`。随后再次打开最终 PNG，确认它与已确认预览一致，再交付 PDF/PNG。`final` 不读取 meeting JSON，不重新计算，不改变 HTML。

## 用户要求调整时

- 时长、负责人、名称、开关、转场和顺序属于内容变化，写入 `agenda_overrides` 后回到 `draft`；
- “字大一点”“重点弱一点”“加入 Pathways 列”“俱乐部介绍放后面”属于视觉变化，只改 `agenda.view.json` 后重跑 `preview`；
- “负责人没对齐、有死空白、列宽难看”是 renderer 问题，不给 view 增加字段，也不让用户授权改技术；
- 纯视觉调整前后，计算结果中的姓名、顺序、时长、地点和正文必须一致；
- 如果一页装不下，保留上一份可用成品，只给 1-2 个业务取舍选项。

## 完成回复

最终只说明：会单已完成、时间是否闭合、本轮变化是否落实，并交付 PDF/PNG。不要向普通用户展示 JSON、HTML、profile 路径、技术阶段或检查日志。用户说“OK”“就这样”表示停止继续改版。只有长期设置确实更新成功时，才说“以后默认沿用”。
