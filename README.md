# Felix Toastmasters Agenda

把 Toastmasters 角色接龙和本期说明，变成内容准确、时间闭合、可直接使用的一页 A4 会单。

> **继承稳定内容，识别本期变化，自动完成加减计算，让整场会议重新闭合。**

## 最短用法

安装后，粘贴角色接龙或发送截图，只需说：

> 帮我把这份角色接龙做成会单。

就这一句。旧会单有就一起发，没有也可以开始。用户不需要准备配置文件，也不需要懂生成和排版技术。

## 它会怎么做

1. 先读你当前发来的文字、图片和附件，不重复追问已有信息。
2. 已经用过的俱乐部，会继承已确认的名称、地点、语言和常用信息；新俱乐部也不会因为没有旧会单而停下。
3. 如果真有影响会议承诺的信息缺失，会先说明已识别内容和当前进度，再把必要问题一次问完；最后问“是否还有其他希望呈现在会单上的”，自然带出介绍、Pathways、二维码等可选增强，但不阻断初版。
4. 必要信息齐全后，程序完成内容与时间校验，AI 直接给真实 A4 图片，不再让用户阅读长文字后回复“确认”。
5. 看图后可以一句话修改，也可以回复“直接导出”；确认交付时直接使用同一份已验证的 PDF/PNG，不再重新渲染。

如果当前电脑暂时缺少导出条件，会先保留已完成的会单内容，再用人话给你一个最短处理建议，不会把报错和内部命令丢给你。

## 怎么继续优化

成品出来后，直接说你想要的效果：

- “时间官宣言改成 1 分钟，总点评改成 10 分钟。”
- “重点环节小一点，其他字大一点。”
- “这期取消茶歇，合影负责人改成 Alex。”
- “这期只要纯议程。”

这些话已经足够，AI 会直接调整、重新校验并导出新版，不会再让你判断用什么技术实现，也不会要求你授权修改程序。你说“OK”“可以”或“就这样”，代表停止继续改版并交付当前成品。只有你说“以后都这样”，才会改变该俱乐部的长期默认。

## 哪些情况才会问你

- 不同理解会导致会单事实不同，又无法从当前材料判断；
- 已出现的角色负责人待定，或本期特殊环节缺少负责人、时长或先后位置；
- 第一次使用且无法从材料判断时，需要确认俱乐部身份、会议日期时间或地点；
- 会议必须超过原定结束时间，需要你确认准确的超时分钟数；
- 内容与“一页 A4 且清晰可读”冲突，必须由你选择保留哪部分。

这些情况会先说明已经识别了什么，再合并成一次人话询问，并给出可直接照抄的回答格式。主题、Pathways、介绍、二维码等可选增强不会拦住初版。

## V3 为什么分三阶段

- **信息确认**：该问的专业问题一次问清，可选信息不拦路。
- **视觉初版**：信息齐全后直接看图，不增加文字审批门。
- **修改与交付**：看图后再改，或立即交付同一份 PDF/PNG。

三阶段用于保证“内容准确”和“视觉好看”互不污染，不是要求用户连续回复三次确认。

## 用户能改到什么程度

- **会议内容**：角色、姓名、环节、顺序、时长、转场、标题和地点都能改；修改后自动重新闭合时间。
- **显示内容**：Pathways、俱乐部介绍、头马介绍、时间官规则、官员团队、二维码和自定义信息块都能增删。
- **视觉呈现**：可以用人话要求字大一点、重点强弱、增加显示列、调整信息先后和整体密度。
- **不需要用户配置**：模板、列宽、坐标、CSS、字体和技术实现由 Skill 自己处理。
- **不会突破的底线**：一页 A4、官方 Logo、清晰可读、不裁切、不隐藏、事实与时间准确。

## 三张示例不是三套模板

- 普通例会示例：四列主议程、无特别强调，使用平衡密度；
- 重点工作坊示例：增加 Pathways 列，只强调一个主环节，长介绍仍自然排版；
- 英文角色密集示例：全英文、更多议程行，使用紧凑间距但不缩成小字。

用户不需要选择“普通 / 工作坊 / 马拉松模板”。三张图使用同一个 renderer 和同一份 CSS，差异来自本期真实内容和受控的视觉意图。

## 会单内容能有多灵活

- 支持中文或英文；
- 同一套设计系统兼容普通例会、重点环节、演讲马拉松和角色密集会单；
- 支持新角色、新环节、工作坊、微课、圆桌和其他本期特殊安排；
- 时长、转场和超时授权支持 0.5 分钟；
- 即兴演讲与即兴点评联动计算；
- 固定信息区可选可组合，还可增加俱乐部自己的信息块；
- 同一份内容同步生成可核对文字、A4 PDF 和分享图。

可选信息区包括：时间官规则、头马介绍、会议秩序与四类禁忌、当届官员团队、俱乐部介绍、如何入会、VPM 入会二维码和本期投票二维码。首次使用时可以全选、部分选或只要纯议程；二维码始终使用用户提供的原图。

## 安装

GitHub：<https://github.com/FelixMaofei/felix-toastmasters-agenda>

不会命令行时，可以把上面的链接发给支持 Skill 安装的 AI，直接说：

> 请安装这个会单 Skill，安装后告诉我已经可以使用。

需要手动安装时：

```bash
# Codex
git clone https://github.com/FelixMaofei/felix-toastmasters-agenda.git ~/.agents/skills/felix-toastmasters-agenda

# WorkBuddy
git clone https://github.com/FelixMaofei/felix-toastmasters-agenda.git ~/.workbuddy/skills/felix-toastmasters-agenda
```

不要同时启用旧会单 Skill 和当前版本，否则自动识别可能命中错误版本。

## 给维护者

AI 负责理解用户、识别附件和映射本期变化；确定性程序负责时间闭合、姓名与关系检查、单页 A4 和品牌底线。这是“聪明模型 + 确定性验证”，不预设任何模型只能机械提取。

V3 主要入口：

```bash
SKILL_DIR="/path/to/felix-toastmasters-agenda"
python3 "$SKILL_DIR/scripts/run_agenda.py" doctor
python3 "$SKILL_DIR/scripts/run_agenda.py" first meeting.json --club-profile "俱乐部完整名称" --output-dir output
python3 "$SKILL_DIR/scripts/run_agenda.py" final output/agenda.preview.html --output-dir output
```

`draft / preview` 只用于维护、排错或纯视觉修改；普通首次制作使用 `first`，避免模型重复阅读和多次调用。

依赖：Python 3 负责确定性计算和生成；Chrome、Chromium 或 Edge 负责真实 A4 预览与 PDF；Poppler 可优先生成高清 PNG，缺失时使用浏览器兜底。缺少导出环境时，已经完成的文字会单仍会保留。

匿名输入示例见 `examples/meeting.example.json`。本地分发包应使用 `scripts/package_local.py` 生成，它只打包运行所需文件并在生成 ZIP 前扫描私有路径和内容。

更详细的内部输入结构、时间规则和受控执行见：

- [`references/input-schema.md`](references/input-schema.md)
- [`references/agenda-rules.md`](references/agenda-rules.md)
- [`references/local-model-workflow.md`](references/local-model-workflow.md)
- [`references/v3-architecture.md`](references/v3-architecture.md)
- [`references/v3-view-intent.md`](references/v3-view-intent.md)

最终只允许交付 1 页 A4 竖版 PDF 和 1 张 PNG。内容放不下时停止替换成品，保留上一版，再让用户在 1–2 个业务选择中决定。
