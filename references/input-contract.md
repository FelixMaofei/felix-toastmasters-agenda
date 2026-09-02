# `meeting.json` 输入合同（按需读取）

普通会单直接按 `SKILL.md` 先调用 `confirm` 生成文字确认稿，用户确认后再调用 `image`。只有当前材料包含特殊环节、顺序变化、非默认时长、辅助信息或视觉修改，而你不确定字段怎样表达时，才读本文件。

## 基本原则

- `meeting.json` 是 Agent 生成的内部文件，不是用户表单。
- 只写用户明确提供的本期事实；不要写完整时间轴、派生开始时间、CSS、坐标或列宽。
- 本期事实覆盖 profile。单期变化不写回长期资料。
- 所有分钟数支持 `0.5` 步进。
- 不知道的可选内容可以省略；已经出现但缺负责人的角色写 `null`。特殊环节缺负责人、时长或位置时先询问，不能猜。
- 可选信息不阻断初版。提问时具体说明：是否补充俱乐部介绍、是否展示官员名单；如有二维码或 Pathways 也可一起提供。
- 角色接龙中的活动介绍、宣传亮点、邀请语和群公告文案默认不写入 `custom_support_blocks`；只提取明确的主题、今日一词等会单字段。只有用户明确要求展示时才加入全文。
- 俱乐部简介、常用地点、语言、官员名单、真实入会方式和入会二维码可以进入 profile，但必须先问用户保存还是仅本期；主题、演讲、当期角色、临时地点和特殊环节永远不进入 profile。
- 经过授权公开的 profile 可以随 Skill 内置。读取顺序为：用户本地 profile → Skill 内置公开 profile → 当前输入初始化；无论来源如何，本期明确事实优先。

## 最小结构

```json
{
  "club": {
    "name": "Example Toastmasters Club",
    "default_location": "Meeting Room",
    "language": "zh"
  },
  "meeting": {
    "number": "12",
    "date": "2026-09-01",
    "start": "19:30",
    "end": "21:30",
    "location": "Meeting Room",
    "manager": "Member A",
    "president": "Member B"
  },
  "roles": [],
  "prepared_speeches": [],
  "impromptu": null,
  "backstage": [],
  "special_segments": [],
  "agenda_overrides": []
}
```

`club.language` 可为：

- `zh`：中文；
- `en`：英文；
- `bilingual`：中英双语。

使用已保存的 `--club-profile` 时，`club` 中已有的稳定字段可以省略。`meeting.location`、本期语言或其他本期明确内容始终优先。

`meeting.end` 可省略，程序默认会议总长 120 分钟。使用 `simple_version: 1` 时，不得在 JSON 中填写 `meeting.approved_overtime_minutes`。

## 超时必须二次确认

第一次正常运行 `confirm`，不要带任何超时确认：

```bash
python3 "$SKILL_DIR/scripts/run_agenda.py" confirm meeting.json \
  --club-profile "俱乐部完整名称" --output-dir output
```

如果程序返回 `overtime_confirmation_required`，向用户明确说明程序算出的准确超时分钟数和预计结束时间，然后停止本轮；不要自行批准，也不要通过修改 `meeting.end` 规避确认。

只有用户在下一条消息中明确同意该准确分钟数后，才第二次运行 `confirm`：

```bash
python3 "$SKILL_DIR/scripts/run_agenda.py" confirm meeting.json \
  --club-profile "俱乐部完整名称" --output-dir output \
  --confirm-overtime-minutes 11
```

参数值必须与程序本次返回的超时分钟数完全一致。错误分钟数、没有实际超时却提供确认，以及 JSON 内预填批准字段，都会被拒绝。用户不同意超时时，先调整内容或时长，再重新运行不带确认参数的 `confirm`。

用户确认后，后续对同一会单做内容修改并再次运行 `confirm` 时继续使用相同的 `--confirm-overtime-minutes N`；如果内容变化导致准确超时分钟改变，程序会拒绝旧值，此时再向用户确认新分钟数。

## 角色、演讲与即兴

角色格式：

```json
{"id": "timer", "person": "Member C"}
```

常用角色 ID：

| ID | 角色 |
|---|---|
| `rules_host` | 会议规则负责人 |
| `toastmaster` | Toastmaster / 主持人 |
| `timer` | 时间官 |
| `ah_counter` | 哼哈官 |
| `grammarian` | 语法官 |
| `guest_host` | 嘉宾介绍负责人 |
| `sharing_host` | 分享环节负责人 |
| `general_evaluator` | 总点评 |
| `awards_host` | 颁奖负责人 |

角色不存在表示本期没有该角色；角色存在但 `person: null` 表示需要询问负责人。不要用 `Toastmaster`、`主持人`、`待定` 等角色称呼冒充姓名。

`rules_host` 就是本俱乐部所称的规则介绍、事务官开场或同类环节，不要再重复新增一个开场环节。

备稿演讲与点评放在同一对象：

```json
{
  "speaker": "Member D",
  "title": "My First Step",
  "project": "PM L1 Ice Breaker",
  "minutes": 6,
  "evaluator": "Member E",
  "evaluation_minutes": 3
}
```

普通备稿未给时长时由程序采用默认值。点评默认存在；只有用户明确取消时写 `"evaluation_enabled": false`。需要点评但人选未知时写 `"evaluator": null`。

即兴格式：

```json
{
  "impromptu": {
    "host": "Member F",
    "minutes": 15,
    "evaluator": "Member G",
    "evaluation_minutes": 7
  }
}
```

