# Felix Toastmasters Agenda V4

把 Toastmasters 角色接龙和本期变化，直接做成内容准确、时间闭合的一页 A4 会单。

> 继承稳定内容，识别本期变化，自动完成加减计算，让整场会议重新闭合。

支持中文、英文和中英双语，生成 PNG 与 PDF。

## 使用方式

把角色接龙、会议说明、截图或本期变化发给已安装 Skill 的 AI，说：

> 帮我把这份角色接龙做成会单。

它会先说明已经识别的内容；只有影响负责人、流程或时间闭合的信息缺失时，才一次问清。信息齐全后直接给 A4 图片初版，不要求你审批 Markdown 或配置模板。

看图后可以直接说：

- “总点评改成 10 分钟”
- “字大一点”
- “把工作坊放到嘉宾介绍后面”
- “直接导出”

最后一种会原样交付你已经看到的 PDF 和 PNG，不重新排版。

## 安装 V4

推荐从 [V4 Release](https://github.com/FelixMaofei/felix-toastmasters-agenda/releases/tag/v4.0.0) 下载 `felix-toastmasters-agenda-local.zip`，解压到 Skills 目录。这个 ZIP 只有运行所需的 Skill、程序、官方 Logo 和离线字体；不包含测试、架构说明和历史资料。

不会安装时，把 Release 链接发给你的 AI，并说：

> 请安装这个会单 Skill，安装后告诉我已经可以使用。

手动安装示例：

```bash
# Codex
unzip ~/Downloads/felix-toastmasters-agenda-local.zip -d ~/.agents/skills

# WorkBuddy
unzip ~/Downloads/felix-toastmasters-agenda-local.zip -d ~/.workbuddy/skills
```

安装后重新打开 AI 对话，再发角色接龙即可。

## 本地俱乐部资料

第一次使用某个俱乐部时，Skill 可以根据已确认资料建立本机 profile，保存俱乐部名称、语言、固定信息和授权素材。以后每期只提供角色与变化即可。

本期明确事实永远优先于 profile：例如本期地点、特殊工作坊、临时时长和负责人会覆盖旧资料，但不会自动改成以后默认。俱乐部资料和自有 Logo 都保存在本机，不需要联网；只有 Toastmasters 官方 Logo 随 V4 运行包提供。

## 维护与验证

本仓库保留源码、匿名样例和测试；普通安装请使用 Release 的精简运行包。开发后运行：

```bash
python3 -m unittest discover -s tests
python3 scripts/package_local.py --output-dir ../agenda-package-build --force
```

V4 的 `first` 一次生成预览 PNG/PDF；`final` 只交付已预览的同一版文件。
