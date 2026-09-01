# 自然语言与受控执行工作流

适用 WorkBuddy、Codex 和其他能执行本地命令的 Agent。模型负责理解用户、映射本期变化和提出可操作方案；程序负责时间计算、A4 适配和最终验证。不因模型不同而预设它只能做机械提取。

Skill 已内置 Logo、图标、主题纹理和可合法分发的中英文字体。准备和导出全程不需联网，也不需本地模型改 CSS。

## 首轮先问，不执行

首次材料里只要会单语言、固定信息选择或已出现环节的真实负责人有一项未确认，就用一条普通文字消息合并询问并结束当前轮次。不要调用 `AskUserQuestion`，不要先运行命令或创建文件；当前 Agent 没有专用提问工具也不能自行选择默认值、取消环节或继续生成。面向用户只展示已识别事实和缺项，不解释内部“阻断门”。

## 绝对不要做

- 不要求用户自己写 JSON；
- 不要求每期提供旧会单；
- 不要手算开始时间、结束时间、转场或剩余分钟；
- 不要修改 `agenda.computed.json` 或已安装 Skill 的模板；用户要求的本期视觉优化先用 `visual_preferences`，必要时只修改输出目录中的 HTML 副本并重新验证；
- 不要联网找图、换图标、调色或另做一张图；
- 不要跳过 `finalize`的视觉审计直接打印。
- 不要用 `find ~` 或其他宽泛搜索寻找 Skill、profile 或历史会单；
- 正常工作先执行 `scripts/run_agenda.py`；只有出现 traceback、无法执行或用户明确要求维护 Skill 时才检查源码。
- 当前消息已经明显缺负责人、语言或固定信息选择时，先合并问用户；不要先列 Skill 目录、读源码或运行环境检查。

## 先确定 Skill 目录

- WorkBuddy 默认直接使用 `~/.workbuddy/skills/felix-toastmasters-agenda`；
- 路径不存在时，再使用当前平台加载 Skill 时显示的 Base directory；
- 不向用户询问安装路径，不搜索整个主目录。
- Skill 工具已经返回 Base directory 时直接使用，不再 `ls` 或遍历目录。

## 第 0 步：事实齐全后，只检查一次环境

```bash
python3 "$SKILL_DIR/scripts/run_agenda.py" doctor
```

返回 `ok: true` 就继续。如果缺 Chrome/Chromium，用人话说明“会单内容可以先完成，但当前电脑暂时不能导出 PDF/PNG”，保留已生成 HTML，再给出一个最短的环境处理建议。

## 第 1 步：从当前消息提取本期事实

先看用户当前粘贴的角色接龙、会议说明和附件。已出现的信息不再问。

只生成 `meeting.json`，主要是：

- `meeting`：期数、日期、正式开始/结束、本期地点、主题、今日一词、会议经理、会长；
- `roles`：接龙中真实出现的功能角色，保留顺序；
- `prepared_speeches`：每篇将演讲者、题目、时长、同编号点评人放在同一对象；
- `impromptu`：即兴主持、即兴点评人；用户没给时长就保留 `null`；
- `backstage`：拍照、场控/PPT、投票链接等，不进时间轴；
- `special_segments`：工作坊、微课等本期特殊环节，必须有负责人、时长和相对位置。

特殊环节负责人必须是真实姓名；不能把“Toastmaster”“主持人”“待定”等角色称呼当负责人。没有姓名就与其他缺项一起问。

接龙明确写出的现场顺序优先。若某个自动生成环节与接龙顺序不同，用 `agenda_overrides.after` 表达“放在谁之后”，不要改源码或接受错误顺序。顺序变化默认保留原阶段；用户也明确改变阶段时才增加 `section`。

字段和空值语义不清楚时，只读 [输入结构](input-schema.md)。不预读 Python 源码或测试。

不要先手算整场时间来代替程序，也不要在第一次生成前浏览模板、视觉系统或源码。先按已知事实运行 `prepare`，只对真实返回的冲突做下一步。

## 第 2 步：准备会单

始终使用俱乐部完整名称：

```bash
python3 "$SKILL_DIR/scripts/run_agenda.py" prepare meeting.json \
  --club-profile "俱乐部完整名称" \
  --output-dir output
```

- 退出 `0`：读取 `output/agenda.md` 自检姓名、顺序、时长和地点；没有事实疑问且用户未要求只看草稿时，直接继续导出；
- 退出 `2`：只按 `errors` 中的缺失/冲突项询问，修改 `meeting.json` 后重跑；
- 不把 `warnings` 当成错误，但要把异常自动时长告诉用户。

## 第 3 步：完成导出并检查最终 A4

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
visual_audit: passed
```

`classic` 与 `editorial` 成品都必须返回 `visual_audit: passed`。随后打开最终 `agenda.png`，确认负责人列同列、无截断重叠、字号可读，才能向用户说“完成”。

## 询问原则

- 一次只合并询问真正阻断生成的缺失事实；
- “你直接做”“我不懂配置”不是语言或固定信息区选择；这两项未明确时仍给出推荐并问一次。
- 用人话问，不暴露 JSON 字段名；
- 用户说“OK”代表停止继续改版并交付当前成品，不再追问；
- 成品生成后停止，不为了“更好看”自行继续改版。
- 最终回复只交付 PDF/PNG，并用人话说明时间闭合和本轮变化；不向普通用户罗列 HTML、JSON、profile、版式代号、主题代号或制作过程。
- 只有用户明确要求长期修改且命令真实成功时，才说“已保存为以后默认”；本期 `meeting.*` 变化不能这样描述。

## 用户要求调整时

- 用户说“这一期改成……”就是对本期可逆调整的授权，不询问 CSS、JSON 或程序权限；
- 时长、负责人、名称、开关、转场和本期相对顺序写入 `agenda_overrides`；
- 整体字号、重点环节突出程度和负责人对齐方式写入 `meeting.visual_preferences`；
- 重新运行 `prepare` 后先对照上一版 `agenda.computed.json`；纯视觉反馈不得改变姓名、顺序、时长和地点，然后直接 `finalize`；
- 如果调整无法通过一页 A4，保留上一份成品，向用户给出 1-2 个业务选择，不暴露内部实现。
