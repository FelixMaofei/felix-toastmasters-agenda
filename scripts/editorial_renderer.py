#!/usr/bin/env python3
"""Render a validated agenda result with the editorial A4 visual system."""

from __future__ import annotations

import base64
import html
import math
import re
import unicodedata
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any


SKILL_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_PATH = SKILL_ROOT / "assets" / "layouts" / "editorial-a4-template.html"
ICON_ROOT = SKILL_ROOT / "assets" / "icons" / "tabler"
DEFAULT_LOGO = SKILL_ROOT / "assets" / "toastmasters-logo.png"
FONT_ROOT = SKILL_ROOT / "assets" / "fonts" / "noto-sans-sc"
FONT_CSS_PATH = FONT_ROOT / "index.css"
FONT_FAMILY = "Felix Agenda Sans"
THEME_ASSETS = {
    "learning": SKILL_ROOT / "assets" / "themes" / "learning-brain-book.png",
}

ICON_FILES = {
    "calendar": "calendar.svg",
    "clock": "clock.svg",
    "map": "map-pin.svg",
    "book": "book.svg",
    "user": "user.svg",
    "camera": "camera.svg",
    "desktop": "device-desktop.svg",
    "link": "link.svg",
    "stars": "stars.svg",
    "list": "list-details.svg",
    "flag": "flag.svg",
    "microphone": "microphone.svg",
    "target": "target.svg",
    "world": "world.svg",
    "shield": "shield-check.svg",
    "puzzle": "puzzle.svg",
    "info": "info-circle.svg",
    "crown": "crown.svg",
    "school": "school.svg",
    "users": "users.svg",
    "speaker": "speakerphone.svg",
    "notebook": "notebook.svg",
    "money": "currency-dollar.svg",
    "briefcase": "briefcase.svg",
    "star": "star.svg",
    "award": "award.svg",
}

PHASES = {
    "opening": ("开场", "Opening", "stars"),
    "first_half": ("上半场", "First Half", "microphone"),
    "second_half": ("下半场", "Second Half", "target"),
    "closing": ("收尾", "Closing", "flag"),
}

OFFICER_ICONS = {
    "president": "crown",
    "vpe": "school",
    "vpm": "users",
    "vppr": "speaker",
    "secretary": "notebook",
    "treasurer": "money",
    "saa": "briefcase",
    "ipp": "star",
}


def escape(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def escape_with_protected_phrases(value: Any, phrases: tuple[str, ...]) -> str:
    rendered = escape(value)
    for phrase in phrases:
        rendered = rendered.replace(
            escape(phrase),
            f'<span class="keep-together">{escape(phrase)}</span>',
        )
    return rendered


def localized(zh: str, en: str, language: str) -> str:
    if language == "en":
        return en
    if language == "bilingual":
        return f"{zh} / {en}"
    return zh


def visual_text_units(value: Any) -> float:
    units = 0.0
    for char in str(value or ""):
        if char.isspace():
            units += 0.32
        elif unicodedata.east_asian_width(char) in {"W", "F"}:
            units += 1.0
        elif char.isupper() or char.isdigit():
            units += 0.64
        else:
            units += 0.54
    return units


def club_name_size_class(value: Any, language: str) -> str:
    units = visual_text_units(value)
    if language == "en":
        if units <= 19:
            return "name-normal"
        if units <= 25:
            return "name-long"
        return "name-xlong"
    if units <= 13:
        return "name-normal"
    if units <= 18:
        return "name-long"
    if units <= 24:
        return "name-xlong"
    return "name-xxlong"


def image_data_uri(path: Path) -> str:
    if not path.is_file():
        return ""
    suffix = path.suffix.lower()
    mime = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".svg": "image/svg+xml",
    }.get(suffix, "application/octet-stream")
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"


def parse_unicode_ranges(value: str) -> tuple[tuple[int, int], ...]:
    ranges: list[tuple[int, int]] = []
    for raw_token in value.split(","):
        token = raw_token.strip().upper()
        if not token.startswith("U+"):
            continue
        body = token[2:]
        if "?" in body:
            start = int(body.replace("?", "0"), 16)
            end = int(body.replace("?", "F"), 16)
        elif "-" in body:
            start_text, end_text = body.split("-", 1)
            start, end = int(start_text, 16), int(end_text, 16)
        else:
            start = end = int(body, 16)
        ranges.append((start, end))
    return tuple(ranges)


