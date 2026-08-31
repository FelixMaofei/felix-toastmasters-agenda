#!/usr/bin/env python3
"""Build a validated, time-closed Toastmasters agenda from minimal meeting facts."""

from __future__ import annotations

import argparse
import base64
import html
import json
import re
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any


SKILL_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LOGO = SKILL_ROOT / "assets" / "toastmasters-logo.png"

UNRESOLVED = {"", "?", "？", "🌺", "待定", "待确认", "招募中", "tbd", "pending", "todo"}
LANGUAGES = {"zh", "en", "bilingual"}

STANDARD_TYPES = {
    "rules",
    "president_opening",
    "toastmaster_opening",
    "guest_introduction",
    "photo_break",
    "sharing",
    "awards",
    "president_closing",
}

ROLE_IDS = {
    "president",
    "rules_host",
    "toastmaster",
    "timer",
    "ah_counter",
    "grammarian",
    "guest_host",
    "sharing_host",
    "general_evaluator",
    "awards_host",
}

DEFAULT_DURATIONS: dict[str, int | None] = {
    "rules": 2,
    "president_opening": 3,
    "toastmaster_opening": 2,
    "timer_intro": 2,
    "ah_counter_intro": 2,
    "grammarian_intro": 2,
    "guest_introduction": 5,
    "prepared_speech": 7,
    "table_topics": None,
    "photo_break": 5,
    "prepared_evaluation": 3,
    "table_topics_evaluation": None,
    "grammarian_report": 3,
    "ah_counter_report": 3,
    "timer_report": 3,
    "sharing": 6,
    "general_evaluation": 8,
    "awards": 3,
    "president_closing": 2,
    "special": None,
    "buffer": None,
}

LABELS = {
    "rules": ("规则介绍", "Meeting Rules"),
    "president_opening": ("会长致辞", "President's Opening Remarks"),
    "toastmaster_opening": ("总主持开场", "Toastmaster's Opening"),
    "timer_intro": ("时间官宣言", "Timer's Introduction"),
    "ah_counter_intro": ("哼哈官宣言", "Ah-Counter's Introduction"),
    "grammarian_intro": ("语法官宣言", "Grammarian's Introduction"),
    "guest_introduction": ("嘉宾介绍", "Guest Introduction"),
    "prepared_speech": ("备稿演讲", "Prepared Speech"),
    "table_topics": ("即兴演讲", "Table Topics"),
    "photo_break": ("合影＋中场休息", "Group Photo & Break"),
    "prepared_evaluation": ("备稿点评", "Speech Evaluation"),
    "table_topics_evaluation": ("即兴点评", "Table Topics Evaluation"),
    "grammarian_report": ("语法官报告", "Grammarian's Report"),
    "ah_counter_report": ("哼哈官报告", "Ah-Counter's Report"),
    "timer_report": ("时间官报告", "Timer's Report"),
    "sharing": ("真情分享", "Sharing"),
    "general_evaluation": ("总点评", "General Evaluation"),
    "awards": ("颁奖", "Awards"),
    "president_closing": ("闭幕致辞", "President's Closing Remarks"),
    "special": ("特别环节", "Special Session"),
    "buffer": ("缓冲", "Buffer"),
}

SECTION_LABELS = {
    "opening": ("开场", "Opening"),
    "first_half": ("上半场", "First Half"),
    "second_half": ("下半场", "Second Half"),
    "closing": ("收尾", "Closing"),
}

NO_TRANSITION_AFTER = {"rules", "president_opening", "photo_break"}
FLEX_BOUNDS = {
    "photo_break": (1, 15),
    "sharing": (1, 20),
}

CORE_OFFICER_ALIASES = {
    "president": {"president", "会长", "主席"},
    "vpe": {
        "vpe",
        "vice president education",
        "vice president of education",
        "教育副会长",
    },
    "vpm": {
        "vpm",
        "vice president membership",
        "vice president of membership",
        "会员副会长",
    },
    "vppr": {
        "vppr",
        "vice president public relations",
        "vice president of public relations",
        "公关副会长",
    },
    "secretary": {"secretary", "秘书", "秘书长"},
    "treasurer": {"treasurer", "财务官"},
    "saa": {"saa", "sergeant at arms", "sergeant-at-arms", "事务官"},
}

SUPPORT_COMPONENTS = {
    "timer_rules",
    "toastmasters_intro",
    "meeting_boundaries",
    "officers",
    "club_intro",
    "join_info",
    "vpm_qr",
    "voting_qr",
}

TOASTMASTERS_INTRO = {
    "zh": (
        "头马国际演讲会成立于1924年，是一个通过全球俱乐部网络帮助会员建立自信、"
        "提升公众演讲、沟通与领导力的非营利教育组织。"
    ),
    "en": (
        "Toastmasters International, founded in 1924, is a nonprofit educational "
        "organization that builds confidence and teaches public speaking, communication "
        "and leadership through a worldwide network of clubs."
    ),
}

TIMER_RULES = [
    {
        "band_zh": "3分钟及以下",
        "band_en": "3 min or less",
        "green_zh": "剩余1分钟",
        "green_en": "1 min left",
        "yellow_zh": "剩余30秒",
        "yellow_en": "30 sec left",
        "red_zh": "时间到",
        "red_en": "Time",
        "bell_zh": "超时15秒响铃",
        "bell_en": "Bell at +15 sec",
    },
    {
        "band_zh": "超过3分钟至10分钟",
        "band_en": "Over 3 to 10 min",
        "green_zh": "剩余2分钟",
        "green_en": "2 min left",
        "yellow_zh": "剩余1分钟",
        "yellow_en": "1 min left",
        "red_zh": "时间到",
        "red_en": "Time",
        "bell_zh": "超时30秒响铃",
        "bell_en": "Bell at +30 sec",
    },
    {
        "band_zh": "10分钟以上",
        "band_en": "Over 10 min",
        "green_zh": "剩余5分钟",
        "green_en": "5 min left",
        "yellow_zh": "剩余2分钟",
        "yellow_en": "2 min left",
        "red_zh": "时间到",
        "red_en": "Time",
        "bell_zh": "超时30秒响铃",
        "bell_en": "Bell at +30 sec",
    },
]


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError("JSON root must be an object")
    return value


def is_unresolved(value: Any) -> bool:
    if value is None:
        return True
    text = str(value).strip()
    return text.lower() in UNRESOLVED or text in UNRESOLVED or "{{" in text or "}}" in text


def positive_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value


def nonnegative_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def parse_clock(value: Any) -> int:
    match = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*", str(value))
    if not match:
        raise ValueError(f"invalid clock time {value!r}; use HH:MM")
    hour, minute = map(int, match.groups())
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"invalid clock time {value!r}")
    return hour * 60 + minute


def format_clock(value: int) -> str:
    value %= 24 * 60
    return f"{value // 60:02d}:{value % 60:02d}"


def display_label(item_type: str, language: str, override: Any = None) -> str:
    if not is_unresolved(override):
        return str(override).strip()
    zh, en = LABELS.get(item_type, (item_type, item_type))
    if language == "en":
        return en
    if language == "bilingual":
        return f"{zh} / {en}"
    return zh


def section_label(section: str, language: str) -> str:
    zh, en = SECTION_LABELS.get(section, (section, section))
    if language == "en":
        return en
    if language == "bilingual":
        return f"{zh} / {en}"
    return zh


def localized(zh: str, en: str, language: str) -> str:
    if language == "en":
        return en
    if language == "bilingual":
        return f"{zh} / {en}"
    return zh


def toastmasters_intro(language: str) -> str:
    if language == "en":
        return TOASTMASTERS_INTRO["en"]
    if language == "bilingual":
        return TOASTMASTERS_INTRO["zh"] + " " + TOASTMASTERS_INTRO["en"]
    return TOASTMASTERS_INTRO["zh"]


def normalize_details(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if not is_unresolved(item)]
    if is_unresolved(value):
        return []
    return [str(value).strip()]


