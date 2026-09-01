# V3 最小输入结构

meeting JSON 是 Skill 内部的生成器输入，不是要求用户填写的表单。Skill 应先从当前消息、接龙和附件中主动识别已有事实，只询问无法判定的少量信息；旧会单为可选参考。

meeting JSON 只保存“本期事实”。不要让模型填写派生的完整时间轴、各行开始时间、默认时长、转场、视觉重点、CSS、尺寸或坐标；这些分别由计算层和视觉层处理。

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
    "approved_overtime_minutes": 0
  },
  "roles": [],
  "prepared_speeches": [],
  "impromptu": null,
  "participant_pathways": {},
  "backstage": [],
  "special_segments": [],
  "standard_overrides": [],
  "agenda_overrides": [],
  "transition_overrides": []
}
```

## 1. 俱乐部

- `name`：首次初始化或未加载 profile 时必填。
- `default_location`：首次初始化或未加载 profile 时必填；本期 `meeting.location` 可覆盖。
- `language`：`zh`、`en` 或 `bilingual`；首次初始化或未加载 profile 时必填。
- “你直接做”“我不懂配置”不等于已经选择语言或固定信息组件；仍需与其他缺项合并询问一次。

生成器会先合并 profile，再做必填验证。因此使用 `--club-profile` 后，日常 meeting JSON 可以完全省略 `club`，只保留本期事实。

俱乐部首次初始化至少保存这三个身份字段，并记录用户选择的固定信息组件。最小 JSON 故意省略 `support_components`，因为字段缺失表示“尚未选择，必须问”；`[]` 只能在用户明确只要纯议程时写入。

旧会单可以帮助识别身份、当届官员和常用组件的候选值，但不能成为视觉样式或固定流程模板。只有用户确认后才保存；旧会单出现过某组件，不自动等于俱乐部的长期选择，任期官员也要确认仍为当届。

### 跨新任务复用俱乐部信息

生成器使用固定的本机资料库 `~/.toastmasters-agenda/profiles/`。文件名由“规范化后的俱乐部名称 + 短哈希”确定性生成，因此不依赖当前任务目录，也不会因同一工作目录有多个俱乐部而覆盖。俱乐部名称是身份主键；地点只能辅助提示，不能单独用于匹配。

首次初始化并确认后，下面的命令会在生成成功后自动创建 profile：

```bash
python3 "$SKILL_DIR/scripts/run_agenda.py" draft meeting.json --club-profile "星河头马演讲俱乐部" --output-dir output
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
      ]
    }
  ]
}
```

- `id`、`title` 和至少一条 `lines` 必填；
- 内容只按纯文本渲染，不接受 HTML；
- `club.custom_support_blocks` 保存俱乐部常用块；`meeting.custom_support_blocks` 存在时完整覆盖俱乐部列表；
- 自定义块在内容层不写左右、底部或列宽。内容确认后，由 `agenda.view.json` 将其放入运营信息或背景信息，并决定同组阅读顺序。

## 2. 本期会议

- `number`：期数或本期标签。
- `date`：`YYYY-MM-DD`。
- `start`：`HH:MM`；半分钟节点可用 `HH:MM:30`。
- `end`：可省略；省略时默认从开始时间起 120 分钟，也支持 `HH:MM:30`。
- `location`：可省略，回退到俱乐部默认地点。
- `theme`、`word_of_day`、`manager`：有则显示。
- `president`：用于会长致辞与闭幕；不是长期俱乐部配置。
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

## 6. 可选 Pathways 进展

只有用户提供真实资料并希望显示 Pathways 列时，才加入：

```json
{
  "participant_pathways": {
    "成员A": "PM L1",
    "成员B": "DL L2"
  }
}
```

- 键使用会单中出现的负责人姓名，值使用用户提供的简短进展；
- 程序按姓名精确匹配，不从会员身份、演讲项目或其他人的记录猜测；
- 没有匹配资料的负责人保持空白，不用破折号制造假信息；
- 这只是本期内容事实，不自动写入俱乐部长期 profile。

## 7. 幕后团队

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

## 8. 特殊环节

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
- `owner` 必须是本期真实负责人姓名；不能用“Toastmaster”“主持人”“待定”等角色称呼代替。材料没有姓名时询问用户。
- `details` 可选，用字符串或字符串数组表达主题、形式或过程要点；视觉层可在重点行中作为辅助说明显示。
- `after` 可省略，默认放在嘉宾介绍之后。
- 可用锚点包括 `guest_introduction`、`prepared_speech:1`、`table_topics`、`photo_break`、`prepared_evaluation:1`、`sharing` 等。
- 特殊环节按数组顺序取得稳定 ID：第一项为 `special:1`，第二项为 `special:2`，以此类推；后续覆盖和锚点使用这个 ID。

## 9. 任意环节统一覆盖（推荐）

用户对本期已存在环节的修改，统一使用 `agenda_overrides`，不需要先判断它是标准环节、角色触发环节还是演讲点评：

```json
{
  "agenda_overrides": [
    {"id": "timer_intro", "minutes": 1},
    {"id": "general_evaluation", "minutes": 10},
    {"id": "photo_break", "label": "合影＋茶歇", "minutes": 8},
    {"id": "ah_counter_intro", "enabled": false},
    {"id": "prepared_evaluation:1", "owner": "新点评人", "transition_after": 0.5},
    {"id": "table_topics_evaluation", "after": "table_topics", "section": "first_half"}
  ]
}
```

可用字段：

- `id`：已生成环节的稳定 ID，必填；
- `minutes`：本期时长，支持 0.5 分钟递增；
- `owner`：本期负责人；
- `label`：本期显示名称；
- `enabled`：`false` 明确取消该环节；
- `transition_after`：该环节后的转场，支持 0.5 分钟递增。
- `after`：本期明确顺序与默认流程不同时，把该环节移动到另一个已生成环节之后；只改变顺序，不自动改变原阶段。
- `section`：仅在用户同时改变环节所属阶段时使用，可为 `opening / first_half / second_half / closing`。

覆盖在全部标准、角色和特殊环节完成组装后应用，然后程序按本期顺序重新求解整场时间。不允许直接覆盖 `start / end`，它们始终由程序派生。`after` 只改变相对顺序，默认保留环节原来的阶段；确实要跨阶段时再同时写 `section`。`after` 不能指向自身、已取消环节或形成循环。

## 9.1 旧版标准环节覆盖（兼容）

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

## 9.2 旧版任意环节转场覆盖（兼容）

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

## 10. 内部视觉意图

用户确认 `agenda.md` 后，AI 另行生成 `agenda.view.json`。它只表达本期强调的环节、显示列、运营/背景组件顺序、密度、字号档位和对比度；不进入 meeting JSON，也不复制姓名、时间和正文。

完整合同见 [V3 视觉意图](v3-view-intent.md)。以下内容一律禁止进入 view：模板名、会议类型、左右位置、坐标、列宽、CSS、HTML、隐藏/截断、整体缩放和按时长分配面积。

## 11. 输出与退出码

```bash
python3 scripts/run_agenda.py draft meeting.json --output-dir output
```

- 退出码 `0`：负责人完整、时间闭合，只生成计算 JSON、Markdown、诊断和阶段清单；不生成 HTML。
- 退出码 `2`：输入、负责人、角色关系或时间闭合失败；按错误修正或向用户确认。

内容确认后再运行 `preview` 生成真实 A4 样式稿；样式确认后运行 `final`。只有实际 PDF 为 1 页 A4 竖版时才能交付；如果浏览器排版产生第 2 页，导出器会删除无效 PDF 并退出 `2`。
