# V3 `agenda.view.json` 视觉意图

状态：V3 内部合同已固化为代码 Schema，并通过普通、重点和英文密集三份视觉基线。

## 1. 它是什么

`agenda.view.json` 是“信息意义”与“确定性排版”之间的语义合同。

- `first` 先按真实内容生成保守默认值；AI 只在用户反馈或明确重点时调整强调、显示列与辅助内容顺序；
- renderer 负责决定：实际列宽、位置、字号、间距、自然高度和对齐；
- 用户不填写，也不需要看到它。

它不是第四个用户层，不是模板路由，也不是页面配置文件。

主议程永远是现场第一使用重点，这条由 renderer 固定，不让 AI 每期重新选择。

## 2. 最小结构

```json
{
  "view_version": 1,
  "content_emphasis": {
    "item_id": "special:1",
    "strength": "clear"
  },
  "display_columns": [
    "time",
    "activity",
    "owner",
    "pathways",
    "duration"
  ],
  "component_flow": {
    "operations": [
      "backstage",
      "timer_rules",
      "officers"
    ],
    "background": [
      "toastmasters_intro",
      "meeting_boundaries",
      "club_intro"
    ]
  },
  "density": "compact",
  "design": {
    "text_scale": "large",
    "contrast": "clear"
  }
}
```

## 3. 字段合同

### `view_version`

- 当前固定为 `1`。

### `content_emphasis`

- 可以是 `null`，或只强调一个已存在环节；
- `item_id` 必须来自 `agenda.computed.json`；
- `strength` 只允许 `subtle` 或 `clear`；
- 不因时长长自动生成；
- 只允许改变字号、字重和有限颜色，不允许改变组件面积。

### `display_columns`

- 固定顺序为 `time → activity → owner → 可选辅助列 → duration`；
- `time`、`activity`、`owner`、`duration` 必须存在；
- `pathways` 等辅助列只有计算真源存在真实数据时才能加入；
- AI 只能决定显示哪些列，不能决定列宽和对齐方式。

### `component_flow`

- `operations`：现场需要查阅的辅助信息，例如幕后、时间官规则、官员团队；
- `background`：头马介绍、会议边界、俱乐部介绍等背景资料；
- 每个已确认组件必须恰好出现一次，不能漏、不能重复；
- 数组顺序表示同组内阅读顺序；
- 它不代表左栏、右栏或底部，物理位置由 renderer 根据真实尺寸决定。

### `density`

- 只允许 `comfortable`、`balanced`、`compact`；
- 只调整行间距和组件间距；
- 不改变字号，不提供“小字塞满”选项。

### `design`

- `text_scale`：`standard` 或 `large`；
- `contrast`：`soft` 或 `clear`；
- 所有结果仍须符合 Toastmasters 品牌色和最低字号。

## 4. 三份压力样本

### 普通例会

```json
{
  "view_version": 1,
  "content_emphasis": null,
  "display_columns": ["time", "activity", "owner", "duration"],
  "component_flow": {
    "operations": ["backstage", "timer_rules", "officers"],
    "background": ["toastmasters_intro", "meeting_boundaries"]
  },
  "density": "balanced",
  "design": {"text_scale": "standard", "contrast": "clear"}
}
```

普通例会不制造主视觉，重点就是清楚可扫的完整议程。

### 60 分钟重点环节＋Pathways＋长介绍

```json
{
  "view_version": 1,
  "content_emphasis": {"item_id": "special:1", "strength": "clear"},
  "display_columns": ["time", "activity", "owner", "pathways", "duration"],
  "component_flow": {
    "operations": ["backstage", "timer_rules", "officers"],
    "background": ["toastmasters_intro", "meeting_boundaries", "club_intro"]
  },
  "density": "compact",
  "design": {"text_scale": "large", "contrast": "clear"}
}
```

60 分钟只是一项时间事实，renderer 不得按 60 分钟分配面积。

### 角色密集／英文会单

```json
{
  "view_version": 1,
  "content_emphasis": null,
  "display_columns": ["time", "activity", "owner", "duration"],
  "component_flow": {
    "operations": ["backstage", "timer_rules", "officers"],
    "background": ["toastmasters_intro", "meeting_boundaries"]
  },
  "density": "compact",
  "design": {"text_scale": "standard", "contrast": "clear"}
}
```

英文是内容语言，不是视觉模板，因此 view 中没有 `english` 版式路由。

## 5. 禁止字段

`agenda.view.json` 不得出现：

- `layout`、`standard`、`feature`、`marathon`、`template`、`renderer`、`mode`；
- `visual_theme`、自动主题名和默认主题插图；
- `left`、`right`、`bottom`、`sidebar`、`grid_area` 等物理位置；
- 坐标、宽高、列宽、行高、比例、面积、边距和像素值；
- HTML、CSS、class、style、字体名、颜色值、边框和渐变；
- `grow`、`weight`、`duration_ratio`、`fill_height`；
- `visible`、`hidden`、`max_lines`、`truncate`、`overflow`；
- `zoom`、`scale`、`fit_to_page`；
- 标题、人名、时间、时长和介绍正文等重复事实；
- `design_prompt`、任意备注和自由设计指令；
- 任意列宽、负责人对齐方式和组件高度。

## 6. 判断纪律

改 view：

- 重点判断错了；
- 显示列错了；
- 运营 / 背景信息分类或顺序错了；
- 用户要整体字大一点、对比更清楚。

改 renderer：

- 没有对齐；
- 有组件内部死空白；
- 卡片被强行拉高；
- 列宽难看；
- 职务与姓名离得过远；
- 最低字号仍看不清。

排不齐和死空白永远不是“再给 view 增加一个字段”的理由。
