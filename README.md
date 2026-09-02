# Felix Toastmasters Agenda V4.2

把 Toastmasters 角色接龙和本期变化，直接做成内容准确、时间闭合的一页 A4 会单。

> 继承稳定内容，识别本期变化，自动完成加减计算，让整场会议重新闭合。

支持中文、英文和中英双语，生成 PNG 与 PDF。

当前正式版为 V4.2。Codex、WorkBuddy 和豆包 Work 使用同一份运行包。

## 使用方式

把角色接龙、会议说明、截图或本期变化发给已安装 Skill 的 AI，说：

> 帮我把这份角色接龙做成会单。

它会先说明已经识别的内容，并通过自然的多轮沟通逐步补齐必要信息，不重复追问。信息齐全后先给完整文字会单确认稿；你确认内容后，再生成 A4 图片初版。用户不需要配置模板。

看图后可以直接说：

- “总点评改成 10 分钟”
- “字大一点”
- “把工作坊放到嘉宾介绍后面”
- “直接导出”

最后一种会原样交付你已经看到的 PDF 和 PNG，不重新排版。

## 安装 V4.2

推荐从 [V4.2 Release](https://github.com/FelixMaofei/felix-toastmasters-agenda/releases/tag/v4.2.0) 下载 `felix-toastmasters-agenda-local.zip`，解压到 Skills 目录。这个 ZIP 只有运行所需的 Skill、程序、官方 Logo、离线字体和经授权公开的内置 profile；不包含测试、架构说明和历史资料。

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

本版本还内置一份经过授权公开的明源云 AI Lab 头马俱乐部 Profile。安装后可直接继承俱乐部简介、常用地点、当前官员、入会规则和嘉宾可参与环节；本期输入仍具有最高优先级。

本期明确事实永远优先于 profile：例如本期地点、特殊工作坊、临时时长和负责人会覆盖旧资料，但不会自动改成以后默认。经过授权公开的 profile 可随 Skill 安装；其他俱乐部资料和自有 Logo 保存在用户本机。Toastmasters 官方 Logo 和离线字体随运行包提供，无需联网查找。

`profiles/` 中收录经过授权公开的明源云 AI Lab 真实 profile，并随 V4.2 统一运行包安装。`examples/mingyuan-ai-lab/` 另提供人物匿名化的完整讲解示例，包含 profile、本期输入、文字确认稿以及一页 A4 PNG/PDF。用户自己创建或修改的私有 profile 仍保存在本机，不进入 Git。

## 维护与验证

本仓库保留源码、匿名样例和测试；普通安装请使用 Release 的精简运行包。开发后运行：

```bash
python3 -m unittest discover -s tests
python3 scripts/package_local.py --output-dir ../agenda-package-build --force
```

V4.2 先用 `confirm` 生成文字确认稿，再用 `image` 把同一份已确认事实生成预览 PNG/PDF；`final` 只交付已预览的同一版文件。

## Git 收录范围

仓库收录 `SKILL.md`、Agent 元数据、当前运行程序、官方 Logo、离线字体与许可证、经过授权公开的内置 profile、输入合同、维护架构、匿名示例和测试。用户本机的私有 profile、独立验证集、历史版本、运行输出、安装目录和发布 ZIP 不进入源码仓库；ZIP 只作为 Release 附件生成。
