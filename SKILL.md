---
name: mingyuan-toastmasters-agenda
description: Create Mingyuan Yun Toastmasters meeting agenda sheets and visuals from Chinese role-signup text, including role parsing, missing-info checks, time planning, GPT Image visual generation, text QA, and HTML/PDF fallback. Use when the user asks for 会单, 例会议程, 角色接龙转会单, 明源云头马会单, Toastmasters agenda, meeting manager agenda output, or a polished agenda image/PDF for Mingyuan Yun Toastmasters Club.
---

# Mingyuan Toastmasters Agenda

## Purpose

Turn a Mingyuan Yun Toastmasters role signup into a confirmed, visually usable agenda sheet. Treat this as an operations deliverable, not a text-only answer.

## Default Fast Path

Use this sequence unless the user explicitly asks for a different workflow:

1. The user sends the role-signup relay text.
2. Parse it immediately and discuss only the missing facts that materially change the flow.
3. Recalculate the complete timeline and show one full Markdown content draft.
4. Lock the text flow with the user before doing visual work.
5. Generate one final-quality GPT Image agenda in A4 portrait ratio.
6. Check the image against the locked text. Once the user chooses a version, save that exact image and stop.

The two approval gates are:

- **Gate 1 - text flow:** roles, sequence, durations, timestamps, backstage people, fixed content, and current officers are confirmed.
- **Gate 2 - chosen image:** The user says a version is good, final, adopted, or “就这样”. That exact version becomes the deliverable; do not keep polishing it autonomously.

## Conversation Speed Rules

- Stay on the meeting flow first. Do not research templates, member data, future automation, or file organization before the flow is clear unless one of those facts is genuinely required to calculate the agenda.
- Ask the smallest useful set of questions in one compact batch. Typical material questions are: optional segments, guest-introduction retention, special-segment duration and position, impromptu duration, evaluation duration, and unresolved functionaries.
- Treat role completeness and role consent as separate checks. A person is confirmed only when they appear in the signup relay for that role, or the user explicitly says the person has agreed/been confirmed. A tentative instruction such as “先写某某” does not prove that person volunteered; ask one short confirmation question before Gate 1.
- `嘉宾介绍主持/负责人` and `真情分享主持/负责人` are independent signup roles. Never infer either one from 事务官、会议经理、时间官、总主持、会长 or another role.
- When the relay is incomplete, list the unresolved roles and ask before producing the confirmed timeline. Do not silently make someone兼任. The only standing owner default is that closing remarks use the same person as the president speech.
- When the user says “你看看还能给多少”, calculate and recommend a usable duration instead of returning the decision to them.
- Apply established time and location defaults silently. Default guest-introduction duration does not supply its host; default sharing duration does not supply its facilitator.
- Preserve explicit strings literally. For example, `拍照官：电视机` means the person/value is exactly `电视机`; never reinterpret it as blank or pending.
- If the meeting has no prepared speeches, Ah-counter, or AI lead, remove those segments cleanly instead of forcing the standard flow.
- After any insertion, deletion, reorder, or duration change, recalculate every downstream timestamp. Never patch only one row.
- Once Gate 1 is reached, stop discussing possibilities and move directly to the image.

## Workflow

1. Parse the role signup and meeting basics.
   - Extract issue number, theme, 今日一词, roles, backstage roles, workshop/speech items, hosts, evaluators, meeting manager, and closing speaker.
   - Mark `🌺`, blanks, ambiguous names, missing speech titles, or missing optional segments as unresolved.
   - For member nickname/full-name matching and Pathways suggestions, optionally read `data/member-info.xlsx` relative to this Skill, sheet `会员信息`. This package does not include member data. If the workbook is absent or the match is uncertain, ask the user instead of searching online or inventing a result.
   - Read `references/meeting-rules.md` when exact parsing, default content, or timing rules are needed.
   - Preserve signup status separately from actual execution. If someone fills a role on site without having signed up, record `现场临时承担（非接龙报名）`; do not rewrite history as if they volunteered in the relay.

2. Fill the time plan before designing.
   - Use Asia/Shanghai dates.
   - Default meeting time is `19:30-21:30`; default entry time is `19:00`.
   - Default location is `金地威新中心A座 6F 洱海会议室`. Preserve the exact room name `洱海`; do not normalize it to `沿海`.
   - If the user gives enough constraints, make a reasonable plan. If a major required duration is missing, ask only the smallest necessary question.
   - Recalculate the whole timeline after any insertion, deletion, reorder, or duration change. Validate item order, every segment duration, and the declared end time together.
   - Never emit a negative residual duration or silently compress a locked segment. If the plan cannot close by `21:30`, show the conflict and proposed tradeoff for confirmation.
   - Before final visual output, show the complete Markdown content truth and get Gate 1 confirmation. A direct instruction such as “继续做会单” after the open points are resolved counts as approval to proceed.

