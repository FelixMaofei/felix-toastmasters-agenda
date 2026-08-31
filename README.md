# Felix Toastmasters Agenda V2

把 Toastmasters 角色接龙转换成内容准确、时间闭合、符合品牌规范的 A4 会单。

## 特点

- 适用于不同 Toastmasters 俱乐部；
- 支持中文、英文和中英双语；
- 不复刻旧会单样式；
- 弱模型只需提取本期事实，程序负责标准流程、默认时间、转场和结束点；
- 即兴演讲与即兴点评联动计算；
- 超出会议时间时停止并要求确认；
- 从同一份 JSON 生成 Markdown 和 A4 HTML。

## 使用

安装到 Codex 或 WorkBuddy 后，直接说：

> 请使用 Felix 头马会单 V2，根据我发送的本期角色接龙制作会单。缺失信息一次问完，先确认文字，再交付 A4 成品。

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

普通例会通常输出一页；内容较多时自动生成多页 A4 PDF 和逐页 PNG，不会裁掉后半段。
