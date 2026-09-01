#!/usr/bin/env python3
"""Render deterministic editorial reference cases for human visual review."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable


SKILL_ROOT = Path(__file__).resolve().parent.parent
EXAMPLE_PATH = SKILL_ROOT / "examples" / "meeting.example.json"
BUILD_SCRIPT = SKILL_ROOT / "scripts" / "build_agenda.py"
EXPORT_SCRIPT = SKILL_ROOT / "scripts" / "export_a4.py"


def base_meeting() -> dict[str, Any]:
    return json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))


def add_four_support_panels(data: dict[str, Any]) -> dict[str, Any]:
    data["club"]["custom_support_blocks"] = [
        {
            "id": "optional_sessions",
            "title": "可选环节",
            "lines": ["主题演讲", "评估环节", "语言项目演练", "专题工作坊", "会员时刻分享"],
        },
        {
            "id": "club_facts",
            "title": "俱乐部信息",
            "lines": [
                "定位：助力会员提升沟通力与AI时代职场竞争力的实践平台",
                "愿景：帮助会员提高AI时代下的职场竞争力",
                "特色：能玩能卷、最懂AI的俱乐部",
                "关键词：有成长、有温暖、有乐趣",
                "价值观：正直、尊重、服务、卓越",
            ],
        },
    ]
    return data


def standard_four() -> dict[str, Any]:
    return add_four_support_panels(base_meeting())


def standard_two() -> dict[str, Any]:
    return base_meeting()


def long_chinese() -> dict[str, Any]:
    data = add_four_support_panels(base_meeting())
    data["club"]["name"] = "星河城市人工智能与领导力头马演讲俱乐部"
    data["club"]["default_location"] = "未来科技中心A座18楼国际会议厅"
    data["meeting"]["location"] = data["club"]["default_location"]
    data["meeting"]["word_of_day"] = "长期主义"
    data["meeting"]["visual_theme"] = "technology"
    return data


def english_long() -> dict[str, Any]:
    data = base_meeting()
    data["club"]["name"] = "Starlight Leadership Advanced Toastmasters Club"
    data["club"]["language"] = "en"
    data["club"]["default_location"] = "Global Innovation Center, Conference Room 1808"
    data["meeting"]["location"] = data["club"]["default_location"]
    data["meeting"]["theme"] = "Speak with clarity and courage"
    data["meeting"]["word_of_day"] = "Stewardship"
    data["meeting"]["visual_theme"] = "technology"
    data["meeting"]["manager"] = "Alex Morgan"
    data["meeting"]["president"] = "Jordan Lee"
    role_names = {
        "rules_host": "Taylor Reed",
        "toastmaster": "Alex Morgan",
        "timer": "Casey Young",
        "ah_counter": "Morgan Chen",
        "grammarian": "Jamie Lin",
        "guest_host": "Riley Park",
        "sharing_host": "Avery Stone",
        "general_evaluator": "Jordan Lee",
        "awards_host": "Taylor Reed",
    }
    for role in data["roles"]:
        role["person"] = role_names[role["id"]]
    data["prepared_speeches"] = [
        {
            "speaker": f"Speaker {index}",
            "title": f"Speech {index}",
            "project": "Presentation Mastery",
            "evaluator": f"Evaluator {index}",
        }
        for index in range(1, 4)
    ]
    data["impromptu"] = {
        "host": "Table Topics Host",
        "evaluator": "Table Topics Evaluator",
    }
    officer_names = (
        "Jordan Lee",
        "Alex Morgan",
        "Taylor Reed",
        "Jamie Lin",
        "Morgan Chen",
        "Casey Young",
        "Riley Park",
    )
    for officer, name in zip(data["club"]["officers"], officer_names):
        officer["name"] = name
    data["backstage"] = [
        {"id": "photographer", "person": "Member J", "label": "Photographer"},
        {"id": "slides", "person": "Member B", "label": "Slides/PPT"},
        {"id": "voting", "person": "Member E", "label": "Voting Link"},
    ]
    data["club"]["custom_support_blocks"] = [
        {
            "id": "optional_sessions",
            "title": "Options",
            "lines": ["Theme speech", "Evaluation", "Language practice"],
        },
        {
            "id": "club_facts",
            "title": "Club Profile",
            "lines": [
                "Positioning: practical communication and leadership",
                "Vision: help members grow with confidence",
                "Character: rigorous, warm and engaging",
                "Keyword: co-creation",
                "Values: integrity, respect, service and excellence",
            ],
        },
    ]
    return data


CASES: tuple[tuple[str, Callable[[], dict[str, Any]]], ...] = (
    ("01-standard-four-panels", standard_four),
    ("02-standard-two-panels", standard_two),
    ("03-long-chinese-technology", long_chinese),
    ("04-english-long", english_long),
)


def validate_output_root(path: Path) -> None:
    if path == Path(path.anchor) or path == Path.home() or len(path.parts) < 4:
        raise ValueError(f"refusing unsafe visual gallery output path: {path}")


def run(command: list[str]) -> None:
    subprocess.run(command, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    output_root = args.output_dir.expanduser().resolve()
    validate_output_root(output_root)
    if output_root.exists():
        if not args.force:
            parser.error("output directory already exists; pass --force to replace it")
        shutil.rmtree(output_root)
    output_root.mkdir(parents=True)

    manifest: list[dict[str, Any]] = []
    for case_name, factory in CASES:
        case_dir = output_root / case_name
        case_dir.mkdir()
        meeting_path = case_dir / "meeting.input.json"
        meeting_path.write_text(
            json.dumps(factory(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        run(
            [
                sys.executable,
                str(BUILD_SCRIPT),
                str(meeting_path),
                "--html-renderer",
                "editorial",
                "--output-dir",
                str(case_dir),
            ]
        )
        run(
            [
                sys.executable,
                str(EXPORT_SCRIPT),
                str(case_dir / "agenda.html"),
                "--output-dir",
                str(case_dir),
            ]
        )
        computed = json.loads(
            (case_dir / "agenda.computed.json").read_text(encoding="utf-8")
        )
        manifest.append(
            {
                "case": case_name,
                "pages": 1,
                "visual_audit": "passed",
                "row_count": len(computed.get("timeline", [])),
                "language": computed.get("club", {}).get("language"),
                "visual_theme": computed.get("visual_theme"),
            }
        )
        print(f"rendered={case_name}", flush=True)

    (output_root / "manifest.json").write_text(
        json.dumps({"cases": manifest}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"gallery={output_root}")


if __name__ == "__main__":
    main()
