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
3. 如果真有影响成品的信息缺失，会先说出已识别的内容，再把缺项合并成一次短询问。
4. 信息够用后先做出可核对的会单，自动重算环节、转场和结束时间，再导出一页 A4 PDF 和分享图。
5. 你可以继续用人话修改；如果新版未通过单页检查，上一份可用成品仍会保留。

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
- 第一次使用时，需要确认俱乐部基本信息和常用信息区；
- 会议必须超过原定结束时间，需要你确认准确的超时分钟数；
- 内容与“一页 A4 且清晰可读”冲突，必须由你选择保留哪部分。

这些情况会尽量合并为一次人话询问。不会因为没有旧会单、你不需要了解内部技术，或者你只想把字改大一点而卡住。

## 会单内容能有多灵活

- 支持中文、英文和中英双语；
- 支持普通例会、重点环节和演讲马拉松等不同密度；
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

主要入口：

```bash
SKILL_DIR="/path/to/felix-toastmasters-agenda"
python3 "$SKILL_DIR/scripts/run_agenda.py" doctor
python3 "$SKILL_DIR/scripts/run_agenda.py" prepare meeting.json --club-profile "俱乐部完整名称" --output-dir output
python3 "$SKILL_DIR/scripts/run_agenda.py" finalize output/agenda.html --output-dir output
```

依赖：Python 3 负责计算和生成；Chrome、Chromium 或 Edge 负责导出 A4 PDF；Poppler 可优先生成逐页 PNG，缺失时使用浏览器长图兜底。

匿名输入示例见 `examples/meeting.example.json`。本地分发包应使用 `scripts/package_local.py` 生成，它只打包运行所需文件并在生成 ZIP 前扫描私有路径和内容。

更详细的内部输入结构、时间规则和受控执行见：

- [`references/input-schema.md`](references/input-schema.md)
- [`references/agenda-rules.md`](references/agenda-rules.md)
- [`references/local-model-workflow.md`](references/local-model-workflow.md)

最终只允许交付 1 页 A4 竖版 PDF 和 1 张 PNG。内容放不下时停止替换成品，保留上一版，再让用户在 1–2 个业务选择中决定。