def normalize_support_text(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if not is_unresolved(item)]
    if is_unresolved(value):
        return []
    text = str(value).strip()
    return [line.strip() for line in text.splitlines() if line.strip()]


def normalize_officer_key(value: Any) -> str | None:
    token = re.sub(r"[^a-z]", "", str(value).lower())
    original = str(value).strip().lower()
    for key, aliases in CORE_OFFICER_ALIASES.items():
        for alias in aliases:
            alias_lower = alias.lower()
            alias_token = re.sub(r"[^a-z]", "", alias_lower)
            if original == alias_lower or (token and alias_token and token == alias_token):
                return key
    return None


def parse_officers(value: Any, errors: list[str]) -> list[dict[str, str]]:
    if not isinstance(value, list) or not value:
        errors.append("club.officers is required and must list the current officer team")
        return []
    result: list[dict[str, str]] = []
    seen_core: set[str] = set()
    for index, row in enumerate(value, start=1):
        if not isinstance(row, dict):
            errors.append(f"club.officers[{index}] must be an object")
            continue
        role = row.get("role")
        name = row.get("name")
        if is_unresolved(role):
            errors.append(f"club.officers[{index}] is missing role")
        if is_unresolved(name):
            errors.append(f"club.officers[{index}] is missing name")
        role_text = "" if role is None else str(role).strip()
        name_text = "" if name is None else str(name).strip()
        core_key = normalize_officer_key(role_text)
        if core_key:
            if core_key in seen_core:
                errors.append(f"club.officers contains duplicate core role: {role_text}")
            seen_core.add(core_key)
        result.append({"role": role_text, "name": name_text})
    missing = [key.upper() if key.startswith("vp") or key == "saa" else key.title() for key in CORE_OFFICER_ALIASES if key not in seen_core]
    if missing:
        errors.append("club.officers is missing core roles: " + ", ".join(missing))
    return result


def parse_support_components(value: Any, errors: list[str]) -> list[str]:
    if not isinstance(value, list):
        errors.append(
            "support_components must be an explicit array; ask the user which fixed-content "
            "components to include"
        )
        return []
    result: list[str] = []
    for index, item in enumerate(value, start=1):
        component = str(item).strip()
        if component not in SUPPORT_COMPONENTS:
            errors.append(f"support_components[{index}] is unsupported: {component!r}")
            continue
        if component in result:
            errors.append(f"duplicate support component: {component}")
            continue
        result.append(component)
    return result


def find_photographer(backstage: list[dict[str, Any]]) -> str | None:
    for row in backstage:
        token = f"{row.get('id', '')} {row.get('role', '')} {row.get('label', '')}".lower()
        if re.search(r"photographer|photo|摄影|拍照", token):
            person = row.get("person", row.get("name"))
            if not is_unresolved(person):
                return str(person).strip()
    return None


def make_item(
    item_type: str,
    owner: Any,
    language: str,
    section: str,
    *,
    item_id: str | None = None,
    label: Any = None,
    duration: int | None = None,
    locked: bool = True,
    preferred: int | None = None,
    details: Any = None,
    transition_after: int | None = None,
    owner_required: bool = True,
    source: str = "generated",
) -> dict[str, Any]:
    return {
        "id": item_id or item_type,
        "type": item_type,
        "label": display_label(item_type, language, label),
        "owner": "" if owner is None else str(owner).strip(),
        "owner_required": owner_required,
        "section": section,
        "details": normalize_details(details),
        "duration": duration,
        "duration_locked": locked,
        "preferred_duration": preferred,
        "transition_after_override": transition_after,
        "source": source,
    }


def parse_roles(data: Any, errors: list[str]) -> tuple[list[str], dict[str, str]]:
    if data is None:
        return [], {}
    if not isinstance(data, list):
        errors.append("roles must be an array")
        return [], {}
    order: list[str] = []
    mapping: dict[str, str] = {}
    for index, row in enumerate(data, start=1):
        if not isinstance(row, dict):
            errors.append(f"roles[{index}] must be an object")
            continue
        role_id = str(row.get("id", "")).strip()
        if role_id not in ROLE_IDS:
            errors.append(f"roles[{index}] has unsupported id: {role_id!r}")
            continue
        if role_id in mapping:
            errors.append(f"duplicate role id: {role_id}")
            continue
        person = row.get("person")
        if is_unresolved(person):
            errors.append(f"role {role_id} exists but its person is unresolved")
            mapping[role_id] = ""
        else:
            mapping[role_id] = str(person).strip()
        order.append(role_id)
    return order, mapping


def parse_backstage(data: Any, errors: list[str]) -> list[dict[str, Any]]:
    if data is None:
        return []
    if not isinstance(data, list):
        errors.append("backstage must be an array")
        return []
    result: list[dict[str, Any]] = []
    for index, row in enumerate(data, start=1):
        if not isinstance(row, dict):
            errors.append(f"backstage[{index}] must be an object")
            continue
        role_id = str(row.get("id", row.get("role", ""))).strip()
        person = row.get("person", row.get("name"))
        if not role_id:
            errors.append(f"backstage[{index}] is missing id/role")
        if is_unresolved(person):
            errors.append(f"backstage role {role_id or index} has unresolved person")
        result.append(
            {
                "id": role_id,
                "label": str(row.get("label", row.get("role", role_id))).strip(),
                "person": "" if person is None else str(person).strip(),
            }
        )
    return result


def parse_overrides(data: Any, errors: list[str]) -> dict[str, dict[str, Any]]:
    if data is None:
        return {}
    if not isinstance(data, list):
        errors.append("standard_overrides must be an array")
        return {}
    result: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(data, start=1):
        if not isinstance(row, dict):
            errors.append(f"standard_overrides[{index}] must be an object")
            continue
        item_id = str(row.get("id", "")).strip()
        if item_id not in STANDARD_TYPES:
            errors.append(f"standard_overrides[{index}] has unsupported id: {item_id!r}")
            continue
        if item_id in result:
            errors.append(f"duplicate standard override: {item_id}")
            continue
        if "enabled" in row and not isinstance(row["enabled"], bool):
            errors.append(f"standard override {item_id} enabled must be a boolean")
        if "minutes" in row and positive_int(row["minutes"]) is None:
            errors.append(f"standard override {item_id} minutes must be a positive integer")
        if "transition_after" in row and nonnegative_int(row["transition_after"]) is None:
            errors.append(f"standard override {item_id} transition_after must be a nonnegative integer")
        result[item_id] = deepcopy(row)
    return result