@lru_cache(maxsize=1)
def font_face_records() -> tuple[tuple[str, Path, tuple[tuple[int, int], ...]], ...]:
    css = FONT_CSS_PATH.read_text(encoding="utf-8")
    records: list[tuple[str, Path, tuple[tuple[int, int], ...]]] = []
    for face in re.findall(r"@font-face\s*\{.*?\}", css, flags=re.DOTALL):
        source = re.search(r"url\(([^)]+)\)", face)
        unicode_range = re.search(r"unicode-range:\s*([^;]+);", face)
        if not source or not unicode_range:
            continue
        relative = source.group(1).strip().strip("'\"")
        path = (FONT_ROOT / relative).resolve()
        if FONT_ROOT.resolve() not in path.parents or not path.is_file():
            raise ValueError(f"invalid bundled font path: {relative}")
        records.append((face, path, parse_unicode_ranges(unicode_range.group(1))))
    if not records:
        raise ValueError("bundled Noto Sans SC font CSS contains no usable faces")
    return tuple(records)


@lru_cache(maxsize=128)
def font_data_uri(path_text: str) -> str:
    encoded = base64.b64encode(Path(path_text).read_bytes()).decode("ascii")
    return f"data:font/woff2;base64,{encoded}"


def embedded_font_css(visible_text: str) -> str:
    codepoints = {ord(char) for char in visible_text if not char.isspace()}
    selected: list[str] = []
    covered: set[int] = set()
    for face, path, ranges in font_face_records():
        matching = {
            codepoint
            for codepoint in codepoints
            if any(start <= codepoint <= end for start, end in ranges)
        }
        if not matching:
            continue
        covered.update(matching)
        inlined = re.sub(
            r"url\([^)]+\)",
            f"url('{font_data_uri(str(path))}')",
            face,
            count=1,
        )
        inlined = inlined.replace("'Noto Sans SC Variable'", f"'{FONT_FAMILY}'")
        inlined = inlined.replace("font-display: swap", "font-display: block")
        selected.append(inlined)
    essential = {
        codepoint
        for codepoint in codepoints
        if codepoint < 0x2E80 or 0x3400 <= codepoint <= 0x9FFF
    }
    missing = essential - covered
    if missing:
        sample = "".join(chr(codepoint) for codepoint in sorted(missing)[:12])
        raise ValueError(f"bundled agenda font does not cover visible text: {sample}")
    if not selected:
        raise ValueError("no bundled font face matches the agenda text")
    return "\n".join(selected)


@lru_cache(maxsize=64)
def icon_svg(name: str, classes: str = "") -> str:
    filename = ICON_FILES.get(name)
    if not filename:
        return ""
    path = ICON_ROOT / filename
    source = path.read_text(encoding="utf-8")
    match = re.search(r"<svg\b([^>]*)>(.*)</svg>", source, flags=re.DOTALL)
    if not match:
        return ""
    attrs, body = match.groups()
    viewbox = re.search(r'viewBox="([^"]+)"', attrs)
    viewbox_value = viewbox.group(1) if viewbox else "0 0 24 24"
    body = body.replace('stroke="#000000"', 'stroke="currentColor"')
    body = body.replace('stroke="currentColor"', 'stroke="currentColor"')
    class_attr = f"ti {classes}".strip()
    return (
        f'<svg class="{escape(class_attr)}" viewBox="{escape(viewbox_value)}" '
        'aria-hidden="true" focusable="false">'
        f"{body}</svg>"
    )


def format_date(value: Any, language: str) -> str:
    text = str(value or "").strip()
    try:
        parsed = datetime.strptime(text, "%Y-%m-%d")
    except ValueError:
        return text or "-"
    if language == "en":
        return parsed.strftime("%b %d, %Y")
    weekdays = "一二三四五六日"
    return f"{parsed.year}年{parsed.month}月{parsed.day}日（周{weekdays[parsed.weekday()]}）"


def format_minutes(value: Any) -> str:
    number = float(value or 0)
    return str(int(number)) if number.is_integer() else f"{number:g}"


def details_inline(item: dict[str, Any]) -> str:
    details = [str(value).strip() for value in item.get("details", []) if str(value).strip()]
    return "｜".join(details)


