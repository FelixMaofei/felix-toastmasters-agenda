from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "agenda_simple_input", ROOT / "scripts" / "simple_input.py"
)
assert SPEC and SPEC.loader
SIMPLE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SIMPLE)

BUILDER_SPEC = importlib.util.spec_from_file_location(
    "agenda_builder_for_simple_input", ROOT / "scripts" / "build_agenda.py"
)
assert BUILDER_SPEC and BUILDER_SPEC.loader
BUILDER = importlib.util.module_from_spec(BUILDER_SPEC)
BUILDER_SPEC.loader.exec_module(BUILDER)


def minimal() -> dict:
    return {
        "simple_version": 1,
        "club": {
            "name": "星河头马演讲俱乐部",
            "default_location": "星河会议室",
            "language": "中文",
        },
        "meeting": {
            "number": "68",
            "date": "2026-09-02",
            "start": "19:30",
            "location": "本期临时会场",
        },
        "roles": [],
        "speeches": [],
        "impromptu": None,
        "backstage": [],
        "special": [],
    }


class SimpleInputTests(unittest.TestCase):
    def test_converted_example_is_accepted_by_existing_business_engine(self) -> None:
        canonical_example = json.loads(
            (ROOT / "examples" / "meeting.fixture.json").read_text(encoding="utf-8")
        )
        data = {
            "simple_version": 1,
            "club": canonical_example["club"],
            "meeting": {
                key: value
                for key, value in canonical_example["meeting"].items()
                if key != "approved_overtime_minutes"
            },
            "roles": [
                {"role": row["id"], "person": row["person"]}
                for row in canonical_example["roles"]
            ],
            "speeches": canonical_example["prepared_speeches"],
            "impromptu": {
                **canonical_example["impromptu"],
                "minutes": 14,
                "evaluation_minutes": 7,
            },
            "backstage": [
                {
                    "role": row["id"],
                    "person": row["person"],
                    "label": row["label"],
                }
                for row in canonical_example["backstage"]
            ],
            "special": [],
            "agenda_overrides": [
                {"id": "photo_break", "minutes": 4},
                {"id": "sharing", "minutes": 6},
            ],
        }

        canonical = SIMPLE.convert_simple_input(data)
        result, errors, warnings = BUILDER.build_agenda(canonical)

        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])
        self.assertEqual(result["computed"]["total_minutes"], 120)
        self.assertEqual(result["computed"]["final_end"], "21:30")

    def test_full_simple_input_converts_without_mutating_source(self) -> None:
        data = minimal()
        data["club"].update(
            {
                "support_components": ["club_intro", "officers", "vpm_qr"],
                "officers": [{"role": "President", "name": "Felix"}],
                "club_intro": ["一起练习表达与领导力。"],
                "join_info": ["欢迎先来体验。"],
                "vpm_qr_image": "assets/vpm.png",
            }
        )
        data["meeting"].update(
            {
                "theme": "清晰表达",
                "word_of_day": "Clarity",
                "support_components": ["club_intro", "voting_qr"],
                "voting_qr_image": "assets/vote.png",
            }
        )
        data["roles"] = [
            {"role": "总主持", "person": "Felix"},
            {"role": "Timer", "person": "Alice"},
            {"role": "总点评官", "person": "Bob"},
        ]
        data["speeches"] = [
            {
                "speaker": "Carol",
                "title": "第一步",
                "project": "PM L1 Ice Breaker",
                "minutes": 6,
                "evaluator": "Dora",
                "evaluation_minutes": 3.5,
            },
            {
                "speaker": "Evan",
                "title": "No Evaluation",
                "evaluation_enabled": False,
            },
        ]
        data["impromptu"] = {
            "host": "Frank",
            "minutes": 15,
            "evaluator": "Grace",
            "evaluation_minutes": 7.5,
        }
        data["backstage"] = [
            {"role": "拍照官", "person": "Helen"},
            {"role": "会议记录", "person": "Iris", "label": "会议记录"},
        ]
        data["special"] = [
            {
                "title": "AI Workshop",
                "owner": "Jack",
                "minutes": 20,
                "after": "在备稿演讲1之后",
                "details": ["Demo", "Practice"],
            }
        ]
        data["participant_pathways"] = {"Carol": "PM L1"}
        data["custom_support_blocks"] = [
            {"id": "pathways", "title": "Pathways", "lines": ["PM L1"]}
        ]
        data["agenda_overrides"] = [
            {"id": "general_evaluation", "minutes": 10}
        ]
        data["transition_overrides"] = [
            {"after": "prepared_speech:1", "minutes": 0.5}
        ]
        original = deepcopy(data)

        result = SIMPLE.convert_simple_input(data)

        self.assertEqual(data, original)
        self.assertNotIn("simple_version", result)
        self.assertEqual(result["club"]["language"], "zh")
        self.assertEqual(result["club"]["club_intro"], ["一起练习表达与领导力。"])
        self.assertEqual(result["meeting"]["voting_qr_image"], "assets/vote.png")
        self.assertEqual(
            result["roles"],
            [
                {"id": "toastmaster", "person": "Felix"},
                {"id": "timer", "person": "Alice"},
                {"id": "general_evaluator", "person": "Bob"},
            ],
        )
        self.assertEqual(result["prepared_speeches"], data["speeches"])
        self.assertEqual(result["backstage"][0]["id"], "photographer")
        self.assertEqual(result["backstage"][0]["label"], "拍照官")
        self.assertEqual(result["backstage"][1]["id"], "会议记录")
        self.assertEqual(result["special_segments"][0]["after"], "prepared_speech:1")
        for field in (
            "participant_pathways",
            "custom_support_blocks",
            "agenda_overrides",
            "transition_overrides",
        ):
            self.assertEqual(result[field], data[field])

    def test_all_role_ids_accept_common_chinese_and_english_aliases(self) -> None:
        aliases = {
            "会长": "president",
            "事务官": "rules_host",
            "Toastmaster of the Day": "toastmaster",
            "时间官": "timer",
            "Ah-Counter": "ah_counter",
            "语法官": "grammarian",
            "Guest Introduction": "guest_host",
            "Sharing": "sharing_host",
            "General Evaluator": "general_evaluator",
            "Awards": "awards_host",
        }
        data = minimal()
        data["roles"] = [
            {"role": alias, "person": f"Member {index}"}
            for index, alias in enumerate(aliases, start=1)
        ]
        result = SIMPLE.convert_simple_input(data)
        self.assertEqual(
            [row["id"] for row in result["roles"]], list(aliases.values())
        )

    def test_rules_host_accepts_club_specific_sergeant_at_arms_names(self) -> None:
        for alias in ("事务官开场", "会场事务官", "SAA", "Sergeant at Arms"):
            with self.subTest(alias=alias):
                data = minimal()
                data["roles"] = [{"role": alias, "person": "Member A"}]
                result = SIMPLE.convert_simple_input(data)
                self.assertEqual(result["roles"], [{"id": "rules_host", "person": "Member A"}])

    def test_language_aliases_are_deterministic(self) -> None:
        for raw, expected in (
            ("zh", "zh"),
            ("Chinese", "zh"),
            ("英文", "en"),
            ("Bilingual", "bilingual"),
            ("中英双语", "bilingual"),
        ):
            with self.subTest(raw=raw):
                data = minimal()
                data["club"]["language"] = raw
                self.assertEqual(
                    SIMPLE.convert_simple_input(data)["club"]["language"], expected
                )

    def test_every_supported_human_anchor_maps_to_canonical_id(self) -> None:
        anchors = {
            "嘉宾介绍": "guest_introduction",
            "Guest Introduction": "guest_introduction",
            "备稿演讲1": "prepared_speech:1",
            "after Prepared Speech 2": "prepared_speech:2",
            "即兴演讲": "table_topics",
            "Table Topics": "table_topics",
            "合影休息": "photo_break",
            "Group Photo & Break": "photo_break",
            "备稿点评1": "prepared_evaluation:1",
            "Speech Evaluation 2": "prepared_evaluation:2",
            "即兴点评": "table_topics_evaluation",
            "Table Topics Evaluation": "table_topics_evaluation",
            "真情分享": "sharing",
            "Sharing": "sharing",
            "prepared_speech:3": "prepared_speech:3",
        }
        for raw, expected in anchors.items():
            with self.subTest(raw=raw):
                self.assertEqual(SIMPLE.normalize_after(raw), expected)

    def test_ambiguous_and_unknown_roles_are_structured_and_aggregated(self) -> None:
        data = minimal()
        data["roles"] = [
            {"role": "主持人", "person": "Alice"},
            {"role": "气氛官", "person": "Bob"},
            {"role": "Timer", "person": "Carol"},
            {"role": "时间官", "person": "Dora"},
        ]
        with self.assertRaises(SIMPLE.SimpleInputError) as caught:
            SIMPLE.convert_simple_input(data)
        payload = caught.exception.to_payload()
        self.assertEqual(payload["stage"], "needs_input")
        self.assertEqual(payload["error_type"], "simple_input")
        by_code = {issue["code"]: issue for issue in payload["errors"]}
        self.assertIn("ambiguous_role", by_code)
        self.assertIn("unknown_role", by_code)
        self.assertIn("duplicate_role", by_code)
        self.assertIn("candidates", by_code["ambiguous_role"])
        self.assertTrue(all("path" in issue for issue in payload["errors"]))

    def test_ambiguous_and_unknown_after_never_guess(self) -> None:
        for raw, code in (
            ("备稿演讲", "ambiguous_after"),
            ("Speech Evaluation", "ambiguous_after"),
            ("主持人开场", "unknown_after"),
        ):
            with self.subTest(raw=raw):
                with self.assertRaises(SIMPLE.SimpleInputError) as caught:
                    SIMPLE.normalize_after(raw)
                issue = caught.exception.errors[0]
                self.assertEqual(issue["code"], code)
                self.assertEqual(issue["value"], raw)
                self.assertIn("candidates", issue)

    def test_missing_special_fields_are_returned_together(self) -> None:
        data = minimal()
        data["special"] = [{}]
        with self.assertRaises(SIMPLE.SimpleInputError) as caught:
            SIMPLE.convert_simple_input(data)
        issues = [
            issue for issue in caught.exception.errors if issue["path"].startswith("special[0]")
        ]
        self.assertEqual(
            {issue["path"] for issue in issues},
            {
                "special[0].title",
                "special[0].owner",
                "special[0].minutes",
                "special[0].after",
            },
        )

    def test_impromptu_requires_all_current_session_durations_together(self) -> None:
        data = minimal()
        data["impromptu"] = {"host": "Alice", "evaluator": "Bob"}

        with self.assertRaises(SIMPLE.SimpleInputError) as caught:
            SIMPLE.convert_simple_input(data)

        issues = [
            issue
            for issue in caught.exception.errors
            if issue["path"].startswith("impromptu.")
        ]
        self.assertEqual(
            {(issue["code"], issue["path"]) for issue in issues},
            {
                ("missing_value", "impromptu.minutes"),
                ("missing_value", "impromptu.evaluation_minutes"),
            },
        )

    def test_selected_join_info_is_not_synthesized_by_simple_pipeline(self) -> None:
        data = minimal()
        data["club"]["support_components"] = ["join_info"]

        canonical = SIMPLE.convert_simple_input(data)
        result, errors, _ = BUILDER.build_agenda(canonical)

        self.assertIn(
            "join_info component is selected but club.join_info is empty",
            errors,
        )
        self.assertEqual(result["club"]["join_info"], [])

    def test_disabled_evaluation_does_not_require_or_emit_evaluator(self) -> None:
        data = minimal()
        data["speeches"] = [
            {
                "speaker": "Alice",
                "title": "One Voice",
                "evaluation_enabled": False,
            }
        ]
        speech = SIMPLE.convert_simple_input(data)["prepared_speeches"][0]
        self.assertFalse(speech["evaluation_enabled"])
        self.assertNotIn("evaluator", speech)
        self.assertNotIn("evaluation_minutes", speech)

    def test_enabled_evaluation_requires_confirmed_evaluator(self) -> None:
        data = minimal()
        data["speeches"] = [{"speaker": "Alice", "title": "One Voice"}]
        with self.assertRaises(SIMPLE.SimpleInputError) as caught:
            SIMPLE.convert_simple_input(data)
        self.assertTrue(
            any(
                issue["path"] == "speeches[0].evaluator"
                and issue["code"] == "missing_value"
                for issue in caught.exception.errors
            )
        )

    def test_visual_css_and_unknown_fields_cannot_enter_canonical_output(self) -> None:
        data = minimal()
        data["meeting"]["visual_theme"] = "technology"
        data["club"]["css"] = ".page { display:none }"
        data["visual"] = {"text_scale": "large"}
        with self.assertRaises(SIMPLE.SimpleInputError) as caught:
            SIMPLE.convert_simple_input(data)
        paths = {issue["path"] for issue in caught.exception.errors}
        self.assertEqual(
            paths,
            {"meeting.visual_theme", "club.css", "visual"},
        )
        self.assertTrue(
            all(issue["code"] == "unknown_field" for issue in caught.exception.errors)
        )

    def test_simple_input_never_accepts_embedded_overtime_approval(self) -> None:
        for value in (0, 11, 11.5):
            with self.subTest(value=value):
                data = minimal()
                data["meeting"]["approved_overtime_minutes"] = value
                with self.assertRaises(SIMPLE.SimpleInputError) as caught:
                    SIMPLE.convert_simple_input(data)
                issues = caught.exception.errors
                self.assertTrue(
                    any(
                        issue["code"] == "overtime_approval_not_allowed"
                        and issue["path"] == "meeting.approved_overtime_minutes"
                        and issue["value"] == value
                        for issue in issues
                    )
                )
                self.assertIn(
                    "--confirm-overtime-minutes",
                    next(
                        issue["message"]
                        for issue in issues
                        if issue["code"] == "overtime_approval_not_allowed"
                    ),
                )

    def test_invalid_version_and_minutes_have_structured_errors(self) -> None:
        data = minimal()
        data["simple_version"] = 2
        data["special"] = [
            {"title": "Workshop", "owner": "Alice", "minutes": 3.25, "after": "嘉宾介绍"}
        ]
        with self.assertRaises(SIMPLE.SimpleInputError) as caught:
            SIMPLE.convert_simple_input(data)
        codes = {issue["code"] for issue in caught.exception.errors}
        self.assertEqual(codes, {"invalid_simple_version", "invalid_minutes"})

    def test_cli_writes_canonical_json_and_emits_structured_failure(self) -> None:
        script = ROOT / "scripts" / "simple_input.py"
        with tempfile.TemporaryDirectory() as temp_text:
            temp = Path(temp_text)
            source = temp / "simple.json"
            output = temp / "meeting.json"
            source.write_text(json.dumps(minimal(), ensure_ascii=False), encoding="utf-8")
            success = subprocess.run(
                [sys.executable, str(script), str(source), "--output", str(output)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(success.returncode, 0, success.stderr)
            self.assertEqual(json.loads(output.read_text(encoding="utf-8"))["club"]["language"], "zh")

            invalid = minimal()
            invalid["roles"] = [{"role": "Host", "person": "Alice"}]
            source.write_text(json.dumps(invalid, ensure_ascii=False), encoding="utf-8")
            failure = subprocess.run(
                [sys.executable, str(script), str(source)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(failure.returncode, 2)
            payload = json.loads(failure.stderr)
            self.assertEqual(payload["errors"][0]["code"], "ambiguous_role")


if __name__ == "__main__":
    unittest.main()
