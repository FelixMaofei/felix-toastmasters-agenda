---
name: felix-toastmasters-agenda
description: 将 Toastmasters 角色接龙、会议说明或旧会单参考，转成内容准确、时间闭合、符合官方品牌规范的中英双语会单。适用于各俱乐部的例会议程、角色接龙转会单、Toastmasters agenda、时间重算、A4 打印版和线上分享版；不复刻各俱乐部旧样式。
---

# Felix Toastmasters Agenda

## 核心价值

> **继承稳定内容，识别本期变化，自动完成加减计算，让整场会议重新闭合。**

输入是本期角色接龙、会议说明或可选旧会单；输出是内容准确、时间闭合、可现场执行的一页 A4 会单。不复刻旧样式，不把单一俱乐部的流程当成通用标准。

## 轻量初始化与日常使用

用户的最短入口可以只是：“帮我把这份角色接龙做成会单。”不要先要求旧会单、JSON 或技术配置。

1. 先检查当前消息、附件及文件名，主动识别已有事实。
2. 再检查固定本机资料库 `~/.toastmasters-agenda/profiles/`。只用规范化后的俱乐部名称识别并继承 profile；地点只能辅助提示，不能单独确认俱乐部。
3. 没有 profile 时仍继续。旧会单有就利用，没有不影响初始化。
4. 只把无法判定、且影响成品的缺失信息合并成一次短询问。先说已识别出什么，再问尚缺项；不暴露字段名。
5. 固定信息未选择时，用人话问：“常用四项（时间官规则、头马介绍、四类禁忌、官员团队）、纯议程，还是自选？”推荐不等于自动加入，不得擅自写 `[]`。
6. 首次稳定信息确认后创建俱乐部 profile。用户明确长期修改默认地点、语言、组件、官员、介绍、入会信息、VPM 二维码或自定义块时才更新；官方俱乐部名称变更时按新名称创建新 profile。本期变化不覆盖 profile。

详细的字段、空值语义、组件选择和 profile 命令见 [输入结构](references/input-schema.md)。

## 默认工作流

1. 读取 [输入结构](references/input-schema.md)，从当前材料生成只包含本期事实的 meeting JSON。保留接龙顺序，不手写完整时间轴、开始时间或转场。
2. 本期存在特殊环节、默认规则冲突、超时或生成器报错时，再读 [会单业务与时间规则](references/agenda-rules.md)。
3. Skill 加载时会显示 Base directory。将它作为 `SKILL_DIR`，用绝对路径运行生成器：

   ```bash
   python3 "$SKILL_DIR/scripts/build_agenda.py" meeting.json --club-profile "俱乐部完整名称" --output-dir output
   ```

   同名 profile 不存在时，生成成功后自动创建；日常 meeting JSON 可以省略整个 `club`。用户明确要长期改变某个字段时，把新值写入 `club.<field>` 并加 `--update-club-profile`；`meeting.*` 仍只表示本期变化。
4. 退出码为 `2` 时，只根据错误中的缺失负责人、冲突、剩余或超时分钟处理；不猜测修复，不绕过阻断。
5. 退出码为 `0` 时，先向用户展示 `agenda.md` 确认姓名、顺序、时长和地点。
6. 文字确认后读取 [版式路由与主题视觉系统](references/visual-system.md)。默认让程序选择 `standard`、`feature` 或 `marathon`，不为显得智能而追问。
7. 若主题确实需要更强艺术表达，可在文字确认后生成一张无文字、无 Logo、无二维码的主题图，写入 `meeting.theme_image` 并重新运行生成器。
8. 用同一 HTML 导出打印和分享成品：

   ```bash
   python3 "$SKILL_DIR/scripts/export_a4.py" output/agenda.html --output-dir output
   ```

## 绝不能破的不变项

- 姓名已填入本期接龙就代表本期承诺，不再审问是否同意。
- 本期明确事实优先于 profile 和通用默认；图像、版式和主题层不得改写事实。
- 角色行不存在就不生成该角色触发环节；幕后角色不自动创造台前环节。
- 备稿演讲与点评按编号绑定。默认需要点评；只有本期明确取消才设置 `evaluation_enabled: false`。
- 最终文字、HTML、PDF 和 PNG 必须来自同一份计算后 JSON，不用图片模型重排密集文字。
- 最终 PDF 必须且只能是 1 页 A4 竖版。不跨页、不裁切、不隐藏，不缩成无法现场阅读的小字。
- 只使用 Toastmasters International 官方 Logo / Wordmark / Logo Lockup；不重设、不改色、不拉伸、不加特效。
- 最终成品不包含提示词、内部判断、缺失项、历史文字或制作过程备注。

## 执行纪律

- `build_agenda.py` 和 `export_a4.py` 是确定性程序，普通任务直接运行。只有出现 traceback、无法执行或输出结构损坏时才检查源码或测试。
- 不在程序前后手算整场时间，不用模型计算覆盖 `agenda.computed.json`。
- `export_a4.py` 因第 2 页退出 `2` 时，说明单页容量冲突并请用户精简议程行、介绍文字或固定组件；不绕过导出器。
- 必须先看当前消息和附件，不因初始化扩张搜索无关历史、会员库或网络。用户明确选定后停止继续改版。
