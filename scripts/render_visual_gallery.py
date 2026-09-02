#!/usr/bin/env python3
"""Render the portable Skill's representative A4 cases for human review."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable


SKILL_ROOT = Path(__file__).resolve().parent.parent
EXAMPLE_PATH = SKILL_ROOT / "examples" / "meeting.example.json"
RUN_SCRIPT = SKILL_ROOT / "scripts" / "run_agenda.py"


def base_meeting() -> dict[str, Any]:
    return json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))


def standard_chinese() -> dict[str, Any]:
    return base_meeting()


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
    data["club"]["custom_support_blocks"] = []
    return data


def bilingual_meeting() -> dict[str, Any]:
    data = base_meeting()
    data["club"]["name"] = "星桥 Bilingual Toastmasters Club"
    data["club"]["language"] = "bilingual"
    data["club"]["default_location"] = "星桥中心 Starbridge Center"
    data["meeting"]["location"] = data["club"]["default_location"]
    data["meeting"]["theme"] = "越过边界 · Speak Beyond Borders"
    data["meeting"]["word_of_day"] = "Clarity · 澄明"
    data["meeting"]["manager"] = "Lily 林"
    data["meeting"]["president"] = "Leo 李"
    for index, role in enumerate(data["roles"], start=1):
        role["person"] = f"Member {index} / 成员{index}"
    for index, speech in enumerate(data["prepared_speeches"], start=1):
        speech["speaker"] = f"Speaker {index} / 演讲者{index}"
        speech["title"] = f"One Step Forward / 向前一步 {index}"
        speech["evaluator"] = f"Evaluator {index} / 点评者{index}"
    data["impromptu"] = {
        "host": "Table Topics Host / 即兴主持",
        "evaluator": "Topics Evaluator / 即兴点评",
    }
    data["backstage"] = [
        {"id": "photographer", "person": "Photo Member / 摄影成员", "label": "Photography / 摄影"},
        {"id": "slides", "person": "Slide Member / 场控成员", "label": "Slides / 场控"},
    ]
    data["club"]["support_components"] = ["toastmasters_intro"]
    return data


def workshop_meeting() -> dict[str, Any]:
    data = base_meeting()
    data["meeting"]["theme"] = "AI Skill 深度实战工作坊"
    data["meeting"]["word_of_day"] = "共创"
    data["special_segments"] = [
        {
            "title": "AI Skill 深度实战",
            "owner": "成员K",
            "minutes": 15,
            "after": "guest_introduction",
            "details": ["现场体验", "共同拆解", "动手实践"],
        }
    ]
    return data


def dense_meeting() -> dict[str, Any]:
    data = base_meeting()
    data["meeting"]["end"] = "21:50"
    data["meeting"]["theme"] = "五场备稿演讲马拉松"
    data["club"]["support_components"] = []
    data["prepared_speeches"] = [
        {
            "speaker": f"演讲者{index}",
            "title": f"演讲题目{index}",
            "project": "Presentation Mastery",
            "evaluator": f"点评者{index}",
        }
        for index in range(1, 6)
    ]
    return data


CASES: tuple[tuple[str, Callable[[], dict[str, Any]]], ...] = (
    ("01-standard-chinese", standard_chinese),
    ("02-english-long", english_long),
    ("03-bilingual", bilingual_meeting),
    ("04-workshop", workshop_meeting),
    ("05-dense-marathon", dense_meeting),
)


def validate_output_root(path: Path) -> None:
    if path == Path(path.anchor) or path == Path.home() or len(path.parts) < 4:
        raise ValueError(f"refusing unsafe visual gallery output path: {path}")


def run(command: list[str]) -> None:
    subprocess.run(command, check=True)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
        run([
            sys.executable,
            str(RUN_SCRIPT),
            "first",
            str(meeting_path),
            "--output-dir",
            str(case_dir),
        ])
        run([
            sys.executable,
            str(RUN_SCRIPT),
            "final",
            str(case_dir / "agenda.preview.html"),
            "--output-dir",
            str(case_dir),
        ])
        computed = json.loads(
            (case_dir / "agenda.computed.json").read_text(encoding="utf-8")
        )
        pdf_matches = sha256(case_dir / "agenda.preview.pdf") == sha256(case_dir / "agenda.pdf")
        png_matches = sha256(case_dir / "agenda.preview.png") == sha256(case_dir / "agenda.png")
        if not pdf_matches or not png_matches:
            raise RuntimeError(f"final files changed after preview for {case_name}")
        manifest.append(
            {
                "case": case_name,
                "pages": 1,
                "visual_audit": "passed",
                "row_count": len(computed.get("timeline", [])),
                "language": computed.get("club", {}).get("language"),
                "time_status": computed.get("computed", {}).get("status"),
                "final_matches_preview": True,
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
