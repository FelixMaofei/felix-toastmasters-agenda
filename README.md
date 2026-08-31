# Felix Toastmasters Agenda V2

把 Toastmasters 角色接龙转换成内容准确、时间闭合、符合品牌规范的 A4 会单。

## 特点

- 适用于不同 Toastmasters 俱乐部；
- 支持中文、英文和中英双语；
- 不复刻旧会单样式；
- 弱模型只需提取本期事实，程序负责标准流程、默认时间、转场和结束点；
- 即兴演讲与即兴点评联动计算；
- 环节时长、转场和超时授权支持 0.5 分钟递增；
- 根据会议内容自动选择标准例会、重点环节或演讲马拉松版式；
- 根据本期主题选择受控的色彩与纹理，并支持可选无文字主题图；
- 普通中文/英文例会可自动使用高密度 editorial A4 呈现器，纯议程、双语和马拉松继续使用 classic；
- editorial 导出前自动阻断裁切、越界、孤字、小字和对齐错误；
- 首次确认后按俱乐部名称保存轻量本机 profile，新任务只需提供本期接龙和变化；
- WorkBuddy/本地模型使用 `run_agenda.py doctor|prepare|finalize` 固定入口，不需要模型自行组装命令；
- `package_local.py` 只打包运行所需的白名单文件，并在生成 ZIP 前做私有路径/内容扫描；
- 超出会议时间时停止并要求确认；
- 固定信息作为可选单页信息组件，不强制所有俱乐部使用同一组内容；
- 支持用标题和纯文本行扩展自定义信息组件，排版器自动分配左栏与底部；
- 从同一份 JSON 生成 Markdown 和 A4 HTML。

## 可选固定信息区

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

最终只允许输出 1 页 A4 竖版 PDF 和 1 张 PNG。固定信息组件与议程整合在同一页；内容放不下时停止并请用户精简环节或组件，不跨页、不裁切、不缩成不可读小字。
