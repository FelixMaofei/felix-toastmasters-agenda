---
name: felix-toastmasters-agenda
description: 将 Toastmasters 角色接龙、会议说明或旧会单参考，转成时间重新闭合的一页 A4 中文、英文或双语会单。用于例会议程、角色接龙转会单、时间重算、自然语言修改以及 PDF/PNG 交付。
---

# Felix Toastmasters Agenda

核心价值：继承俱乐部稳定内容，识别本期变化，自动完成加减计算，让整场会议重新闭合。

用户只需提供角色接龙、本期说明和自然语言修改。Agent 负责确认信息和调用程序；时间计算、排版与文件检查交给程序。

## 1. 信息确认

先读用户当前消息和附件，并用一段简短的话说明：已识别的俱乐部、日期时间、角色、演讲、特殊环节，以及当前进度。

只问会改变负责人、流程或时间闭合，且当前无法判断的问题。特殊环节必须有标题、负责人、时长和相对位置，缺少任何一项都要问。把全部必要问题一次问清，并给一行可照抄的回答格式；最后问：

> 是否还有其他希望呈现在会单上的？

主题、Pathways、俱乐部介绍、入会信息、官员名单和二维码属于可选内容，不阻断初版。必要信息已经齐全时，不等待可选内容，直接生成图片。

角色材料没有“真情分享”时，可以与其他必要问题一起只确认一次：`本期有真情分享吗？有：负责人姓名；没有：取消。` 用户确认没有后，在本期输入加入 `{"agenda_overrides":[{"id":"sharing","enabled":false}]}`，此后不再追问。

用户说“没有其他内容”“不需要可选内容”或“纯会单”时，代表本期不继承 profile 的介绍、官员、规则、二维码或自定义信息块。内部输入必须同时写入 `meeting.support_components: []` 和 `meeting.custom_support_blocks: []`，不再逐项追问。

推荐提问格式：

> 我已识别：……
> 当前进度：补齐下面信息后，我会直接生成 A4 图片初版。
> 1. ……
> 2. ……
> 请直接回复：`1. ……；2. ……`
> 可选内容不影响初版。是否还有其他希望呈现在会单上的？

## 2. 完整信息直接出图

普通任务只做三件事：把本期事实写成 `simple_version: 1` 的简易 JSON；运行一次 `first`；向用户展示生成的 PNG。

`first` 是唯一运行入口，已经负责查找俱乐部长期资料、检查输入、计算时间和生成文件。加载 Skill 后直接使用给出的 Skill 目录，不需要先确认脚本路径、查找 profile、列目录或检查依赖。

简易输入使用自然语言角色和位置。中文可写“时间官”“总主持”“备稿演讲1”“即兴点评”，英文可写 `Timer`、`Toastmaster`、`Prepared Speech 1`、`Table Topics Evaluation`。不知道的信息不要猜；先按上一节提问。

下面是一份紧凑但完整的示例：

```json
{
  "simple_version": 1,
  "club": {"name": "示例头马演讲俱乐部", "language": "zh", "default_location": "示例会议室"},
  "meeting": {"number": "236", "date": "2026-09-02", "start": "19:30", "end": "21:30", "location": "示例会议室", "theme": "持续成长", "word_of_day": "笃行", "manager": "成员甲", "president": "成员乙"},
  "roles": [
    {"role": "会议规则", "person": "成员丙"},
    {"role": "总主持", "person": "成员丁"},
    {"role": "时间官", "person": "成员丙"},
    {"role": "哼哈官", "person": "成员戊"},
    {"role": "语法官", "person": "成员己"},
    {"role": "嘉宾介绍", "person": "成员庚"},
    {"role": "真情分享", "person": "成员丙"},
    {"role": "总点评", "person": "成员辛"},
    {"role": "颁奖主持", "person": "成员庚"}
  ],
  "speeches": [{"speaker": "成员乙", "title": "我的第一步", "evaluator": "成员戊"}],
  "impromptu": {"host": "成员壬", "evaluator": "成员乙"},
  "backstage": [
    {"role": "拍照", "person": "成员癸"},
    {"role": "场控/PPT", "person": "成员丑"},
    {"role": "投票", "person": "成员寅"}
  ],
  "special": [{"title": "AI 工作坊", "owner": "成员子", "minutes": 20, "after": "嘉宾介绍"}]
}
```

`club.language` 使用 `zh`、`en` 或 `bilingual`。常用相对位置可直接写：嘉宾介绍、备稿演讲1、即兴演讲、合影休息、备稿点评1、即兴点评、真情分享；英文写法也可直接使用。

俱乐部名称明确时，无论新旧俱乐部都直接运行同一条命令：

```bash
python3 "$SKILL_DIR/scripts/run_agenda.py" first meeting.json \
  --club-profile "俱乐部完整名称" --output-dir output
```

程序会自行处理 profile：找到就继承稳定内容，没找到就按当前 JSON 初始化；本期 JSON 中的明确事实始终优先。Agent 不预先读取或搜索 profile。输出目录放在 Skill 安装目录之外。

- 返回 `needs_input`：把程序列出的全部缺项合并为一次用户提问。
- 返回 `preview_ready`：直接展示 `agenda.preview.png`，并保留同一版 `agenda.preview.pdf`。

展示初版时只需告诉用户：

> 这版已经可以直接交付。你可以回复“直接导出”，也可以一句话告诉我哪里要改。

## 3. 修改与交付

用户可以直接说“总点评改成 10 分钟”“把合影放在即兴点评后”“字大一点”。角色、演讲、即兴、幕后或特殊环节变化时，更新同一简易 JSON 中的 `roles / speeches / impromptu / backstage / special` 后重新运行 `first`。

标准环节的时长等改动可在简易 JSON 中增加最小覆盖，例如：

```json
{"agenda_overrides": [{"id": "general_evaluation", "minutes": 10}]}
```

用户确认本期没有真情分享时，使用 `{"agenda_overrides":[{"id":"sharing","enabled":false}]}`。这个确认保存在同一份本期 JSON 中，后续内容或视觉修改不得再次追问。

纯视觉变化使用最小 `view.patch.json`，例如 `{"design":{"text_scale":"large"}}`，并在 `first` 后增加 `--view-patch view.patch.json`。每次修改都由程序重新检查时间和版面，并展示新的 `agenda.preview.png`。

用户说“直接导出”“可以”“OK”或“就这样”时，只运行：

```bash
python3 "$SKILL_DIR/scripts/run_agenda.py" final \
  output/agenda.preview.html --output-dir output
```

`final` 原样交付用户已看到的预览 PDF/PNG，不重新计算或排版。成功后交付 `agenda.pdf` 和 `agenda.png`。

## 成品要求

- 本期明确事实优先于俱乐部长期资料；单期变化不自动写回长期设置。
- 姓名、顺序、时长和转场由程序计算；视觉修改不改变会议事实。
- 成品为一页 A4，使用官方 Logo，清晰可读，不裁切、不隐藏。
- 中文、英文和中英双语均可，按本期材料生成。
- 最终只说明会单已完成、时间是否闭合、本轮修改是否落实，并交付 PDF/PNG。
