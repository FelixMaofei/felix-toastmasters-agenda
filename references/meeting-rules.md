# Mingyuan Yun Toastmasters Agenda Rules

## Role Signup Parsing

Parse lines like `emoji + role + colon + person`.

- `📝事务官：范范` -> 事务官 = 范范
- `⏱时间官：🌺` -> 时间官 unresolved
- `👉🏻场控（PPT）：毛斐` -> backstage role, not timeline role
- `🏆投票链接修改：宗一` -> backstage role
- `🎤讲师：考拉` + `📌主题：从MBTI认识自己` -> workshop speaker and topic
- `🌿工作坊《一场关于你体质密码的解读》主讲：考拉（约40分钟）` -> workshop title, speaker = 考拉, duration = about 40 min
- `🎖新干事上任仪式：栎菲` -> special segment, owner = 栎菲, duration unresolved until supplied or explicitly planned
- `A&B` or `A & B` -> split people if the role naturally supports multiple people
- Text in `《...》` -> speech title
- Path/project text after a speech title -> Pathways project when present
- Normalize any role containing `主席` to `会长`; this club uses `会长`, not `主席`.
- If a role is blank, marked `🌺`, `待定`, `招募中`, or `？`, keep it unresolved instead of dropping it.
- Explicit values in the current user message override the role signup for agenda content, but a name supplied outside the relay is not automatically proof of signup consent. Before Gate 1, confirm whether that person has agreed; otherwise keep the role unresolved.

Common backstage roles:

- 拍照官
- 场控（PPT）
- 投票链接修改
- 打印/物料/签到/直播回放 when present

## Required Checks

Ask only for missing information that changes the agenda materially:

- Is there AI领航?
- Is there a workshop/special segment? What duration?
- How long should impromptu speeches and impromptu evaluation be, unless the user asks the agent to plan them?
- Guest introduction duration if not using the default 5 minutes
- Meeting manager if not provided
- Any missing functionary whose declaration/report is present in the proposed flow
- Guest-introduction host/owner whenever guest introduction is present
- Sharing host/facilitator whenever Sharing is present
- Missing prepared speech titles/path only when prepared speeches exist

Do not block the agenda on guest names or home clubs unless they will be printed. Guest count matters when it makes the default introduction duration unrealistic.

Do not infer guest-introduction or Sharing ownership from 事务官、会议经理、时间官、总主持、会长, or another role. If either role is missing from the relay, ask the user and keep it `待确认` until the named person has been confirmed.

The closing speaker defaults to the same person as the president speech. An explicit closing-speaker assignment overrides this default. This is the only standing owner default.

## Defaults

- Date: an explicit meeting date wins. Otherwise use base `第229期 = 2026-05-20`; add 7 days per issue number and label it as inferred until confirmed.
- Start/end: formal meeting `19:30-21:30`; entry is the separate pre-meeting period `19:00-19:30` and does not consume the 120-minute formal meeting budget.
- Location: `金地威新中心A座 6F 洱海会议室`. The exact room name is `洱海`, never `沿海`.
- Guest introduction: 5 min. This is a duration default only; the host must be signed up or confirmed.
- Break: 5 min.
- Rule intro: 2 min.
- President speech: 3 min.
- Toastmaster opening: 2 min.
- Timer declaration: 2 min.
- Ah-counter declaration: 2 min.
- Prepared speech: 7 min; icebreaker 6 min.
- Prepared speech evaluation: 3 min.
- Officer reports: 3 min each.
- General evaluation: 8 min; do not compress without explicit confirmation.
- Awards: 3 min.
- Closing: 3 min; do not compress without explicit confirmation.
- Transition: add 1 minute between most major segments. Exceptions: entry -> rules, rules -> president speech, president speech -> Toastmaster opening, and after break.

## Timeline Validation

- Support `0-N` prepared speeches and bind prepared speech `N` to prepared speech evaluation `N`.
- Recalculate every downstream timestamp after any change; never patch only the edited row.
- Validate order, segment duration, transition count, and final end time together.
- `Sharing` may absorb remaining time only when the residual is positive and operationally usable. This rule sets duration, not ownership; the facilitator must be signed up or confirmed. If the plan cannot fit, report the conflict and request a tradeoff rather than outputting a negative duration or silently shortening a locked segment.
- Special segments such as workshops, officer installations, certificates, or ceremonies require an owner, duration, and explicit position in the flow.