def phase_groups(timeline: list[dict[str, Any]]) -> list[tuple[str, list[dict[str, Any]]]]:
    runs: list[tuple[str, list[dict[str, Any]]]] = []
    for item in timeline:
        key = str(item.get("section", "first_half"))
        if runs and runs[-1][0] == key:
            runs[-1][1].append(item)
        else:
            runs.append((key, [item]))
    return runs


def render_panel(title: str, icon_name: str, body: str, extra_class: str = "") -> str:
    classes = f"panel {extra_class}".strip()
    return (
        f'<article class="{escape(classes)}">'
        '<h2 class="panel-head">'
        f'{icon_svg(icon_name, "head-icon")}{escape(title)}</h2>'
        f"{body}</article>"
    )


def render_meta(
    meeting: dict[str, Any], computed: dict[str, Any], language: str
) -> str:
    cells = [
        (
            "calendar",
            localized("日期", "Date", language),
            format_date(meeting.get("date"), language),
            "",
        ),
        (
            "clock",
            localized("时间", "Time", language),
            f"{computed.get('start') or '-'} - {computed.get('final_end') or '-'}",
            "",
        ),
        (
            "map",
            localized("地点", "Location", language),
            meeting.get("location") or "-",
            "",
        ),
        (
            "book",
            localized("今日一词", "Word", language),
            meeting.get("word_of_day") or "-",
            " word",
        ),
        (
            "user",
            localized("会议经理", "Manager", language),
            meeting.get("manager") or "-",
            "",
        ),
    ]
    return "".join(
        '<div class="meta-item'
        + extra
        + '">'
        + icon_svg(icon_name, "meta-icon")
        + '<div class="meta-copy"><b>'
        + escape(label)
        + "</b><span>"
        + escape(value)
        + "</span></div></div>"
        for icon_name, label, value, extra in cells
    )


def backstage_icon(row: dict[str, Any]) -> str:
    token = f"{row.get('id', '')} {row.get('label', '')}".lower()
    if re.search(r"photo|camera|摄影|拍照", token):
        return "camera"
    if re.search(r"slide|ppt|场控|投屏", token):
        return "desktop"
    if re.search(r"vote|link|投票|链接", token):
        return "link"
    return "briefcase"


def render_backstage(rows: list[dict[str, Any]], language: str) -> str:
    visible = rows
    if not visible:
        visible = [{"label": "-", "person": "-"}]
    body = '<div class="backstage-list">' + "".join(
        '<div class="backstage-row">'
        + icon_svg(backstage_icon(row), "row-icon")
        + f'<strong>{escape(row.get("label") or "-")}</strong>'
        + f'<span>{escape(row.get("person") or "-")}</span></div>'
        for row in visible
    ) + "</div>"
    return render_panel(
        localized("幕后团队", "Backstage Team", language),
        "users",
        body,
    )


def render_timer_rules(language: str, timer_rules: list[dict[str, str]]) -> str:
    bands = []
    classes = ("green", "yellow", "red")
    for index, row in enumerate(timer_rules[:3]):
        color = classes[index]
        if language == "en":
            title = row.get("band_en", "")
            signals = (
                ("green", row.get("green_en", "")),
                ("yellow", row.get("yellow_en", "")),
                ("red", row.get("red_en", "")),
                ("bell", row.get("bell_en", "")),
            )
        else:
            title = row.get("band_zh", "")
            signals = (
                ("green", row.get("green_zh", "")),
                ("yellow", row.get("yellow_zh", "")),
                ("red", row.get("red_zh", "")),
                ("bell", row.get("bell_zh", "")),
            )
        bands.append(
            '<div class="timer-band">'
            f'<span class="paddle {color}"></span>'
            '<div class="timer-copy">'
            f"<strong>{escape(title)}</strong>"
            '<div class="timer-signals">'
            + "".join(
                f'<span class="signal {signal_class}">{escape(text)}</span>'
                for signal_class, text in signals
            )
            + "</div></div></div>"
        )
    return render_panel(
        localized("时间官规则", "Timer Rules", language),
        "clock",
        '<div class="timer-body">' + "".join(bands) + "</div>",
    )