def build_items(
    data: dict[str, Any],
    language: str,
    meeting: dict[str, Any],
    role_order: list[str],
    roles: dict[str, str],
    backstage: list[dict[str, Any]],
    overrides: dict[str, dict[str, Any]],
    errors: list[str],
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    photographer = find_photographer(backstage)
    president = meeting.get("president") or roles.get("president")

    def standard(
        item_type: str,
        owner: Any,
        section: str,
        *,
        flexible: bool = False,
    ) -> dict[str, Any] | None:
        override = overrides.get(item_type, {})
        if override.get("enabled", True) is False:
            return None
        resolved_owner = override.get("owner", owner)
        explicit_minutes = override.get("minutes")
        if explicit_minutes is not None:
            duration = explicit_minutes
            locked = True
            preferred = None
        elif flexible:
            duration = None
            locked = False
            preferred = DEFAULT_DURATIONS[item_type]
        else:
            duration = DEFAULT_DURATIONS[item_type]
            locked = True
            preferred = None
        return make_item(
            item_type,
            resolved_owner,
            language,
            section,
            label=override.get("label"),
            duration=duration,
            locked=locked,
            preferred=preferred,
            transition_after=override.get("transition_after"),
            source="standard",
        )

    for item in (
        standard("rules", roles.get("rules_host"), "opening"),
        standard("president_opening", president, "opening"),
        standard("toastmaster_opening", roles.get("toastmaster"), "opening"),
    ):
        if item:
            items.append(item)

    function_role_types = {
        "timer": ("timer_intro", "timer_report"),
        "ah_counter": ("ah_counter_intro", "ah_counter_report"),
        "grammarian": ("grammarian_intro", "grammarian_report"),
    }
    present_functions = [role_id for role_id in role_order if role_id in function_role_types]
    for role_id in present_functions:
        intro_type, _ = function_role_types[role_id]
        items.append(
            make_item(
                intro_type,
                roles[role_id],
                language,
                "opening",
                duration=DEFAULT_DURATIONS[intro_type],
                source="role",
            )
        )

    guest = standard("guest_introduction", roles.get("guest_host"), "opening")
    if guest:
        items.append(guest)

    speeches = data.get("prepared_speeches", [])
    if speeches is None:
        speeches = []
    if not isinstance(speeches, list):
        errors.append("prepared_speeches must be an array")
        speeches = []
    evaluation_items: list[dict[str, Any]] = []
    for index, speech in enumerate(speeches, start=1):
        if not isinstance(speech, dict):
            errors.append(f"prepared_speeches[{index}] must be an object")
            continue
        speaker = speech.get("speaker")
        if is_unresolved(speaker):
            errors.append(f"prepared speech {index} has unresolved speaker")
        minutes_value = speech.get("minutes")
        if minutes_value is None:
            project_text = f"{speech.get('project', '')} {speech.get('title', '')}"
            duration = 6 if re.search(r"ice\s*breaker|破冰", project_text, re.I) else 7
        else:
            duration = positive_int(minutes_value)
            if duration is None:
                errors.append(f"prepared speech {index} minutes must be a positive integer")
                duration = 7
        details = []
        if not is_unresolved(speech.get("title")):
            details.append(str(speech["title"]).strip())
        if not is_unresolved(speech.get("project")):
            details.append(str(speech["project"]).strip())
        label_override = speech.get("label")
        label = display_label("prepared_speech", language, label_override)
        label = f"{label} {index}"
        items.append(
            make_item(
                "prepared_speech",
                speaker,
                language,
                "first_half",
                item_id=f"prepared_speech:{index}",
                label=label,
                duration=duration,
                details=details,
                source="prepared_speech",
            )
        )
        evaluation_enabled = speech.get("evaluation_enabled", True)
        if not isinstance(evaluation_enabled, bool):
            errors.append(f"prepared speech {index} evaluation_enabled must be a boolean")
            evaluation_enabled = True
        if evaluation_enabled:
            evaluator = speech.get("evaluator")
            if is_unresolved(evaluator):
                errors.append(f"prepared speech {index} requires an evaluator but the name is unresolved")
            evaluation_minutes = speech.get("evaluation_minutes")
            if evaluation_minutes is None:
                evaluation_duration = 3
            else:
                evaluation_duration = positive_int(evaluation_minutes)
                if evaluation_duration is None:
                    errors.append(f"prepared speech {index} evaluation_minutes must be a positive integer")
                    evaluation_duration = 3
            eval_label = display_label("prepared_evaluation", language, speech.get("evaluation_label"))
            evaluation_items.append(
                make_item(
                    "prepared_evaluation",
                    evaluator,
                    language,
                    "second_half",
                    item_id=f"prepared_evaluation:{index}",
                    label=f"{eval_label} {index}",
                    duration=evaluation_duration,
                    details=details[:1],
                    source="prepared_speech",
                )
            )
        elif "evaluator" in speech and not is_unresolved(speech.get("evaluator")):
            errors.append(
                f"prepared speech {index} sets evaluation_enabled false but also supplies an evaluator"
            )

    impromptu = data.get("impromptu")
    table_topics_item: dict[str, Any] | None = None
    table_topics_evaluation_item: dict[str, Any] | None = None
    if impromptu is not None:
        if not isinstance(impromptu, dict):
            errors.append("impromptu must be an object or null")
        else:
            host = impromptu.get("host")
            if is_unresolved(host):
                errors.append("impromptu exists but its host is unresolved")
            minutes_value = impromptu.get("minutes")
            if minutes_value is None:
                tt_duration = None
                tt_locked = False
            else:
                tt_duration = positive_int(minutes_value)
                tt_locked = True
                if tt_duration is None:
                    errors.append("impromptu.minutes must be a positive integer")
                    tt_duration = 15
            table_topics_item = make_item(
                "table_topics",
                host,
                language,
                "first_half",
                duration=tt_duration,
                locked=tt_locked,
                preferred=15 if not tt_locked else None,
                details=impromptu.get("details"),
                source="impromptu",
            )
            items.append(table_topics_item)
            if "evaluator" in impromptu:
                evaluator = impromptu.get("evaluator")
                if is_unresolved(evaluator):
                    errors.append("impromptu requires an evaluator but the name is unresolved")
                evaluation_minutes = impromptu.get("evaluation_minutes")
                if evaluation_minutes is None:
                    eval_duration = None
                    eval_locked = False
                else:
                    eval_duration = positive_int(evaluation_minutes)
                    eval_locked = True
                    if eval_duration is None:
                        errors.append("impromptu.evaluation_minutes must be a positive integer")
                        eval_duration = 7
                table_topics_evaluation_item = make_item(
                    "table_topics_evaluation",
                    evaluator,
                    language,
                    "second_half",
                    duration=eval_duration,
                    locked=eval_locked,
                    preferred=None,
                    source="impromptu",
                )

    photo_break = standard("photo_break", photographer, "first_half", flexible=True)
    if photo_break:
        items.append(photo_break)

    items.extend(evaluation_items)
    if table_topics_evaluation_item:
        items.append(table_topics_evaluation_item)

    for role_id in reversed(present_functions):
        _, report_type = function_role_types[role_id]
        items.append(
            make_item(
                report_type,
                roles[role_id],
                language,
                "second_half",
                duration=DEFAULT_DURATIONS[report_type],
                source="role",
            )
        )

    sharing = standard("sharing", roles.get("sharing_host"), "closing", flexible=True)
    if sharing:
        items.append(sharing)

    if "general_evaluator" in roles:
        items.append(
            make_item(
                "general_evaluation",
                roles["general_evaluator"],
                language,
                "closing",
                duration=8,
                source="role",
            )
        )

    awards = standard("awards", roles.get("awards_host"), "closing")
    if awards:
        items.append(awards)
    closing = standard("president_closing", president, "closing")
    if closing:
        items.append(closing)

    specials = data.get("special_segments", [])
    if specials is None:
        specials = []
    if not isinstance(specials, list):
        errors.append("special_segments must be an array")
        specials = []
    last_anchor: dict[str, str] = {}
    for index, segment in enumerate(specials, start=1):
        if not isinstance(segment, dict):
            errors.append(f"special_segments[{index}] must be an object")
            continue
        title = segment.get("title")
        owner = segment.get("owner")
        duration = positive_int(segment.get("minutes"))
        if is_unresolved(title):
            errors.append(f"special segment {index} has unresolved title")
        if is_unresolved(owner):
            errors.append(f"special segment {index} has unresolved owner")
        if duration is None:
            errors.append(f"special segment {index} minutes must be a positive integer")
            duration = 1
        anchor = str(segment.get("after", "guest_introduction")).strip()
        anchor = last_anchor.get(anchor, anchor)
        anchor_index = next((i for i, item in enumerate(items) if item["id"] == anchor), None)
        if anchor_index is None:
            errors.append(f"special segment {index} references missing anchor: {anchor!r}")
            continue
        special_id = f"special:{index}"
        special = make_item(
            "special",
            owner,
            language,
            str(segment.get("section", items[anchor_index]["section"])),
            item_id=special_id,
            label=title,
            duration=duration,
            details=segment.get("details"),
            transition_after=segment.get("transition_after"),
            source="special",
        )
        items.insert(anchor_index + 1, special)
        original_anchor = str(segment.get("after", "guest_introduction")).strip()
        last_anchor[original_anchor] = special_id

    return items


def apply_transitions(items: list[dict[str, Any]], errors: list[str]) -> int:
    total = 0
    for index, item in enumerate(items):
        override = item.get("transition_after_override")
        if override is not None:
            transition = nonnegative_int(override)
            if transition is None:
                errors.append(f"{item['id']} transition_after must be a nonnegative integer")
                transition = 0
        elif index == len(items) - 1 or item["type"] in NO_TRANSITION_AFTER:
            transition = 0
        else:
            transition = 1
        item["transition_after"] = transition
        total += transition
    return total


def score_flexible_solution(
    actual: dict[str, int],
    table_topics_present: bool,
    table_topics_evaluation_present: bool,
) -> float:
    score = 0.0
    if table_topics_present and table_topics_evaluation_present:
        score += abs(actual["table_topics_evaluation"] - actual["table_topics"] / 2) * 20
    if "photo_break" in actual:
        score += (actual["photo_break"] - 5) ** 2
    if "sharing" in actual:
        score += (actual["sharing"] - 6) ** 2
    if "table_topics" in actual:
        score += (actual["table_topics"] - 15) ** 2 * 0.01
    return score


def solve_flexible(items: list[dict[str, Any]], target_item_minutes: int) -> bool:
    variables = [item for item in items if item.get("duration") is None]
    locked_total = sum(int(item["duration"]) for item in items if item.get("duration") is not None)
    required = target_item_minutes - locked_total
    if not variables:
        return required == 0
    if required < len(variables):
        return False

    by_type = {item["type"]: item for item in variables}
    tt_item = next((item for item in items if item["type"] == "table_topics"), None)
    eval_item = next((item for item in items if item["type"] == "table_topics_evaluation"), None)
    tt_variable = "table_topics" in by_type
    eval_variable = "table_topics_evaluation" in by_type

    tt_values = range(1, required + 1) if tt_variable else [None]
    eval_values = range(1, required + 1) if eval_variable else [None]
    remaining_types = [
        item_type for item_type in ("photo_break", "sharing") if item_type in by_type
    ]
    unsupported = [item["type"] for item in variables if item["type"] not in {
        "table_topics", "table_topics_evaluation", "photo_break", "sharing"
    }]
    if unsupported:
        return False

    best: tuple[float, dict[str, int]] | None = None
    for tt_value in tt_values:
        for eval_value in eval_values:
            assignment: dict[str, int] = {}
            used = 0
            if tt_variable:
                assignment["table_topics"] = int(tt_value)
                used += int(tt_value)
            if eval_variable:
                assignment["table_topics_evaluation"] = int(eval_value)
                used += int(eval_value)
            remainder = required - used
            if not remaining_types:
                if remainder != 0:
                    continue
            elif len(remaining_types) == 1:
                item_type = remaining_types[0]
                lower, upper = FLEX_BOUNDS[item_type]
                if not (lower <= remainder <= upper):
                    continue
                assignment[item_type] = remainder
            else:
                first, second = remaining_types
                first_pref = 5 if first == "photo_break" else 6
                second_pref = 5 if second == "photo_break" else 6
                first_min, first_max = FLEX_BOUNDS[first]
                second_min, second_max = FLEX_BOUNDS[second]
                feasible_min = max(first_min, remainder - second_max)
                feasible_max = min(first_max, remainder - second_min)
                if feasible_min > feasible_max:
                    continue
                first_value = round((remainder + first_pref - second_pref) / 2)
                first_value = max(feasible_min, min(feasible_max, first_value))
                assignment[first] = first_value
                assignment[second] = remainder - first_value

            actual: dict[str, int] = {}
            for item_type in ("table_topics", "table_topics_evaluation", "photo_break", "sharing"):
                item = next((row for row in items if row["type"] == item_type), None)
                if item is None:
                    continue
                if item_type in assignment:
                    actual[item_type] = assignment[item_type]
                else:
                    actual[item_type] = int(item["duration"])
            score = score_flexible_solution(
                actual,
                table_topics_present=tt_item is not None,
                table_topics_evaluation_present=eval_item is not None,
            )
            if best is None or score < best[0]:
                best = (score, assignment)

    if best is None:
        return False
    for item_type, duration in best[1].items():
        by_type[item_type]["duration"] = duration
        by_type[item_type]["computed_flexible"] = True
    return True


def fill_flexible_preferences(items: list[dict[str, Any]]) -> None:
    tt_duration: int | None = None
    for item in items:
        if item["type"] == "table_topics" and item.get("duration") is not None:
            tt_duration = int(item["duration"])
    for item in items:
        if item.get("duration") is not None:
            continue
        if item["type"] == "table_topics":
            item["duration"] = 15
            tt_duration = 15
        elif item["type"] == "table_topics_evaluation":
            item["duration"] = max(1, round((tt_duration or 15) / 2))
        else:
            item["duration"] = int(item.get("preferred_duration") or 1)


def validate_owners(items: list[dict[str, Any]], errors: list[str]) -> None:
    for item in items:
        if item.get("owner_required", True) and is_unresolved(item.get("owner")):
            errors.append(f"{item['label']} is missing its responsible person")


def validate_role_relationships(items: list[dict[str, Any]], warnings: list[str]) -> None:
    tt = next((item for item in items if item["type"] == "table_topics"), None)
    evaluation = next((item for item in items if item["type"] == "table_topics_evaluation"), None)
    if evaluation and not tt:
        warnings.append("table topics evaluation exists without a table topics session")
    if tt and evaluation and tt.get("duration") and evaluation.get("duration"):
        difference = abs(int(evaluation["duration"]) - int(tt["duration"]) / 2)
        if difference > 2:
            warnings.append(
                f"table topics evaluation is {evaluation['duration']} minutes while table topics is "
                f"{tt['duration']} minutes; confirm this intentional deviation"
            )


def assign_timeline(items: list[dict[str, Any]], start: int) -> int:
    cursor = start
    for item in items:
        item["start"] = format_clock(cursor)
        cursor += int(item["duration"])
        item["end"] = format_clock(cursor)
        cursor += int(item["transition_after"])
    return cursor


def build_agenda(
    data: dict[str, Any],
    source_dir: Path | None = None,
) -> tuple[dict[str, Any], list[str], list[str]]:
    normalized = deepcopy(data)
    errors: list[str] = []
    warnings: list[str] = []

    club = normalized.get("club")
    if not isinstance(club, dict):
        errors.append("club must be an object")
        club = {}
    for field in ("name", "default_location", "language"):
        if is_unresolved(club.get(field)):
            errors.append(f"club.{field} is required")
    language = str(club.get("language", "zh")).strip().lower()
    if language not in LANGUAGES:
        errors.append("club.language must be zh, en, or bilingual")
        language = "zh"
    meeting = normalized.get("meeting")
    if not isinstance(meeting, dict):
        errors.append("meeting must be an object")
        meeting = {}
    for field in ("number", "date", "start"):
        if is_unresolved(meeting.get(field)):
            errors.append(f"meeting.{field} is required")
    location = meeting.get("location", club.get("default_location"))
    if is_unresolved(location):
        errors.append("meeting location is unresolved")
    meeting["location"] = "" if location is None else str(location).strip()
    support_components = parse_support_components(
        meeting.get("support_components", club.get("support_components")),
        errors,
    )
    officers = (
        parse_officers(club.get("officers"), errors)
        if "officers" in support_components
        else []
    )
    club_intro = normalize_support_text(club.get("club_intro"))
    join_info = normalize_support_text(club.get("join_info"))
    if "club_intro" in support_components and not club_intro:
        errors.append("club_intro component is selected but club.club_intro is empty")
    if "join_info" in support_components and not join_info:
        errors.append("join_info component is selected but club.join_info is empty")
    resolved_source_dir = (source_dir or Path.cwd()).expanduser().resolve()
    vpm_qr_data = ""
    if "vpm_qr" in support_components:
        if is_unresolved(club.get("vpm_qr_image")):
            errors.append("vpm_qr component is selected but club.vpm_qr_image is missing")
        else:
            vpm_qr_data = resolve_support_image(
                club.get("vpm_qr_image"),
                resolved_source_dir,
                errors,
                "club.vpm_qr_image",
            )
    voting_qr_data = ""
    if "voting_qr" in support_components:
        if is_unresolved(meeting.get("voting_qr_image")):
            errors.append(
                "voting_qr component is selected but meeting.voting_qr_image is missing"
            )
        else:
            voting_qr_data = resolve_support_image(
                meeting.get("voting_qr_image"),
                resolved_source_dir,
                errors,
                "meeting.voting_qr_image",
            )

    try:
        start = parse_clock(meeting.get("start"))
    except ValueError as exc:
        errors.append(str(exc))
        start = 0
    if is_unresolved(meeting.get("end")):
        declared_end = start + 120
        meeting["end"] = format_clock(declared_end)
    else:
        try:
            declared_end = parse_clock(meeting.get("end"))
            if declared_end == start:
                errors.append("meeting.end must differ from meeting.start")
                declared_end = start + 120
            elif declared_end < start:
                declared_end += 24 * 60
        except ValueError as exc:
            errors.append(str(exc))
            declared_end = start + 120
    declared_window = declared_end - start
    if declared_window > 360:
        errors.append(
            f"meeting window is {declared_window} minutes; use a window of 360 minutes or less"
        )
    if declared_window != 120:
        warnings.append(f"current meeting window is {declared_window} minutes, not the 120-minute default")

    approved_overtime = meeting.get("approved_overtime_minutes", 0)
    if nonnegative_int(approved_overtime) is None:
        errors.append("meeting.approved_overtime_minutes must be a nonnegative integer")
        approved_overtime = 0
    role_order, roles = parse_roles(normalized.get("roles"), errors)
    backstage = parse_backstage(normalized.get("backstage"), errors)
    overrides = parse_overrides(normalized.get("standard_overrides"), errors)
    items = build_items(
        normalized,
        language,
        meeting,
        role_order,
        roles,
        backstage,
        overrides,
        errors,
    )
    validate_owners(items, errors)
    transition_minutes = apply_transitions(items, errors)
    target_item_minutes = declared_window - transition_minutes
    solved = solve_flexible(items, target_item_minutes)
    if not solved:
        fill_flexible_preferences(items)

    total_item_minutes = sum(int(item["duration"]) for item in items)
    total_minutes = total_item_minutes + transition_minutes
    delta = total_minutes - declared_window
    if delta > 0:
        if int(approved_overtime) != delta:
            errors.append(
                f"timeline overruns the declared meeting window by {delta} minutes; "
                f"approved_overtime_minutes is {approved_overtime}. Ask the user to approve exactly "
                f"{delta} minutes or reduce content"
            )
    elif delta < 0:
        errors.append(
            f"timeline has {abs(delta)} unexplained minutes remaining; "
            "adjust the flexible sessions or add an explicit buffer"
        )
    elif int(approved_overtime) > 0:
        errors.append(
            "approved_overtime_minutes no longer matches a current overrun; reset it to 0 and "
            "reconfirm any later overrun"
        )

    final_cursor = assign_timeline(items, start)
    validate_role_relationships(items, warnings)
    effective_window = declared_window + int(approved_overtime)
    page_item_limit = 20 if language == "bilingual" else 23
    timeline_page_count = max(1, (len(items) + page_item_limit - 1) // page_item_limit)
    estimated_page_count = timeline_page_count + (1 if support_components else 0)

    computed = {
        "status": (
            "exact_with_approved_overtime"
            if delta > 0 and int(approved_overtime) == delta and not errors
            else "exact"
            if delta == 0 and not errors
            else "needs_confirmation"
        ),
        "declared_window_minutes": declared_window,
        "approved_overtime_minutes": int(approved_overtime),
        "effective_window_minutes": effective_window,
        "item_minutes": total_item_minutes,
        "transition_minutes": transition_minutes,
        "total_minutes": total_minutes,
        "delta_minutes": delta,
        "start": format_clock(start),
        "declared_end": format_clock(declared_end),
        "final_end": format_clock(final_cursor),
        "row_count": len(items),
        "page_count": estimated_page_count,
    }

    result = {
        "schema_version": 2,
        "club": {
            "name": str(club.get("name", "")).strip(),
            "default_location": str(club.get("default_location", "")).strip(),
            "language": language,
            "support_components": support_components,
            "officers": officers,
            "club_intro": club_intro,
            "join_info": join_info,
            "vpm_qr_present": bool(vpm_qr_data),
        },
        "meeting": {
            key: meeting.get(key)
            for key in (
                "number",
                "date",
                "start",
                "end",
                "location",
                "theme",
                "word_of_day",
                "manager",
                "president",
                "approved_overtime_minutes",
            )
            if key in meeting
        },
        "timeline": items,
        "backstage": backstage,
        "computed": computed,
        "warnings": warnings,
        "support_components": support_components,
        "_assets": {
            "vpm_qr_data_uri": vpm_qr_data,
            "voting_qr_data_uri": voting_qr_data,
        },
    }
    result["meeting"]["voting_qr_present"] = bool(voting_qr_data)
    return result, errors, warnings


def render_markdown(result: dict[str, Any]) -> str:
    club = result["club"]
    meeting = result["meeting"]
    computed = result["computed"]
    language = club["language"]
    if language == "en":
        title = f"# {club['name']} · Meeting {meeting.get('number', '')} Agenda"
        labels = {
            "theme": "Theme",
            "date": "Date",
            "time": "Time",
            "location": "Location",
            "word": "Word of the Day",
            "manager": "Meeting Manager",
            "time_col": "Time",
            "agenda": "Agenda",
            "owner": "Role Taker",
            "duration": "Duration",
            "backstage": "Backstage Team",
            "summary": "Time check",
        }
    elif language == "bilingual":
        title = f"# {club['name']} · 第 {meeting.get('number', '')} 期 / Meeting {meeting.get('number', '')} Agenda"
        labels = {
            "theme": "主题 / Theme",
            "date": "日期 / Date",
            "time": "时间 / Time",
            "location": "地点 / Location",
            "word": "今日一词 / Word of the Day",
            "manager": "会议经理 / Meeting Manager",
            "time_col": "时间 / Time",
            "agenda": "会议流程 / Agenda",
            "owner": "负责人 / Role Taker",
            "duration": "时长 / Duration",
            "backstage": "幕后团队 / Backstage Team",
            "summary": "时间校验 / Time check",
        }
    else:
        title = f"# {club['name']} · 第 {meeting.get('number', '')} 期会单"
        labels = {
            "theme": "主题",
            "date": "日期",
            "time": "时间",
            "location": "地点",
            "word": "今日一词",
            "manager": "会议经理",
            "time_col": "时间",
            "agenda": "会议流程",
            "owner": "负责人",
            "duration": "时长",
            "backstage": "幕后团队",
            "summary": "时间校验",
        }

    lines = [title, ""]
    metadata = [
        (labels["theme"], meeting.get("theme")),
        (labels["date"], meeting.get("date")),
        (labels["time"], f"{computed['start']}-{computed['final_end']}"),
        (labels["location"], meeting.get("location")),
        (labels["word"], meeting.get("word_of_day")),
        (labels["manager"], meeting.get("manager")),
    ]
    for label, value in metadata:
        if not is_unresolved(value):
            lines.append(f"- {label}：{value}")
    lines.extend(
        [
            "",
            f"| {labels['time_col']} | {labels['agenda']} | {labels['owner']} | {labels['duration']} |",
            "|---|---|---|---:|",
        ]
    )
    last_section = None
    for item in result["timeline"]:
        current_section = section_label(item["section"], language)
        if current_section != last_section:
            lines.append(f"|  | **{current_section}** |  |  |")
            last_section = current_section
        details = "<br>".join(item.get("details", []))
        activity = item["label"] + (f"<br><small>{details}</small>" if details else "")
        lines.append(
            f"| {item['start']}-{item['end']} | {activity} | {item['owner']} | "
            f"{item['duration']} min |"
        )
    lines.extend(
        [
            "",
            f"**{labels['summary']}：** {computed['item_minutes']} min + "
            f"{computed['transition_minutes']} min transitions = {computed['total_minutes']} min；"
            f"{computed['start']}-{computed['final_end']}。",
        ]
    )
    if result["backstage"]:
        backstage_text = " · ".join(
            f"{row['label']}：{row['person']}" for row in result["backstage"]
        )
        lines.extend(["", f"**{labels['backstage']}：** {backstage_text}"])
    support_components = result.get("support_components", [])
    if support_components:
        lines.extend(
            [
                "",
                f"## {localized('固定信息组件', 'Support Components', language)}",
            ]
        )
    if "timer_rules" in support_components:
        lines.extend(
            [
                "",
                f"### {localized('时间官规则', 'Timer Rules', language)}",
                "",
                f"| {localized('演讲时长', 'Speech length', language)} | "
                f"{localized('绿牌', 'Green', language)} | "
                f"{localized('黄牌', 'Yellow', language)} | "
                f"{localized('红牌', 'Red', language)} | "
                f"{localized('响铃', 'Bell', language)} |",
                "|---|---|---|---|---|",
            ]
        )
        for row in TIMER_RULES:
            lines.append(
                f"| {localized(row['band_zh'], row['band_en'], language)} | "
                f"{localized(row['green_zh'], row['green_en'], language)} | "
                f"{localized(row['yellow_zh'], row['yellow_en'], language)} | "
                f"{localized(row['red_zh'], row['red_en'], language)} | "
                f"{localized(row['bell_zh'], row['bell_en'], language)} |"
            )
    if "toastmasters_intro" in support_components:
        lines.extend(
            [
                "",
                f"### {localized('头马国际演讲会', 'Toastmasters International', language)}",
                "",
                toastmasters_intro(language),
            ]
        )
    if "meeting_boundaries" in support_components:
        lines.extend(
            [
                "",
                f"### {localized('会议秩序与内容边界', 'Meeting Conduct & Content Boundaries', language)}",
                "",
                f"- {localized('安静：会议过程中保持安静，手机调至静音或震动。', 'Quiet: keep phones silent or on vibrate during the meeting.', language)}",
                f"- {localized('四类禁忌：演讲不涉及政治、宗教、色情或传销。', 'Four boundaries: avoid politics, religion, pornography and pyramid selling.', language)}",
                f"- {localized('整洁：结束后带走个人物品与垃圾。', 'Clean: take personal belongings and rubbish when leaving.', language)}",
            ]
        )
    if "officers" in support_components:
        lines.extend(
            [
                "",
                f"### {localized('当届官员团队', 'Current Officer Team', language)}",
                "",
                f"| {localized('职务', 'Role', language)} | {localized('姓名', 'Name', language)} |",
                "|---|---|",
            ]
        )
        for officer in result["club"]["officers"]:
            lines.append(f"| {officer['role']} | {officer['name']} |")
    if "club_intro" in support_components:
        lines.extend(
            [
                "",
                f"### {localized('俱乐部介绍', 'About the Club', language)}",
                "",
                *[f"- {line}" for line in result["club"]["club_intro"]],
            ]
        )
    if "join_info" in support_components:
        lines.extend(
            [
                "",
                f"### {localized('如何入会', 'How to Join', language)}",
                "",
                *[f"- {line}" for line in result["club"]["join_info"]],
            ]
        )
    if "vpm_qr" in support_components:
        lines.extend(
            [
                "",
                f"- {localized('VPM 入会二维码：见会单附页。', 'VPM joining QR: see the support page.', language)}",
            ]
        )
    if "voting_qr" in support_components:
        lines.extend(
            [
                "",
                f"- {localized('本期投票二维码：见会单附页。', 'Meeting voting QR: see the support page.', language)}",
            ]
        )
    return "\n".join(lines) + "\n"


def image_data_uri(path: Path) -> str:
    if not path.is_file():
        return ""
    mime = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".svg": "image/svg+xml",
    }.get(path.suffix.lower())
    if not mime:
        raise ValueError(f"unsupported image format: {path.suffix}")
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def resolve_support_image(
    value: Any,
    source_dir: Path,
    errors: list[str],
    label: str,
) -> str:
    if is_unresolved(value):
        return ""
    path = Path(str(value)).expanduser()
    if not path.is_absolute():
        path = source_dir / path
    path = path.resolve()
    if not path.is_file():
        errors.append(f"{label} does not exist: {path}")
        return ""
    try:
        return image_data_uri(path)
    except (OSError, ValueError) as exc:
        errors.append(f"{label}: {exc}")
        return ""


def render_html(result: dict[str, Any]) -> str:
    club = result["club"]
    meeting = result["meeting"]
    computed = result["computed"]
    language = club["language"]
    logo = image_data_uri(DEFAULT_LOGO)
    row_count = len(result["timeline"])
    page_item_limit = 20 if language == "bilingual" else 23
    timeline_pages = [
        result["timeline"][index : index + page_item_limit]
        for index in range(0, row_count, page_item_limit)
    ] or [[]]
    support_components = result.get("support_components", [])
    max_page_rows = max(len(page) for page in timeline_pages)
    density = "ultra" if max_page_rows >= 22 else "compact" if max_page_rows >= 18 else "normal"

    meta_parts = [
        str(meeting.get("date", "")).strip(),
        f"{computed['start']}-{computed['final_end']}",
        str(meeting.get("location", "")).strip(),
    ]
    meta = " · ".join(html.escape(part) for part in meta_parts if part)
    meeting_number = html.escape(str(meeting.get("number", "")))
    if language == "en":
        kicker = f"Meeting {meeting_number}"
    elif language == "bilingual":
        kicker = f"第 {meeting_number} 期 / Meeting {meeting_number}"
    else:
        kicker = f"第 {meeting_number} 期例会"
    theme = html.escape(str(meeting.get("theme", "")).strip())
    word = html.escape(str(meeting.get("word_of_day", "")).strip())
    manager = html.escape(str(meeting.get("manager", "")).strip())

    backstage = " · ".join(
        f"{html.escape(row['label'])}：{html.escape(row['person'])}"
        for row in result["backstage"]
    )
    if language == "en":
        backstage_label = "Backstage Team"
        time_label = "Time check"
        word_label = "Word of the Day"
        manager_label = "Meeting Manager"
        table_headers = ("Time", "Agenda", "Role Taker", "Duration")
    elif language == "bilingual":
        backstage_label = "幕后团队 / Backstage Team"
        time_label = "时间闭环 / Time check"
        word_label = "今日一词 / Word of the Day"
        manager_label = "会议经理 / Meeting Manager"
        table_headers = (
            "时间 / Time",
            "会议流程 / Agenda",
            "负责人 / Role Taker",
            "时长 / Duration",
        )
    else:
        backstage_label = "幕后团队"
        time_label = "时间闭环"
        word_label = "今日一词"
        manager_label = "会议经理"
        table_headers = ("时间", "会议流程", "负责人", "时长")
    website = "toastmasters.org"

    def page_rows(page_items: list[dict[str, Any]]) -> str:
        rows: list[str] = []
        last_section = None
        for item in page_items:
            current_section = section_label(item["section"], language)
            if current_section != last_section:
                rows.append(
                    f'<tr class="section-row"><td colspan="4">{html.escape(current_section)}</td></tr>'
                )
                last_section = current_section
            details = " · ".join(html.escape(value) for value in item.get("details", []))
            detail_html = f'<div class="detail">{details}</div>' if details else ""
            rows.append(
                "<tr>"
                f'<td class="time">{html.escape(item["start"])}</td>'
                f'<td class="activity">{html.escape(item["label"])}{detail_html}</td>'
                f'<td class="owner">{html.escape(item["owner"])}</td>'
                f'<td class="duration">{item["duration"]} min</td>'
                "</tr>"
            )
        return "".join(rows)

    page_blocks: list[str] = []
    total_pages = len(timeline_pages) + (1 if support_components else 0)
    for page_index, page_items in enumerate(timeline_pages, start=1):
        page_marker = f"{page_index}/{total_pages}"
        sparse_class = " sparse-page" if len(page_items) < 12 else ""
        page_blocks.append(
            f"""
<main class="page {density} lang-{html.escape(language)}{sparse_class}">
  <header class="hero">
    {"<img class='logo' src='" + logo + "' alt='Toastmasters International'>" if logo else "<div class='logo-fallback'>TOASTMASTERS<br>INTERNATIONAL</div>"}
    <div>
      <div class="club">{html.escape(club['name'])}</div>
      <div class="kicker">{kicker}</div>
      <div class="theme">{theme}</div>
      <div class="meta">{meta}</div>
    </div>
  </header>
  <div class="chips">
    <div class="chip"><strong>{word_label}</strong> · {word or "—"}</div>
    <div class="chip"><strong>{manager_label}</strong> · {manager or "—"}</div>
  </div>
  <section class="timeline">
    <table>
      <thead><tr><th>{table_headers[0]}</th><th>{table_headers[1]}</th><th>{table_headers[2]}</th><th>{table_headers[3]}</th></tr></thead>
      <tbody>{page_rows(page_items)}</tbody>
    </table>
  </section>
  <footer class="footer">
    <div class="backstage"><strong>{backstage_label}</strong> · {backstage or "—"}</div>
    <div class="timecheck"><strong>{time_label}</strong> · {computed['item_minutes']} + {computed['transition_minutes']} = {computed['total_minutes']} min</div>
    <div class="site">{website} · {page_marker}</div>
  </footer>
</main>"""
        )

    if support_components:
        support_cards: list[str] = []

        def support_card(title: str, body: str, wide: bool = False) -> str:
            card_class = "support-card wide" if wide else "support-card"
            return (
                f'<article class="{card_class}">'
                f'<h2>{html.escape(title)}</h2>{body}</article>'
            )

        for component in support_components:
            if component in {"vpm_qr", "voting_qr"}:
                continue
            if component == "timer_rules":
                timer_rows = []
                for row in TIMER_RULES:
                    timer_rows.append(
                        "<tr>"
                        f"<td>{html.escape(localized(row['band_zh'], row['band_en'], language))}</td>"
                        f"<td>{html.escape(localized(row['green_zh'], row['green_en'], language))}</td>"
                        f"<td>{html.escape(localized(row['yellow_zh'], row['yellow_en'], language))}</td>"
                        f"<td>{html.escape(localized(row['red_zh'], row['red_en'], language))}</td>"
                        f"<td>{html.escape(localized(row['bell_zh'], row['bell_en'], language))}</td>"
                        "</tr>"
                    )
                timer_body = (
                    '<table class="timer-table"><thead><tr>'
                    f"<th>{html.escape(localized('演讲时长', 'Speech length', language))}</th>"
                    f"<th>{html.escape(localized('绿牌', 'Green', language))}</th>"
                    f"<th>{html.escape(localized('黄牌', 'Yellow', language))}</th>"
                    f"<th>{html.escape(localized('红牌', 'Red', language))}</th>"
                    f"<th>{html.escape(localized('响铃', 'Bell', language))}</th>"
                    f"</tr></thead><tbody>{''.join(timer_rows)}</tbody></table>"
                )
                support_cards.append(
                    support_card(
                        localized("时间官规则", "Timer Rules", language),
                        timer_body,
                        wide=True,
                    )
                )
            elif component == "toastmasters_intro":
                support_cards.append(
                    support_card(
                        localized(
                            "头马国际演讲会",
                            "Toastmasters International",
                            language,
                        ),
                        f"<p>{html.escape(toastmasters_intro(language))}</p>",
                    )
                )
            elif component == "meeting_boundaries":
                boundaries = [
                    localized(
                        "安静：会议过程中保持安静，手机调至静音或震动。",
                        "Quiet: keep phones silent or on vibrate during the meeting.",
                        language,
                    ),
                    localized(
                        "四类禁忌：演讲不涉及政治、宗教、色情或传销。",
                        "Four boundaries: avoid politics, religion, pornography and pyramid selling.",
                        language,
                    ),
                    localized(
                        "整洁：结束后带走个人物品与垃圾。",
                        "Clean: take personal belongings and rubbish when leaving.",
                        language,
                    ),
                ]
                support_cards.append(
                    support_card(
                        localized(
                            "会议秩序与内容边界",
                            "Meeting Conduct & Content Boundaries",
                            language,
                        ),
                        "<ul>" + "".join(f"<li>{html.escape(line)}</li>" for line in boundaries) + "</ul>",
                    )
                )
            elif component == "officers":
                officer_rows = "".join(
                    f"<div><strong>{html.escape(row['role'])}</strong><span>{html.escape(row['name'])}</span></div>"
                    for row in club["officers"]
                )
                support_cards.append(
                    support_card(
                        localized("当届官员团队", "Current Officer Team", language),
                        f'<div class="officer-list">{officer_rows}</div>',
                    )
                )
            elif component == "club_intro":
                support_cards.append(
                    support_card(
                        localized("俱乐部介绍", "About the Club", language),
                        "<ul>"
                        + "".join(
                            f"<li>{html.escape(line)}</li>" for line in club["club_intro"]
                        )
                        + "</ul>",
                    )
                )
            elif component == "join_info":
                support_cards.append(
                    support_card(
                        localized("如何入会", "How to Join", language),
                        "<ul>"
                        + "".join(
                            f"<li>{html.escape(line)}</li>" for line in club["join_info"]
                        )
                        + "</ul>",
                    )
                )

        qr_items: list[str] = []
        assets = result.get("_assets", {})
        if "vpm_qr" in support_components:
            qr_items.append(
                '<div class="qr-item">'
                f'<img src="{html.escape(assets.get("vpm_qr_data_uri", ""), quote=True)}" alt="VPM QR">'
                f"<strong>{html.escape(localized('入会咨询', 'Join Us', language))}</strong>"
                "</div>"
            )
        if "voting_qr" in support_components:
            qr_items.append(
                '<div class="qr-item">'
                f'<img src="{html.escape(assets.get("voting_qr_data_uri", ""), quote=True)}" alt="Voting QR">'
                f"<strong>{html.escape(localized('本期投票', 'Meeting Vote', language))}</strong>"
                "</div>"
            )
        if qr_items:
            support_cards.append(
                support_card(
                    localized("二维码", "QR Codes", language),
                    f'<div class="qr-grid">{"".join(qr_items)}</div>',
                    wide=True,
                )
            )

        support_page_marker = f"{total_pages}/{total_pages}"
        support_theme = localized("会单信息组件", "Agenda Information", language)
        page_blocks.append(
            f"""
<main class="page support-page lang-{html.escape(language)}">
  <header class="hero">
    {"<img class='logo' src='" + logo + "' alt='Toastmasters International'>" if logo else "<div class='logo-fallback'>TOASTMASTERS<br>INTERNATIONAL</div>"}
    <div>
      <div class="club">{html.escape(club['name'])}</div>
      <div class="kicker">{kicker}</div>
      <div class="theme">{html.escape(support_theme)}</div>
      <div class="meta">{meta}</div>
    </div>
  </header>
  <section class="support-grid">{"".join(support_cards)}</section>
  <footer class="footer support-footer">
    <div><strong>{html.escape(localized('信息附页', 'Information Page', language))}</strong></div>
    <div class="timecheck">{website}</div>
    <div class="site">{support_page_marker}</div>
  </footer>
</main>"""
        )

    return f"""<!doctype html>
<html lang="{html.escape(language)}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="agenda-page-count" content="{total_pages}">
<title>{html.escape(club['name'])} · {kicker}</title>
<style>
@page {{ size: A4 portrait; margin: 0; }}
* {{ box-sizing: border-box; }}
html, body {{ margin: 0; padding: 0; background: #e8edf0; color: #15344a; font-family: Arial, "PingFang SC", "Microsoft YaHei", sans-serif; }}
.page {{ width: 210mm; height: 297mm; margin: 0 auto; overflow: hidden; background: #fffdf8; padding: 9mm 10mm 7mm; display: flex; flex-direction: column; }}
.page + .page {{ margin-top: 8mm; }}
.hero {{ background: #004165; color: white; border-radius: 6mm; padding: 6mm 7mm 5mm; display: grid; grid-template-columns: 26mm 1fr; gap: 6mm; align-items: center; border-bottom: 2mm solid #F2DF74; }}
.logo {{ width: 24mm; height: 24mm; object-fit: contain; }}
.logo-fallback {{ width: 24mm; height: 24mm; border: .4mm solid rgba(255,255,255,.65); border-radius: 50%; display: grid; place-items: center; font-weight: 800; font-size: 9px; text-align: center; }}
.club {{ font-size: 5.7mm; font-weight: 800; line-height: 1.08; letter-spacing: .1mm; }}
.kicker {{ margin-top: 1.5mm; color: #F2DF74; font-size: 3.8mm; font-weight: 800; }}
.theme {{ margin-top: 1.2mm; font-size: 7.2mm; font-weight: 900; color: #fff; line-height: 1.05; }}
.meta {{ margin-top: 2mm; font-size: 3.1mm; color: rgba(255,255,255,.92); }}
.chips {{ display: flex; gap: 3mm; margin: 3mm 0; }}
.chip {{ flex: 1; border: .35mm solid #d3dadd; border-radius: 99mm; padding: 1.6mm 3mm; font-size: 3mm; background: white; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
.chip strong {{ color: #772432; }}
.timeline {{ flex: 1; min-height: 0; border: .4mm solid #d5dde1; border-radius: 3mm; overflow: hidden; background: white; }}
table {{ width: 100%; height: 100%; border-collapse: collapse; table-layout: fixed; }}
.sparse-page table {{ height: auto; }}
thead th {{ background: #772432; color: white; font-size: 3mm; padding: 1.5mm 1.6mm; text-align: left; }}
thead th:nth-child(1) {{ width: 20mm; }}
thead th:nth-child(3) {{ width: 32mm; }}
thead th:nth-child(4) {{ width: 18mm; text-align: right; }}
tbody td {{ border-bottom: .25mm solid #dfe5e8; padding: 1.25mm 1.6mm; font-size: 2.8mm; line-height: 1.15; vertical-align: middle; }}
tbody tr:last-child td {{ border-bottom: 0; }}
.section-row td {{ background: #eaf1f4; color: #004165; font-weight: 900; padding: 1mm 1.6mm; font-size: 2.75mm; letter-spacing: .2mm; }}
.time {{ color: #b17b00; font-weight: 900; }}
.activity {{ font-weight: 750; }}
.detail {{ margin-top: .45mm; color: #62727d; font-size: 2.25mm; font-weight: 400; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
.owner {{ color: #004165; font-weight: 700; }}
.duration {{ text-align: right; color: #5a6670; white-space: nowrap; }}
.footer {{ margin-top: 3mm; background: #004165; color: white; border-radius: 3mm; padding: 2.2mm 3mm; display: grid; grid-template-columns: minmax(0,1.7fr) minmax(0,1fr) auto; gap: 3mm; align-items: center; font-size: 2.6mm; }}
.footer strong {{ color: #F2DF74; }}
.backstage {{ white-space: normal; overflow: visible; line-height: 1.18; }}
.timecheck {{ white-space: nowrap; }}
.site {{ color: #F2DF74; font-weight: 800; }}
.lang-bilingual .footer {{ font-size: 2.2mm; }}
.compact tbody td {{ padding-top: 1mm; padding-bottom: 1mm; font-size: 2.55mm; }}
.compact .section-row td {{ padding-top: .8mm; padding-bottom: .8mm; font-size: 2.5mm; }}
.compact .detail {{ font-size: 2.05mm; }}
.ultra tbody td {{ padding-top: .72mm; padding-bottom: .72mm; font-size: 2.35mm; }}
.ultra .section-row td {{ padding-top: .62mm; padding-bottom: .62mm; font-size: 2.3mm; }}
.ultra .detail {{ font-size: 1.9mm; }}
.support-grid {{ flex: 1; min-height: 0; margin-top: 3mm; display: grid; grid-template-columns: 1fr 1fr; gap: 3mm; align-content: start; }}
.support-card {{ border: .35mm solid #d5dde1; border-radius: 3mm; background: white; padding: 3mm; font-size: 2.55mm; line-height: 1.35; }}
.support-card.wide {{ grid-column: 1 / -1; }}
.support-card h2 {{ margin: 0 0 1.6mm; color: #772432; font-size: 3.5mm; line-height: 1.15; }}
.support-card p {{ margin: 0; }}
.support-card ul {{ margin: 0; padding-left: 4.5mm; }}
.support-card li + li {{ margin-top: .8mm; }}
.support-page table {{ height: auto; }}
.timer-table th, .timer-table td {{ width: auto !important; padding: 1.2mm; border: .25mm solid #dfe5e8; font-size: 2.35mm; text-align: left; }}
.timer-table th {{ background: #004165; color: white; }}
.officer-list {{ display: grid; gap: .7mm; }}
.officer-list div {{ display: grid; grid-template-columns: 1fr 1.2fr; gap: 2mm; padding-bottom: .5mm; border-bottom: .2mm solid #e5eaed; }}
.officer-list div:last-child {{ border-bottom: 0; }}
.officer-list span {{ color: #004165; font-weight: 700; }}
.qr-grid {{ display: flex; justify-content: center; gap: 12mm; }}
.qr-item {{ display: grid; justify-items: center; gap: 1.2mm; color: #004165; }}
.qr-item img {{ width: 30mm; height: 30mm; object-fit: contain; image-rendering: auto; }}
.support-footer {{ margin-top: 3mm; }}
.lang-bilingual .support-card {{ font-size: 2.25mm; }}
.lang-bilingual .support-card h2 {{ font-size: 3.1mm; }}
@media print {{
  html, body {{ background: white; }}
  .page {{ margin: 0; page-break-after: always; break-after: page; }}
  .page + .page {{ margin-top: 0; }}
  .page:last-child {{ page-break-after: auto; break-after: auto; }}
}}
</style>
</head>
<body>{''.join(page_blocks)}</body>
</html>
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_json", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("output"))
    parser.add_argument("--profile", type=Path, default=None)
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()

    input_path = args.input_json.expanduser().resolve()
    if not input_path.is_file():
        parser.error(f"input JSON does not exist: {input_path}")
    try:
        data = load_json(input_path)
        if args.profile:
            profile_path = args.profile.expanduser().resolve()
            data = deep_merge(load_json(profile_path), data)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "errors": [str(exc)]}, ensure_ascii=False, indent=2), file=sys.stderr)
        raise SystemExit(2)

    result, errors, warnings = build_agenda(data, source_dir=input_path.parent)
    summary = {
        "ok": not errors,
        "computed": result["computed"],
        "warnings": warnings,
        "errors": errors,
    }
    if args.validate_only:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        raise SystemExit(0 if not errors else 2)

    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    diagnostics_path = output_dir / "agenda.diagnostics.json"
    diagnostics_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    if errors:
        print(json.dumps(summary, ensure_ascii=False, indent=2), file=sys.stderr)
        raise SystemExit(2)

    computed_path = output_dir / "agenda.computed.json"
    markdown_path = output_dir / "agenda.md"
    html_path = output_dir / "agenda.html"
    computed_result = deepcopy(result)
    computed_result.pop("_assets", None)
    computed_path.write_text(
        json.dumps(computed_result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    markdown_path.write_text(render_markdown(result), encoding="utf-8")
    html_path.write_text(render_html(result), encoding="utf-8")

    print(
        json.dumps(
            {
                **summary,
                "outputs": {
                    "computed_json": str(computed_path),
                    "markdown": str(markdown_path),
                    "html": str(html_path),
                    "diagnostics": str(diagnostics_path),
                },
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
