# V2 最小输入结构

meeting JSON 只保存“本期事实”。不要让模型填写派生的完整时间轴、开始时间、默认时长、转场或视觉样式；这些全部由生成器补齐。

```json
{
  "club": {
    "name": "Example Toastmasters Club",
    "default_location": "Meeting Room / Online",
    "language": "zh"
  },
  "meeting": {
    "number": "236",
    "date": "2026-07-08",
    "start": "19:30",
    "end": "21:30",
    "location": "Current Meeting Room",
    "theme": "本期主题",
    "word_of_day": "学习",
    "manager": "会议经理",
    "president": "会长姓名",
    "approved_overtime_minutes": 0
  },
  "roles": [],
  "prepared_speeches": [],
  "impromptu": null,
  "backstage": [],
  "special_segments": [],
  "standard_overrides": []
}
```

## 1. 俱乐部

- `name`：必填。
- `default_location`：必填；本期 `meeting.location` 可覆盖。
- `language`：`zh`、`en` 或 `bilingual`。

俱乐部首次初始化只需长期保存这三个字段。旧会单只能用来提取并确认它们，不能成为样式或流程模板。

## 2. 本期会议

- `number`：期数或本期标签。
- `date`：`YYYY-MM-DD`。
- `start`：`HH:MM`。
- `end`：可省略；省略时默认从开始时间起 120 分钟。
- `location`：可省略，回退到俱乐部默认地点。
- `theme`、`word_of_day`、`manager`：有则显示。
- `president`：用于会长致辞与闭幕；不是长期俱乐部配置。
- `approved_overtime_minutes`：默认 `0`。只有用户明确同意当前计算所需的准确分钟数后才能写入；内容变化后若超时分钟数不同，旧授权自动失效。

## 3. 角色

```json
{
  "roles": [
    {"id": "rules_host", "person": "成员A"},
    {"id": "toastmaster", "person": "成员B"},
    {"id": "timer", "person": "成员C"},
    {"id": "ah_counter", "person": "成员D"},
    {"id": "grammarian", "person": "成员E"},
    {"id": "guest_host", "person": "成员F"},
    {"id": "sharing_host", "person": "成员G"},
    {"id": "general_evaluator", "person": "成员H"},
    {"id": "awards_host", "person": "成员I"}
  ]
}
```

- 数组顺序保留接龙顺序。
- 角色条目不存在：接龙没有该角色，不生成它触发的环节。
- 角色存在但 `person: null`：环节存在，但缺负责人，必须询问。
- 姓名填入即视为本期承诺，不增加 `confirmed` 字段。
- `timer`、`ah_counter`、`grammarian` 分别由程序展开为宣言和报告。
- `general_evaluator` 只在角色存在时生成总点评。

## 4. 备稿演讲与点评

```json
{
  "prepared_speeches": [
    {
      "speaker": "成员A",
      "title": "演讲标题",
      "project": "PM L1 Ice Breaker",
      "minutes": 6,
      "evaluation_enabled": true,
      "evaluator": "成员B",
      "evaluation_minutes": 3
    }
  ]
}
```

- 演讲者与点评人放在同一个对象，避免两组数组错位。
- `minutes` 缺失时，普通备稿默认 7 分钟；明确破冰或项目时按当前项目要求。
- `evaluation_enabled` 默认 `true`。接龙明确没有该演讲点评时才设为 `false`。
- 需要点评时，`evaluator` 缺失或为 `null` 都表示负责人未完成，必须询问。
- 不要用漏写 `evaluator` 字段代表取消，避免弱模型静默漏掉点评。
- `evaluation_minutes` 缺失时默认 3 分钟。

## 5. 即兴

```json
{
  "impromptu": {
    "host": "成员A",
    "evaluator": "成员B",
    "minutes": null,
    "evaluation_minutes": null
  }
}
```

- 整个 `impromptu` 不存在或为 `null`：本期没有即兴。
- `evaluator` 字段不存在：有即兴，但没有即兴点评。
- `evaluator: null`：需要即兴点评，但点评人未定。
- 数字时长代表用户明确锁定；`null` 或省略交给程序计算。
- 即兴和即兴点评都未锁定时，程序在剩余时间内求整数解，使即兴点评约等于即兴演讲的一半，并让整场闭合。

## 6. 幕后团队

```json
{
  "backstage": [
    {"id": "photographer", "person": "成员A", "label": "拍照官"},
    {"id": "slides", "person": "成员B", "label": "场控/PPT"},
    {"id": "voting", "person": "成员C", "label": "投票链接"}
  ]
}
```

幕后团队不进入时间轴。摄影师只会被标准合影/休息环节引用，不会自行生成台前环节。

## 7. 特殊环节

```json
{
  "special_segments": [
    {
      "title": "AI领航",
      "owner": "成员A",
      "minutes": 10,
      "after": "guest_introduction"
    }
  ]
}
```

- `title`、`owner`、`minutes` 必填。
- `after` 可省略，默认放在嘉宾介绍之后。
- 可用锚点包括 `guest_introduction`、`prepared_speech:1`、`table_topics`、`photo_break`、`prepared_evaluation:1`、`sharing` 等。

## 8. 标准环节覆盖

只写本期明确变化，不要把全部默认环节重复一遍：

```json
{
  "standard_overrides": [
    {"id": "photo_break", "minutes": 8, "label": "合影＋茶歇"},
    {"id": "guest_introduction", "enabled": false}
  ]
}
```

可覆盖：

- `enabled`：`false` 表示本期明确取消；
- `minutes`：锁定本期时长；
- `owner`：覆盖默认负责人；
- `label`：覆盖显示名称；
- `transition_after`：覆盖默认转场分钟数。

## 9. 输出与退出码

```bash
python3 scripts/build_agenda.py meeting.json --output-dir output
```

- 退出码 `0`：负责人完整、时间闭合，计算 JSON、Markdown 和 HTML 已生成。
- 退出码 `2`：输入、负责人、角色关系或时间闭合失败；按错误修正或向用户确认。