def officer_key(role: Any) -> str:
    text = str(role or "").strip().lower()
    token = re.sub(r"[^a-z]", "", text)
    if text == "president" or "会长" in text and "副" not in text:
        return "president"
    if token in {"vpe", "vicepresidenteducation"} or "教育副会长" in text:
        return "vpe"
    if token in {"vpm", "vicepresidentmembership"} or "会员副会长" in text:
        return "vpm"
    if token in {"vppr", "vicepresidentpublicrelations"} or "公关副会长" in text:
        return "vppr"
    if token == "secretary" or "秘书" in text:
        return "secretary"
    if token == "treasurer" or "财务" in text:
        return "treasurer"
    if token in {"saa", "sergeantatarms"} or "事务官" in text:
        return "saa"
    if token == "ipp" or "荣誉会长" in text:
        return "ipp"
    return "star"


def render_officers(rows: list[dict[str, Any]], language: str) -> str:
    visible = rows
    body = '<div class="officer-list">' + "".join(
        '<div class="officer-row">'
        + icon_svg(OFFICER_ICONS.get(officer_key(row.get("role")), "star"), "row-icon")
        + f'<strong>{escape(row.get("role") or "-")}</strong>'
        + f'<span>{escape(row.get("name") or "-")}</span></div>'
        for row in visible
    ) + "</div>"
    return render_panel(
        localized("当届官员团队", "Current Officer Team", language),
        "users",
        body,
    )


def render_sidebar(
    result: dict[str, Any],
    language: str,
    timer_rules: list[dict[str, str]],
) -> tuple[str, int]:
    cards = [render_backstage(result.get("backstage", []), language)]
    components = result.get("support_components", [])
    if "timer_rules" in components:
        cards.append(render_timer_rules(language, timer_rules))
    if "officers" in components:
        cards.append(render_officers(result.get("club", {}).get("officers", []), language))
    return "".join(cards), len(cards)


def render_timeline(result: dict[str, Any], language: str) -> tuple[str, str]:
    timeline = result.get("timeline", [])
    row_count = len(timeline)
    density = "density-normal" if row_count <= 18 else "density-compact" if row_count <= 23 else "density-ultra"
    feature_item = result.get("feature_item")
    rows: list[str] = []
    for section, items in phase_groups(timeline):
        zh, en, phase_icon = PHASES.get(section, ("流程", "Agenda", "list"))
        start = items[0].get("start", "")
        end = items[-1].get("end", "")
        rows.append(
            '<tr class="phase-row"><td colspan="4"><div class="phase-wrap">'
            '<span class="phase-badge">'
            + icon_svg(phase_icon, "phase-icon")
            + "</span>"
            + escape(localized(zh, en, language))
            + f'<span class="phase-range">{escape(start)} - {escape(end)}</span>'
            + "</div></td></tr>"
        )
        for item in items:
            details = details_inline(item)
            label = escape(item.get("label"))
            if details:
                separator = "" if language == "en" else "｜"
                label += f'<span class="item-detail">{separator}{escape(details)}</span>'
            featured = (
                item.get("id") == feature_item
                or item.get("type") == "special"
                or float(item.get("duration") or 0) >= 20
            )
            row_classes: list[str] = []
            if featured:
                row_classes.append("featured")
            if details:
                row_classes.append("has-detail")
            rows.append(
                f'<tr class="{" ".join(row_classes)}">'
                f'<td class="time-cell">{escape(item.get("start"))}</td>'
                f'<td class="item-cell">{label}</td>'
                f'<td>{escape(item.get("owner") or "-")}</td>'
                f'<td>{escape(format_minutes(item.get("duration")))} min</td>'
                "</tr>"
            )
    rows.append(
        '<tr class="phase-row"><td colspan="4"><div class="phase-wrap">'
        '<span class="phase-badge">'
        + icon_svg("flag", "phase-icon")
        + "</span>"
        + escape(localized("结束", "End", language))
        + f'<span class="phase-range">{escape(result.get("computed", {}).get("final_end"))}</span>'
        + "</div></td></tr>"
    )
    return "".join(rows), density


def custom_block_map(result: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(block.get("id")): block
        for block in result.get("custom_support_blocks", [])
        if block.get("id")
    }