3. Generate the agenda content.
   - Include basic info, backstage roles, agenda timeline, timekeeper rules, officer team, Pathways, guest participation, reminders, Toastmasters intro, and club intro.
   - Do not duplicate a separate role list when all台前 roles already appear in the timeline.
   - Keep WeChat copy as plain text if the user asks for chat-ready text; use Markdown only for docs.
   - The confirmed Markdown draft is the canonical content truth for image generation. It must contain every visible field that the final agenda needs.

4. Produce a stable agenda visual.
   - Once the content is confirmed and a strong visual reference is available, use GPT Image directly for the first final-quality agenda visual. Treat dense Chinese text rendering as an empirical QA question: if the current image model has already passed a real agenda test, do not reject this route based only on generic assumptions.
   - Read `references/image-generation-workflow.md` before generating the image.
   - Use `assets/agenda-reference-good.png` as the stable information-design reference and `assets/agenda-a4-health-reference.png` as an A4 health-theme reference. Both are style references only; never copy their meeting-specific text.
   - Give image generation both: (a) an approved visual reference and (b) an A4 content-truth image containing every exact field. A verified HTML-rendered agenda PNG is useful as the content-truth reference.
   - Use A4 portrait ratio `210:297` (about `0.707`) as the default final canvas. Explicitly reject `2:3`, phone-long-screenshot, and extra-narrow poster proportions in the prompt.
   - Do not attach a tall event poster directly as a visual reference when it can pull the output into a narrow ratio. Translate its theme into words or a compact palette/mood reference instead.
   - Generate exactly one version first. Do not silently spray variants or run repeated correction generations after the user has seen or approved a version.
   - Compare every visible name, timestamp, duration, role, address, fixed-content line, section number, and officer row against the confirmed content before treating it as final.
   - Keep deterministic HTML/CSS as the editable backup and correction fallback. Start from `assets/agenda-template.html` when image generation fails text QA, when exact small corrections are needed, or when the user explicitly asks for an editable layout.
   - Use `assets/toastmasters-transparent.png` only when a cleaner official logo asset is not available locally.
   - Export a PNG for sharing and a PDF for printing when the user asks for a final agenda file.
   - Prefer an A4 portrait image for both sharing and printing. A nearby ratio is acceptable only when the user explicitly approves that exact version.
   - Generate print PDF as single-page A4 portrait (`210mm x 297mm`) with `scripts/make_a4_print_pdf.py`. Do not rely on browser default print settings, which may produce Letter size or split into multiple pages.

5. QA before treating the result as final.
   - Open or inspect the exported PNG.
   - Check no content is cut off, including bottom modules and footer.
   - Check the location against the current meeting input. Without an override, it must read `金地威新中心A座 6F 洱海会议室`; reject accidental `沿海` or stale `太湖` text.
   - Check PDF page size and page count: A4 portrait, exactly 1 page for a one-page agenda.
   - Check text does not overflow, collide, or sit awkwardly inside cards.
   - Check logo is integrated into the header, not pasted in a white box.
   - Check there is no fake logo such as a decorative `TM` mark.
   - Check whitespace is intentional: dense but orderly, not large dead blanks.
   - Check body typography has breathing room: avoid making every line heavy/bold.
   - Check the chosen image against the current officer list; reject stale officer rows and accidental extra `IPP` rows.
   - Check club-introduction labels are correct: `定位`, `使命`, `愿景`, and `关键词` must not be swapped or duplicated.
   - Check section numbering has no duplicated digits such as `1 1 幕后人员`.
   - Check the final aspect ratio is A4-like and not visibly narrow.
   - If the user has already selected a version despite a known imperfection, their explicit selection wins. Save that exact version, note the choice briefly, and stop.

## Visual Direction

For Mingyuan Yun agendas, prefer a formal Toastmasters event-poster language:

- Brand colors: Toastmasters loyal blue `#004165`, maroon `#772432`, gold/yellow `#F2DF74`, cool gray `#A9B2B1`.
- Layout: A4 portrait agenda; strong branded masthead; meta row; main timeline as the visual center; supporting modules below and/or left.
- Logo: integrate as a lockup in the masthead. Avoid white sticker boxes unless the supplied brand asset requires a plate.
- Typography: use a display face only for the main title and key theme; use readable sans for tables. Do not make all table text bold.
- Density: agenda sheets are allowed to be dense. Use hierarchy and grid rhythm instead of oversized decorative whitespace.
- Footer: use club name, slogan, and values. Do not invent a logo or fake monogram.

## Output Contract

When the first image is generated, show only that image. After the user approves a version:

- Copy that exact generated file into the user's chosen issue/output folder with a clear `最终采用` filename.
- Do not replace it with a later “improved” generation unless the user explicitly requests another version.
- Keep HTML as an editable backup only when it was created.
- Create a single-page A4 PDF only when the user asks for a print file or the delivery explicitly requires one.
