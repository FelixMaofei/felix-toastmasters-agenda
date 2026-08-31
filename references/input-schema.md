# V2 最小输入结构

meeting JSON 是 Skill 内部的生成器输入，不是要求用户填写的表单。Skill 应先从当前消息、接龙和附件中主动识别已有事实，只询问无法判定的少量信息；旧会单为可选参考。

meeting JSON 只保存“本期事实”。不要让模型填写派生的完整时间轴、各行开始时间、默认时长、转场、CSS、尺寸或坐标；这些全部由生成器补齐。可以传递用户明确选择的语义版式、重点环节和主题方向。

所有显式 `minutes`、`transition_after` 和 `approved_overtime_minutes` 都支持 0.5 分钟递增。输入 0.5 就按 30 秒计算，不通过修改其他环节补数。

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
    "layout": "auto",
    "feature_item": null,
    "visual_theme": "auto",
    "approved_overtime_minutes": 0
  },
  "roles": [],
  "prepared_speeches": [],
  "impromptu": null,
  "backstage": [],
  "special_segments": [],
  "standard_overrides": [],
  "transition_overrides": []
}
```

## 1. 俱乐部

- `name`：首次初始化或未加载 profile 时必填。
- `default_location`：首次初始化或未加载 profile 时必填；本期 `meeting.location` 可覆盖。
- `language`：`zh`、`en` 或 `bilingual`；首次初始化或未加载 profile 时必填。

生成器会先合并 profile，再做必填验证。因此使用 `--club-profile` 后，日常 meeting JSON 可以完全省略 `club`，只保留本期事实。

俱乐部首次初始化至少保存这三个身份字段，并记录用户选择的固定信息组件。最小 JSON 故意省略 `support_components`，因为字段缺失表示“尚未选择，必须问”；`[]` 只能在用户明确只要纯议程时写入。

旧会单可以帮助识别身份、当届官员和常用组件的候选值，但不能成为视觉样式或固定流程模板。只有用户确认后才保存；旧会单出现过某组件，不自动等于俱乐部的长期选择，任期官员也要确认仍为当届。

### 跨新任务复用俱乐部信息

生成器使用固定的本机资料库 `~/.toastmasters-agenda/profiles/`。文件名由“规范化后的俱乐部名称 + 短哈希”确定性生成，因此不依赖当前任务目录，也不会因同一工作目录有多个俱乐部而覆盖。俱乐部名称是身份主键；地点只能辅助提示，不能单独用于匹配。

首次初始化并确认后，下面的命令会在生成成功后自动创建 profile：

```bash
python3 "$SKILL_DIR/scripts/build_agenda.py" meeting.json --club-profile "星河头马演讲俱乐部" --output-dir output
```

之后的新任务继续使用同一命令；生成器会在校验前加载 profile，meeting JSON 无需重复俱乐部稳定字段。如果当前资料库有多家俱乐部而用户未说名称，先只问“这是哪家俱乐部？”，不用地点自行猜测。

profile 保存俱乐部名称、默认地点、语言、固定组件、当届官员、俱乐部介绍、入会信息、VPM 二维码和俱乐部自定义块；不保存本期角色、日期、时长、顺序或会议号。长期更新时，必须把新值写入 meeting JSON 的 `club.<field>`，再增加 `--update-club-profile`；例如长期默认地点改用 `club.default_location`，`meeting.location` 只表示本期地点。官方俱乐部名称变更时使用新名称创建新 profile。

### 固定信息组件

固定信息组件必须由用户选择，可以为空。字段缺失表示“尚未选择，必须问”；`[]` 表示“用户已明确只要纯议程，不显示固定信息区”。

取值顺序：

1. `meeting.support_components` 存在：完整采用它，包括 `[]`；
2. 否则 `club.support_components` 存在：完整采用它，包括 `[]`；
3. 两处都不存在：询问用户；
4. 单期数组是完整覆盖，不与俱乐部数组合并。

可选组件：

| ID | 内容 | 所需输入 |
|---|---|---|
| `timer_rules` | 内置时间官规则 | 无 |
| `toastmasters_intro` | 内置头马介绍 | 无 |
| `meeting_boundaries` | 内置会议秩序与四类禁忌 | 无 |
| `officers` | 当届官员团队 | `club.officers` |
| `club_intro` | 俱乐部介绍 | `club.club_intro` |
| `join_info` | 如何入会 | `club.join_info` |
| `vpm_qr` | VPM 入会二维码 | `club.vpm_qr_image` |
| `voting_qr` | 本期投票二维码 | `meeting.voting_qr_image` |

首次询问时，可以把前四项作为推荐选项展示，但推荐不等于自动加入。未经用户选择不得写入。用户可以全选、部分选择或使用空数组只生成议程页。

官员团队使用：

```json
{
  "officers": [
    {"role": "President", "name": "Member A"},
    {"role": "VPE", "name": "Member B"},
    {"role": "VPM", "name": "Member C"},
    {"role": "VPPR", "name": "Member D"},
    {"role": "Secretary", "name": "Member E"},
    {"role": "Treasurer", "name": "Member F"},
    {"role": "SAA", "name": "Member G"}
  ]
}
```

`club_intro` 和 `join_info` 可使用字符串数组。`club.vpm_qr_image` 和 `meeting.voting_qr_image` 都可用绝对路径，或使用相对于本期 meeting JSON 的路径。保存 profile 时，生成器会把 VPM 二维码原图复制到该 profile 的固定 `assets/` 目录，后续不再依赖首次任务或临时附件路径。本期投票二维码不进入 profile。生成器只嵌入用户原图；不从旧 PDF/截图裁切，不重绘或修复二维码。

### 自定义固定信息块

用户需要内置列表外的信息时，使用 `custom_support_blocks`：

```json
{
  "custom_support_blocks": [
    {
      "id": "pathways",
      "title": "Pathways 教育路径",
      "lines": [
        "DL - 动态领导",
        "PM - 精通演讲",
        "VC - 愿景沟通"
      ],
      "placement": "auto"
    }
  ]
}
```

- `id`、`title` 和至少一条 `lines` 必填；
- 内容只按纯文本渲染，不接受 HTML；
- `placement` 可为 `auto`、`left` 或 `bottom`，默认 `auto`。`left` 是兼容字段名，意思是“放入当前版式的侧边信息栏”；在 `feature` 中实际会显示在右侧。
- `club.custom_support_blocks` 保存俱乐部常用块；`meeting.custom_support_blocks` 存在时完整覆盖俱乐部列表；
- 排版器按内容体量在当前版式的侧栏、横向条与底部之间装箱；具体位置见 [版式路由与主题视觉系统](visual-system.md)。内容太多时由单页 A4 导出校验阻断。

## 2. 本期会议

- `number`：期数或本期标签。
- `date`：`YYYY-MM-DD`。
- `start`：`HH:MM`；半分钟节点可用 `HH:MM:30`。
- `end`：可省略；省略时默认从开始时间起 120 分钟，也支持 `HH:MM:30`。
- `location`：可省略，回退到俱乐部默认地点。
- `theme`、`word_of_day`、`manager`：有则显示。
- `president`：用于会长致辞与闭幕；不是长期俱乐部配置。
- `layout`：`auto`、`standard`、`feature` 或 `marathon`。默认 `auto`；除非用户明确选择，不需要追问。
- `feature_item`：可选的本期环节 ID，用于多个重点候选时指定主舞台，例如 `special:2` 或 `prepared_speech:1`。用户未指定时不需追问，生成器自动选时长最长者，同长选更早出现者。
- `visual_theme`：`auto`、`general`、`learning`、`technology`、`wellness`、`voice`、`leadership` 或 `celebration`。默认优先从本期主题和今日一词识别。
- `theme_image`：可选的 PNG/JPG/SVG/WebP 主题图路径。图中不得包含文字、Logo、人名、时间或二维码；相对路径以 meeting JSON 所在目录为基准。
- `approved_overtime_minutes`：默认 `0`，支持 0.5 分钟递增。只有用户明确同意当前计算所需的准确分钟数后才能写入；内容变化后若超时分钟数不同，旧授权自动失效。
- `support_components`：可选；本期需要改变俱乐部常用组合时覆盖 `club.support_components`。
- `voting_qr_image`：选择 `voting_qr` 组件时必填。

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
- 即兴和即兴点评都未锁定时，程序按 0.5 分钟步进在剩余时间内求解，使即兴点评约等于即兴演讲的一半，并让整场闭合；有等价解时优先整分钟。

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
      "details": ["现场体验", "方法拆解", "动手实作"],
      "after": "guest_introduction"
    }
  ]
}
```