def editorial_compatibility_errors(result: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    language = result.get("club", {}).get("language", "zh")
    layout = result.get("layout", "standard")
    components = set(result.get("support_components", []))
    club = result.get("club", {})
    custom = custom_block_map(result)

    if language not in {"zh", "en"}:
        errors.append("editorial renderer currently supports zh or en")
    if layout != "standard":
        errors.append("editorial renderer currently supports standard meetings only")
    if components & {"vpm_qr", "voting_qr"}:
        errors.append("editorial renderer does not yet support QR components")
    if len(result.get("backstage", [])) > 4:
        errors.append("editorial renderer supports at most 4 backstage roles")
    if "officers" in components and len(club.get("officers", [])) > 8:
        errors.append("editorial renderer supports at most 8 officer rows")

    panel_count = 0
    panel_count += int("toastmasters_intro" in components)
    panel_count += int("meeting_boundaries" in components)
    panel_count += int("club_intro" in components and bool(club.get("club_intro")))
    panel_count += int("join_info" in components and bool(club.get("join_info")))
    panel_count += len(custom)
    if any(block.get("placement") == "left" for block in custom.values()):
        errors.append(
            "editorial renderer does not yet support custom_support_blocks placement:left"
        )
    if panel_count > 4:
        errors.append(
            f"editorial renderer supports at most 4 bottom information panels; got {panel_count}"
        )
    return errors


def support_panel(
    title: str,
    icon_name: str,
    body: str,
    extra_class: str = "",
) -> str:
    classes = f"support-panel {extra_class}".strip()
    return render_panel(
        title,
        icon_name,
        f'<div class="support-body">{body}</div>',
        classes,
    )


def render_club_facts(lines: list[Any]) -> str:
    icons = ("target", "award", "users", "star", "shield")
    rows: list[str] = []
    for index, raw_line in enumerate(lines):
        line = str(raw_line or "").strip()
        if not line:
            continue
        match = re.match(r"^([^:：]{1,24})([:：])\s*(.*)$", line)
        if match:
            label = match.group(1) + match.group(2)
            value = match.group(3) or "-"
        else:
            label = ""
            value = line
        rows.append(
            "<div>"
            + icon_svg(icons[index % len(icons)], "fact-icon")
            + f"<strong>{escape(label)}</strong>"
            + f"<span>{escape(value)}</span></div>"
        )
    return '<div class="club-facts">' + "".join(rows) + "</div>"


def support_grid_template(panels: list[str], language: str) -> str:
    count = len(panels)
    if count <= 1:
        return "1fr"
    canonical_four = (
        count == 4
        and "support-toastmasters-intro" in panels[0]
        and "support-meeting-boundaries" in panels[1]
        and "support-optional-sessions" in panels[2]
        and "support-club-facts" in panels[3]
    )
    if canonical_four:
        return "0.95fr 1.05fr .78fr 1.22fr" if language == "en" else "1.08fr .95fr .72fr 1.25fr"
    raw: list[float] = []
    for panel in panels:
        visible = html.unescape(re.sub(r"<[^>]+>", " ", panel))
        required_line_width = 0.0
        for tag_name, allowed_lines in (("li", 2), ("p", 6)):
            for fragment in re.findall(
                rf"<{tag_name}\b[^>]*>(.*?)</{tag_name}>", panel, flags=re.DOTALL
            ):
                plain = html.unescape(re.sub(r"<[^>]+>", " ", fragment))
                units = visual_text_units(plain)
                preferred_lines = (
                    1 if tag_name == "li" and units <= 30 else allowed_lines
                )
                required_line_width = max(
                    required_line_width,
                    units / preferred_lines,
                )
        if 'class="club-facts"' in panel:
            for fragment in re.findall(r"<span>(.*?)</span>", panel, flags=re.DOTALL):
                plain = html.unescape(re.sub(r"<[^>]+>", " ", fragment))
                units = visual_text_units(plain)
                required_line_width = max(
                    required_line_width,
                    units if units <= 20 else units / 2,
                )
        raw.append(
            math.sqrt(max(8.0, visual_text_units(visible)))
            + .6 * required_line_width
        )
    average = sum(raw) / count
    minimum, maximum = ((0.9, 1.1) if count == 2 else (0.78, 1.34) if count == 3 else (0.72, 1.45))
    weights = [min(max(value / average, minimum), maximum) for value in raw]
    for _ in range(3):
        scale = count / sum(weights)
        weights = [min(max(value * scale, minimum), maximum) for value in weights]
    return " ".join(f"{value:.3f}fr" for value in weights)


def render_support_panels(
    result: dict[str, Any],
    language: str,
    toastmasters_intro_text: str,
    meeting_boundary_lines: list[str],
) -> list[str]:
    club = result.get("club", {})
    components = result.get("support_components", [])
    custom = custom_block_map(result)
    panels: list[str] = []
    if "toastmasters_intro" in components:
        intro_text = (
            escape_with_protected_phrases(
                toastmasters_intro_text,
                ("是一个通过", "非营利教育组织"),
            )
            if language != "en"
            else escape(toastmasters_intro_text)
        )
        panels.append(
            support_panel(
                localized("头马国际介绍", "Toastmasters", language),
                "world",
                f"<p>{intro_text}</p>"
                '<span class="site-link">toastmasters.org</span>',
                "support-toastmasters-intro",
            )
        )
    if "meeting_boundaries" in components:
        protected_phrases = (
            ("调至静音或震动", "色情") if language != "en" else ()
        )
        panels.append(
            support_panel(
                localized("会议边界", "Meeting Boundaries", language),
                "shield",
                "<ul>"
                + "".join(
                    f"<li>{escape_with_protected_phrases(line, protected_phrases)}</li>"
                    for line in meeting_boundary_lines
                )
                + "</ul>",
                "support-meeting-boundaries",
            )
        )
    if "club_intro" in components and club.get("club_intro"):
        panels.append(
            support_panel(
                localized("俱乐部介绍", "About the Club", language),
                "info",
                "<ul>"
                + "".join(f"<li>{escape(line)}</li>" for line in club.get("club_intro", []))
                + "</ul>",
                "support-club-intro",
            )
        )
    if "join_info" in components and club.get("join_info"):
        panels.append(
            support_panel(
                localized("如何入会", "How to Join", language),
                "users",
                "<ul>"
                + "".join(f"<li>{escape(line)}</li>" for line in club.get("join_info", []))
                + "</ul>",
                "support-join-info",
            )
        )
    preferred_custom = ("optional_sessions", "guest_participation", "club_facts", "pathways")
    for block_id in preferred_custom:
        block = custom.pop(block_id, None)
        if not block:
            continue
        icon_name = {
            "optional_sessions": "puzzle",
            "guest_participation": "users",
            "club_facts": "info",
            "pathways": "school",
        }[block_id]
        if block_id == "club_facts":
            body = render_club_facts(block.get("lines", []))
            extra_class = "support-club-facts"
        else:
            body = (
                "<ul>"
                + "".join(
                    f"<li>{escape(line)}</li>" for line in block.get("lines", [])
                )
                + "</ul>"
            )
            extra_class = f"support-{block_id.replace('_', '-')}"
        panels.append(
            support_panel(
                str(block.get("title") or ""),
                icon_name,
                body,
                extra_class,
            )
        )
    for block in custom.values():
        panels.append(
            support_panel(
                str(block.get("title") or ""),
                "info",
                "<ul>"
                + "".join(f"<li>{escape(line)}</li>" for line in block.get("lines", []))
                + "</ul>",
                "support-custom",
            )
        )
    return panels


def footer_text(result: dict[str, Any], language: str) -> tuple[str, str]:
    slogan = localized(
        "Toastmasters International",
        "Toastmasters International",
        language,
    )
    computed = result.get("computed", {})
    values = localized(
        "时间闭环："
        + f"{format_minutes(computed.get('item_minutes'))} + "
        + f"{format_minutes(computed.get('transition_minutes'))} = "
        + f"{format_minutes(computed.get('total_minutes'))} min",
        "Time closed: "
        + f"{format_minutes(computed.get('item_minutes'))} + "
        + f"{format_minutes(computed.get('transition_minutes'))} = "
        + f"{format_minutes(computed.get('total_minutes'))} min",
        language,
    )
    return slogan, values


def render_editorial_html(
    result: dict[str, Any],
    *,
    timer_rules: list[dict[str, str]],
    toastmasters_intro_text: str,
    meeting_boundary_lines: list[str],
) -> str:
    language = result.get("club", {}).get("language", "zh")
    compatibility_errors = editorial_compatibility_errors(result)
    if compatibility_errors:
        raise ValueError("; ".join(compatibility_errors))
    club = result.get("club", {})
    meeting = result.get("meeting", {})
    computed = result.get("computed", {})
    logo = image_data_uri(DEFAULT_LOGO)
    explicit_theme_art = result.get("_assets", {}).get("theme_art_data_uri", "")
    visual_theme = str(result.get("visual_theme", "general"))
    if visual_theme not in {
        "general",
        "learning",
        "technology",
        "wellness",
        "voice",
        "leadership",
        "celebration",
    }:
        visual_theme = "general"
    theme_asset = THEME_ASSETS.get(visual_theme)
    theme_art = explicit_theme_art or (image_data_uri(theme_asset) if theme_asset else "")

    sidebar_html, sidebar_count = render_sidebar(result, language, timer_rules)
    timeline_rows, density = render_timeline(result, language)
    panels = render_support_panels(
        result,
        language,
        toastmasters_intro_text,
        meeting_boundary_lines,
    )
    if not panels:
        panels = [
            support_panel(
                localized("本期说明", "Meeting Note", language),
                "info",
                f"<p>{escape(meeting.get('theme') or '-')}</p>",
            )
        ]
    support_count = len(panels)
    support_columns = support_grid_template(panels, language)
    slogan, values = footer_text(result, language)

    number = escape(meeting.get("number") or "")
    club_name = escape(club.get("name") or "")
    agenda_title = localized("例会议程", "Meeting Agenda", language)
    theme = escape(meeting.get("theme") or localized("本期例会", "Club Meeting", language))
    document_title = f"{club_name} {number} {agenda_title}".strip()
    name_size_class = club_name_size_class(club.get("name"), language)
    body = f"""
<main class="page language-{escape(language)} {escape(name_size_class)} visual-{escape(visual_theme)}">
  <header class="hero">
    <img class="brand-logo" src="{logo}" alt="Toastmasters International">
    <div class="hero-copy">
      <div class="club-name">{club_name}</div>
      <div class="meeting-title">{localized("第", "Meeting ", language)}<em>{number}</em>{localized("期", "", language)}&nbsp; {escape(agenda_title)}</div>
      <div class="theme-title">{localized("主题：", "Theme: ", language)}{theme}</div>
    </div>
    {"<img class='theme-art' src='" + theme_art + "' alt=''>" if theme_art else '<span class="theme-pattern" aria-hidden="true"></span>'}
  </header>
  <section class="meta-strip">{render_meta(meeting, computed, language)}</section>
  <div class="rule-separator" aria-hidden="true"></div>
  <section class="main-grid">
    <aside class="sidebar sidebar-{sidebar_count}">{sidebar_html}</aside>
    <article class="panel agenda-panel">
      <div class="agenda-head">
        <strong>{icon_svg("list", "head-icon")}{escape(localized("会议流程", "Meeting Flow", language))}</strong>
        <span>{escape(computed.get("start"))} - {escape(computed.get("final_end"))}</span>
      </div>
      <table class="agenda-table {density}" aria-label="{escape(agenda_title)}">
        <colgroup><col class="time"><col class="item"><col class="owner"><col class="duration"></colgroup>
        <thead><tr>
          <th>{escape(localized("时间", "Time", language))}</th>
          <th>{escape(localized("环节", "Agenda", language))}</th>
          <th>{escape(localized("负责人", "Role Taker", language))}</th>
          <th>{escape(localized("时长", "Duration", language))}</th>
        </tr></thead>
        <tbody>{timeline_rows}</tbody>
      </table>
    </article>
  </section>
  <div aria-hidden="true"></div>
  <section class="support-grid support-count-{support_count}" data-seed-columns="{escape(support_columns)}" style="grid-template-columns:{escape(support_columns)}">{"".join(panels)}</section>
  <div aria-hidden="true"></div>
  <footer class="footer">
    <div class="footer-brand">
      <span class="mic-mark">{icon_svg("microphone", "footer-icon")}</span>
      <div>
        <div class="footer-name">{club_name}</div>
        <div class="footer-slogan">{escape(slogan)}</div>
      </div>
    </div>
    <div class="footer-values">{escape(values)}</div>
  </footer>
</main>"""
    visible_text = html.unescape(re.sub(r"<[^>]+>", " ", document_title + " " + body))
    font_css = embedded_font_css(visible_text)
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    return (
        template.replace("{{DOCUMENT_TITLE}}", escape(document_title))
        .replace("{{FONT_CSS}}", font_css)
        .replace("{{BODY}}", body)
    )
