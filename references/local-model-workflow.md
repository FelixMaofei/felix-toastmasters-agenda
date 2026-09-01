# 本地 / 弱模型最短工作流

适用 WorkBuddy、本地模型或执行稳定性未知的 Agent。目标是让模型只负责提取事实，不参与时间计算、HTML 设计或 A4 适配。

Skill 已内置 Logo、图标、主题纹理和可合法分发的中英文字体。准备和导出全程不需联网，也不需本地模型改 CSS。

## 绝对不要做

- 不要求用户自己写 JSON；
- 不要求每期提供旧会单；
- 不要手算开始时间、结束时间、转场或剩余分钟；
- 不要修改 `agenda.computed.json`、`agenda.html` 或模板 CSS；
- 不要联网找图、换图标、调色或另做一张图；
- 不要跳过 `finalize`的视觉审计直接打印。
- 不要用 `find ~` 或其他宽泛搜索寻找 Skill、profile 或历史会单；
- 不要读取 `scripts/*.py` 源码、测试或历史输出，只执行 `scripts/run_agenda.py`。

## 先确定 Skill 目录

- WorkBuddy 默认直接使用 `~/.workbuddy/skills/felix-toastmasters-agenda`；
- 路径不存在时，再使用当前平台加载 Skill 时显示的 Base directory；
- 不向用户询问安装路径，不搜索整个主目录。

## 第 0 步：只检查一次环境

```bash
python3 "$SKILL_DIR/scripts/run_agenda.py" doctor
```

返回 `ok: true` 就继续。如果缺 Chrome/Chromium，直接告诉用户本机无法导出 PDF/PNG；不自行安装或改用其他打印方式。

## 第 1 步：从当前消息提取本期事实

先看用户当前粘贴的角色接龙、会议说明和附件。已出现的信息不再问。

只生成 `meeting.json`，主要是：

- `meeting`：期数、日期、正式开始/结束、本期地点、主题、今日一词、会议经理、会长；
- `roles`：接龙中真实出现的功能角色，保留顺序；
- `prepared_speeches`：每篇将演讲者、题目、时长、同编号点评人放在同一对象；
- `impromptu`：即兴主持、即兴点评人；用户没给时长就保留 `null`；
- `backstage`：拍照、场控/PPT、投票链接等，不进时间轴；
- `special_segments`：工作坊、微课等本期特殊环节，必须有负责人、时长和相对位置。

字段和空值语义不清楚时，只读 [输入结构](input-schema.md)。不预读 Python 源码或测试。

## 第 2 步：准备会单

始终使用俱乐部完整名称：

```bash
python3 "$SKILL_DIR/scripts/run_agenda.py" prepare meeting.json \
  --club-profile "俱乐部完整名称" \
  --output-dir output
```

- 退出 `0`：只读取并展示 `output/agenda.md`，请用户确认文字；
- 退出 `2`：只按 `errors` 中的缺失/冲突项询问，修改 `meeting.json` 后重跑；
- 不把 `warnings` 当成错误，但要把异常自动时长告诉用户。

## 第 3 步：只有用户确认后才完成导出

用 `prepare` 返回的 `finalize_command`，或运行：

```bash
python3 "$SKILL_DIR/scripts/run_agenda.py" finalize output/agenda.html \
  --output-dir output
```

必须同时看到：

```text
ok: true
stage: finalized
pages: 1
visual_audit: passed   # editorial 成品
```

`classic` 成品暂可返回 `visual_audit: not_provided`，但仍必须是 1 页 A4。

## 询问原则

- 一次只合并询问真正阻断生成的缺失事实；
- 用人话问，不暴露 JSON 字段名；
- 用户说“OK”就运行 finalize，不再追问；
- 成品生成后停止，不为了“更好看”自行继续改版。
