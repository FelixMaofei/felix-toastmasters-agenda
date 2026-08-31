# Felix Toastmasters Agenda V2

把 Toastmasters 角色接龙转换成内容准确、时间闭合、符合品牌规范的 A4 会单。

## 特点

- 适用于不同 Toastmasters 俱乐部；
- 支持中文、英文和中英双语；
- 不复刻旧会单样式；
- 弱模型只需提取本期事实，程序负责标准流程、默认时间、转场和结束点；
- 即兴演讲与即兴点评联动计算；
- 环节时长、转场和超时授权支持 0.5 分钟递增；
- 超出会议时间时停止并要求确认；
- 固定信息作为可选附页组件，不强制所有俱乐部使用同一组内容；
- 从同一份 JSON 生成 Markdown 和 A4 HTML。

## 可选信息附页

Skill 内置 8 个可选组件：时间官规则、头马介绍、会议秩序与四类禁忌、当届官员团队、俱乐部介绍、如何入会、VPM 入会二维码和本期投票二维码。

首次使用时，Skill 会询问要加入哪些。前四项只是推荐选项，不会在用户未选择时自动加入。可以全选、部分选择，也可以全部不选，只要纯议程。俱乐部可以保存常用组合，单期再完整覆盖。

两种二维码都必须使用用户提供的原始图片，不从截图裁切，不由模型重画或修复。

## 使用

安装到 Codex 或 WorkBuddy 后，直接说：

> 请使用 felix-toastmasters-agenda，把下面这份角色接龙做成会单。先自己识别已有信息，缺什么再一次问我。

旧会单是可选参考，不是必交材料。用户不需要自己准备 JSON 或配置文件；Skill 会先从当前消息、接龙和附件中识别，再询问无法判定的少量信息。

手动运行：

```bash
SKILL_DIR="/path/to/felix-toastmasters-agenda"
python3 "$SKILL_DIR/scripts/build_agenda.py" meeting.json --output-dir output
python3 "$SKILL_DIR/scripts/export_a4.py" output/agenda.html --output-dir output
```

匿名示例见 `examples/meeting.example.json`。

## 安装位置

GitHub：<https://github.com/FelixMaofei/felix-toastmasters-agenda>

Codex：

```bash
git clone https://github.com/FelixMaofei/felix-toastmasters-agenda.git ~/.agents/skills/felix-toastmasters-agenda
```

WorkBuddy：

```bash
git clone https://github.com/FelixMaofei/felix-toastmasters-agenda.git ~/.workbuddy/skills/felix-toastmasters-agenda
```

不要同时启用旧会单 Skill 和 V2，否则自动识别可能命中错误版本。

## 依赖与自检

- Python 3：计算和生成 Markdown/HTML；
- Chrome、Chromium 或 Edge：导出 A4 PDF；
- Poppler 的 `pdftoppm`：优先生成逐页 PNG；缺失时使用 Chrome 长图兜底。

```bash
python3 -m py_compile "$SKILL_DIR/scripts/build_agenda.py" "$SKILL_DIR/scripts/export_a4.py"
python3 "$SKILL_DIR/scripts/build_agenda.py" "$SKILL_DIR/examples/meeting.example.json" --output-dir /tmp/felix-agenda-smoke
python3 "$SKILL_DIR/scripts/export_a4.py" /tmp/felix-agenda-smoke/agenda.html --output-dir /tmp/felix-agenda-smoke
```

纯议程通常输出一页；选择固定信息组件后会增加信息附页。议程较长时会继续自动分页，输出多页 A4 PDF 和逐页 PNG，不会裁掉后半段。