## Signup Status vs Actual Execution

- `接龙报名`: the person volunteered or was entered in the role-signup relay.
- `已确认安排`: the person did not appear in the relay, but the user explicitly confirms they have agreed.
- `待确认`: a tentative name exists, but consent has not been confirmed. Do not pass Gate 1 with this status.
- `现场临时承担（非接龙报名）`: the person actually performed the role on site without having signed up beforehand.
- A post-meeting report may name the actual performer, but must not convert actual execution into a signup record.

## Default Flow

Opening:

1. Rules introduction
2. President speech
3. Toastmaster opening
4. Timer declaration
5. Ah-counter declaration
6. Guest introduction + group photo

Upper half:

1. Optional AI lead / workshop / special segment
2. Prepared speeches if any
3. Impromptu speeches
4. Break

Lower half:

1. Prepared speech evaluations if any
2. Impromptu evaluation
3. Ah-counter report
4. Timer report
5. Sharing
6. General evaluation
7. Awards
8. Closing

## Fixed Content

Toastmasters International:

头马国际演讲会成立于1924年的美国加州，是致力于提升会员沟通力、演讲力、领导力的全球性非盈利教育组织，目前已遍布全球150个国家，共14000+俱乐部，成功帮助了270000+位会员。

Pathways:

- DL: 动态领导 / Dynamic Leadership
- MS: 激励策略 / Motivational Strategies
- PI: 有说服力的影响 / Persuasive Influence
- PM: 精通演讲 / Presentation Mastery
- VC: 愿景沟通 / Visionary Communication
- EH: 运用幽默 / Engaging Humor

Mingyuan Yun Toastmasters Club:

- 定位：一个让你练好表达、用好AI的实践成长平台
- 使命：我们提供互助互益的学习体验，帮会员提高沟通表达与公众演讲能力，更会用AI也更自信
- 愿景：让每个会员都成为更会表达、更会用AI的人，收获实实在在的自信与成长
- 口号：明星闪耀，源来是你！
- 关键词：有成长、有温暖、有乐趣
- 价值观：正直、尊重、服务、卓越

Current officers (11.0 term, verified 2026-07-15 from the user-provided officer announcement and 2026-07-04 officer meeting notes):

- President: 毛斐
- VPE: 黎耀棠（耀棠）
- VPM: 毛斐
- VPPR: 金晶
- Secretary: 源仔
- Treasurer: 彭宗一（宗一）
- SAA: 魏真（考拉）

Member / Pathways reference:

- Optional local workbook: `data/member-info.xlsx` relative to the Skill root.
- Sheet: `会员信息`. Match members by `昵称` first, then `英文名` or `会员编号` when needed.
- This package intentionally contains no member workbook or private member data. If the file is absent, unreadable, or ambiguous, ask the user for the current path/project information.
- Do not fetch a member database from Notion or another online source unless the user explicitly asks and authorizes that separate action.
- Use the local workbook only for nickname/full-name matching, Pathways path, and level suggestions. Do not treat its imported `状态` or old `角色/简介` field as official current-term truth.
- A member's saved path/level is a suggestion, not proof of the current speech project. Prefer an explicit project supplied for the meeting.

Timer rules:

- Short speech <= 3 min: green with 1 min left; yellow with 30 sec left; red at time; ring after 15 sec overtime.
- Medium speech > 3 min and <= 10 min: green with 2 min left; yellow with 1 min left; red at time; ring after 30 sec overtime.
- Long speech > 10 min: green with 5 min left; yellow with 2 min left; red at time; ring after 30 sec overtime.

Guest participation:

- Guest intro: 30 sec self-introduction
- Impromptu speech: 2 min topic speech
- Sharing: 1 min feeling/learning

Reminders:

- 安静：会议过程请保持安静，并将手机调至静音或震动状态。
- 纯净：演讲不得涉及政治、宗教、色情及传销等话题。
- 干净：会议结束后请带走个人物品与随身垃圾。