`impromptu` 省略或为 `null` 表示本期没有即兴。保留即兴时，`minutes` 每期必填；提供 `evaluator` 时，`evaluation_minutes` 也必填。`evaluator` 省略表示本期没有即兴点评；`evaluator: null` 表示需要点评但人选未知。程序不得从 profile、常见时长或会议剩余时间推算这两项。

## 幕后团队和特殊环节

幕后角色不单独生成台前环节：

```json
{"backstage": [{"id": "photographer", "person": "Member H", "label": "Photographer"}]}
```

常用 ID 为 `photographer`、`slides`、`voting`，也可保留接龙中的其他 ID 与显示名称。

特殊环节必须同时具有标题、真实负责人、时长和相对位置：

```json
{
  "special_segments": [
    {
      "title": "AI Workshop",
      "owner": "Member I",
      "minutes": 20,
      "after": "guest_introduction",
      "details": ["Demo", "Practice", "Review"]
    }
  ]
}
```

`after` 使用另一个真实环节的稳定 ID，例如 `guest_introduction`、`prepared_speech:1`、`table_topics`、`table_topics_evaluation`、`photo_break`、`prepared_evaluation:1`、`sharing`。不要按经验选择位置。

## 本期内容修改

修改角色、演讲或特殊环节时，优先直接改对应对象。修改已经生成的普通环节，用 `agenda_overrides`：

```json
{
  "agenda_overrides": [
    {"id": "general_evaluation", "minutes": 10},
    {"id": "photo_break", "label": "Group Photo + Break", "minutes": 8},
    {"id": "table_topics_evaluation", "after": "table_topics", "section": "first_half"},
    {"id": "ah_counter_intro", "enabled": false},
    {"id": "prepared_evaluation:1", "owner": "Member J", "transition_after": 0.5}
  ]
}
```

合影休息和真情分享没有提供时长时，信息确认阶段固定提议两项各 10 分钟，并等待用户确认。确认后显式写入：

```json
{
  "agenda_overrides": [
    {"id": "photo_break", "minutes": 10},
    {"id": "sharing", "minutes": 10}
  ]
}
```

用户未确认时程序必须返回缺项，不得根据会议剩余时间自动伸缩这两个环节。已取消的环节无需确认时长。

支持字段为 `id`、`minutes`、`owner`、`label`、`enabled`、`transition_after`、`after` 和 `section`。`section` 只在用户明确跨阶段移动时使用，可为 `opening`、`first_half`、`second_half`、`closing`。

不要填写任何环节的 `start` 或 `end`；程序会按新顺序重新计算。

调整顺序时必须保持这些关系：

- 每个 `prepared_evaluation:N` 都在对应的 `prepared_speech:N` 之后；
- `table_topics_evaluation` 在 `table_topics` 之后；
- `general_evaluation` 和 `sharing` 都留在 `closing` 收尾区，并位于所有主菜和反馈环节之后；
- `general_evaluation` 与 `sharing` 的先后可以按用户需要互换。

不符合这些关系的移动会被程序拒绝，并保留原顺序。

## 可选辅助信息

辅助信息未提供时由程序先使用 profile；仍未提供时只自动采用时间官规则、头马介绍和会议边界。如果 profile 中已有完整七人官员团队，再自动加入官员信息。Agent 不要自行拼装这组默认值。`join_info` 只能使用俱乐部或用户确认过的真实内容，绝不生成通用占位话术；用户明确选择它但资料为空时，必须返回缺项。用户明确只要纯议程时写空数组：

```json
{"meeting": {"support_components": []}}
```

可选组件 ID：`timer_rules`、`toastmasters_intro`、`meeting_boundaries`、`officers`、`club_intro`、`join_info`、`vpm_qr`、`voting_qr`。

- `club.officers`：`[{"role": "President", "name": "Member A"}]`
- `club.club_intro`、`club.join_info`：字符串数组
- `club.vpm_qr_image`、`meeting.voting_qr_image`：用户提供的二维码图片路径
- `participant_pathways`：`{"Member D": "PM L1"}`；只填写用户提供的真实进展
- `custom_support_blocks`：`[{"id": "pathways", "title": "Pathways", "lines": ["PM - Presentation Mastery"]}]`

## 视觉修改

视觉修改写入局部 `view.patch.json`，不要复制会单事实：

```json
{"design": {"text_scale": "large"}}
```

允许字段：

- `design.text_scale`：`standard` 或 `large`
- `design.contrast`：`soft` 或 `clear`
- `density`：`comfortable`、`balanced` 或 `compact`
- `content_emphasis`：`null`，或 `{"item_id": "special:1", "strength": "subtle|clear"}`
- `display_columns`：完整列数组；必须包含并按顺序使用 `time`、`activity`、`owner`、可选真实辅助列、`duration`
- `component_flow.operations` / `component_flow.background`：可以只改其中一组；提供的数组会整组替换，所有真实辅助组件最终必须各出现一次

不要在视觉 patch 中写人名、正文、时间、时长、模板、左右位置、尺寸、HTML 或 CSS。

显式 patch 成功后会保存到输出目录，后续 `image` 会自动沿用。用户要求恢复默认时，移除保存的 patch 后再运行 `image`。

## 长期资料更新

只有用户明确说“以后默认都这样”时，才在 `confirm` 中增加 `--update-club-profile`。本期角色、日期、会议号、特殊环节、临时时长和本期顺序永远不写入 profile。

`confirm` 成功后读取 `profile.status`：

- `created` / `updated`：转达 `profile.user_message`，明确告诉用户真正保存了哪些长期资料，以及下次不必重复提供什么；
- `reused`：只说明沿用了已有资料，不能声称刚刚保存了新内容；
- `bundled`：说明使用了 Skill 内置公开资料，不能声称写入了用户本机；
- `not_used`：不提 profile。
