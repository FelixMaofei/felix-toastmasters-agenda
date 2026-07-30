# GPT Image Agenda Workflow

## Required Inputs

Before image generation, have all four:

1. Confirmed Markdown content truth.
2. Recalculated full timeline with no unresolved negative or hidden residual time.
3. Current officer list and fixed club content.
4. One stable A4 visual reference.

Do not start image generation while sequence, duration, role ownership, address, or fixed content is still being discussed.

## Reference Order

Recommended references:

1. A verified A4 content-truth image rendered from the confirmed Markdown/HTML.
2. `../assets/agenda-reference-good.png` for information architecture and Toastmasters formality.
3. `../assets/agenda-a4-health-reference.png` only when its health-theme language is relevant.

The content-truth image always wins. Style references must be explicitly forbidden from contributing their old dates, places, officers, themes, or timeline rows.

Avoid using tall promotional posters as direct references. They can pull the agenda into a narrow phone-poster ratio. Describe their color, mood, or motifs in the prompt instead.

## A4 Prompt Requirements

Every prompt must state:

- Standard A4 portrait ratio `210:297`, approximately `0.707`.
- Not `2:3`, not a phone screenshot, and not an extra-tall narrow poster.
- One complete flat page, no mockup, no external scene, and no multiple versions.
- All names, times, durations, locations, section labels, and fixed text come only from the content-truth reference.
- The style reference contributes design only and must not contribute any text.
- Official Toastmasters logo only; no fake `TM` monogram.

Repeat the highest-risk exact fields in the prompt:

- Issue number, date, weekday, and meeting time.
- Exact room name, especially `6F 洱海会议室`.
- Special-segment order and start times.
- Unusual literal values such as `拍照官：电视机`.
- Current officer list.
- Explicitly absent segments.

## One-Version Rule

- Generate one version first.
- Do not batch-generate options.
- Do not silently generate correction after correction while the user is already reviewing the output.
- If the user says `完美`, `就这样`, `用这个`, `采用初版`, or equivalent, stop immediately and save that exact image.
- Never replace the selected image because a later version seems technically cleaner.

## Visual QA Checklist

Compare the output against the confirmed Markdown:

- [ ] A4-like proportion; not narrow.
- [ ] Issue, date, weekday, entry time, formal meeting time.
- [ ] Exact address and room name.
- [ ] Theme, 今日一词, meeting manager.
- [ ] Backstage roles, including literal unusual values.
- [ ] Every timeline row in the confirmed order.
- [ ] Every start time, duration, and owner.
- [ ] No removed segment reappears.
- [ ] Current officers only; no stale role/name or extra IPP.
- [ ] Pathways codes and names.
- [ ] Timer rules.
- [ ] Guest participation and reminders.
- [ ] Toastmasters introduction and website.
- [ ] Club `定位`, `使命`, `愿景`, `关键词`, slogan, and values.
- [ ] No duplicated section number.
- [ ] No clipped, garbled, overlapping, or invented text.

## Finalization

After explicit approval:

1. Copy the exact selected generated image to the matching issue folder.
2. Use a filename ending in `最终采用.png`.
3. Keep prior versions clearly labeled or outside the formal issue folder; do not let multiple files all claim to be final.
4. Stop unless the user asks for PDF, another ratio, or a new revision.
