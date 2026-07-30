# 明源云头马会单 Skill

这是一个可分享、可安装的 Codex Skill，用于把微信群里的中文角色接龙快速整理成准确的明源云头马例会会单，并生成 A4 会单图。

## 它能做什么

1. 解析角色接龙、主题、今日一词、会议经理和特殊环节。
2. 区分“接龙报名、已确认安排、待确认、现场临时承担”。
3. 对缺失角色和影响流程的信息先追问，不擅自安排兼任。
4. 自动计算完整时间轴，并先输出 Markdown 文字版供确认。
5. 文字确认后生成一张 A4 竖版会单图，并逐项校对。
6. 图像生成不稳定时，可使用附带的 HTML 模板和 PDF 脚本兜底。

## 安装

### 从 GitHub 安装

安装到当前用户：

```bash
git clone https://github.com/FelixMaofei/mingyuan-toastmasters-agenda.git ~/.codex/skills/mingyuan-toastmasters-agenda
```

安装到单个项目：

```bash
git clone https://github.com/FelixMaofei/mingyuan-toastmasters-agenda.git .agents/skills/mingyuan-toastmasters-agenda
```

### 安装到单个项目

把整个 `mingyuan-toastmasters-agenda` 文件夹复制到项目的：

```text
.agents/skills/mingyuan-toastmasters-agenda
```

### 安装到当前用户

把整个文件夹复制到：

```text
~/.codex/skills/mingyuan-toastmasters-agenda
```

安装后重新打开相关 Codex 任务，确保 Skill 被识别。

## 使用方式

在 Codex 中发送：

```text
用 $mingyuan-toastmasters-agenda 把下面角色接龙做成会单：

（粘贴角色接龙）
```

推荐工作流：

```text
解析接龙 → 追问缺口 → 确认完整 Markdown → 生成 1 张 A4 图 → 文字与版式 QA → 可选导出 PDF
```

## 会员数据

分享包不包含任何会员库、Notion 页面、API 凭据或个人本机路径。

如需自动匹配会员昵称和 Pathways 信息，可自行创建：

```text
data/member-info.xlsx
```

工作表名称应为 `会员信息`。建议至少包含 `昵称`、`英文名`、`会员编号`、`路径`、`等级` 等字段。若文件不存在，Skill 会直接向用户确认，不会联网搜索或猜测。

## 图像与模板

- `assets/agenda-reference-good.png`：信息架构参考。
- `assets/agenda-a4-health-reference.png`：A4 健康主题视觉参考。
- `assets/agenda-template.html`：可编辑 HTML 兜底模板，内含示例会议信息；每次使用必须替换全部期次、人员、时间和流程文字。
- `assets/toastmasters-transparent.png`：Toastmasters 透明 Logo 资产。

参考图只用于视觉方向，不能复制其中旧会议的日期、地点、人员或流程。

## PDF 脚本

`scripts/make_a4_print_pdf.py` 可把最终 PNG 转为单页 A4 PDF。

依赖：

```text
Python 3
Pillow
```

示例：

```bash
python3 scripts/make_a4_print_pdf.py agenda.png agenda.pdf
```

## 重要规则

- 会单制作先把会议流程聊清楚，再做图。
- 接龙不全必须追问；不要自动安排别人兼任。
- 嘉宾介绍负责人、真情分享负责人是独立报名角色。
- 只有闭幕致辞负责人可默认与会长致辞相同。
- 用户确认某张图后，保存那一张并停止，不擅自换成后续版本。
- 默认会议室为 `金地威新中心A座 6F 洱海会议室`，注意是“洱海”。

## 一起迭代

欢迎通过 GitHub Issue 提交问题、会单案例和规则建议，也欢迎通过 Pull Request 改进：

- 角色接龙解析规则
- 时间轴计算与校验
- 固定内容维护
- GPT Image 提示与文字 QA
- A4 模板与 PDF 输出

提交真实会议案例前，请先删除会员联系方式、内部链接、凭据及其他非必要个人信息。

## 隐私与商标

- 仓库不包含会员库、Notion 页面、API 凭据或个人本机路径。
- `data/` 默认被 Git 忽略，会员数据不得提交到公开仓库。
- Toastmasters International 的名称与标识属于其各自权利人；仓库中的相关素材仅用于制作俱乐部会单，不代表 Toastmasters International 官方背书。

版本：1.0.0