- `title`、`owner`、`minutes` 必填。
- `details` 可选，用字符串或字符串数组表达主题、形式或过程要点；进入 `feature` 版式时显示在专题舞台内。
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
- `transition_after`：覆盖默认转场分钟数，可使用 `0.5`。

## 9. 任意环节转场覆盖

备稿点评、即兴点评、时间官/哼哈官/语法官报告等角色触发环节不属于 `standard_overrides`。需要单独调整它们的转场时，使用：

```json
{
  "transition_overrides": [
    {"id": "prepared_evaluation:1", "minutes": 0.5},
    {"id": "table_topics_evaluation", "minutes": 0.5},
    {"id": "timer_report", "minutes": 0.5}
  ]
}
```

- `id` 必须是本期已生成的环节 ID；
- 备稿演讲/点评使用 `prepared_speech:1`、`prepared_evaluation:1` 等编号 ID；
- 即兴与即兴点评使用 `table_topics`、`table_topics_evaluation`；
- 官员报告使用 `timer_report`、`ah_counter_report`、`grammarian_report`；
- `minutes` 支持 `0`、`0.5`、`1` 等 0.5 分钟递增；
- 同一环节不要同时在两处覆盖转场。

## 10. 输出与退出码

```bash
python3 scripts/build_agenda.py meeting.json --output-dir output
```

- 退出码 `0`：负责人完整、时间闭合，计算 JSON、Markdown 和 HTML 已生成。
- 退出码 `2`：输入、负责人、角色关系或时间闭合失败；按错误修正或向用户确认。

HTML 仍需经 `export_a4.py` 验证。只有实际 PDF 为 1 页 A4 竖版时才能交付；如果浏览器排版产生第 2 页，导出器会删除无效 PDF 并退出 `2`。
