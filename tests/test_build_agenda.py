from __future__ import annotations

import importlib.util
import json
import unittest
from copy import deepcopy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("agenda_builder", ROOT / "scripts" / "build_agenda.py")
assert SPEC and SPEC.loader
BUILDER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILDER)


def example() -> dict:
    return json.loads((ROOT / "examples" / "meeting.example.json").read_text(encoding="utf-8"))


class AgendaBuilderTests(unittest.TestCase):
    def test_standard_example_closes_exactly(self) -> None:
        result, errors, warnings = BUILDER.build_agenda(example())
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])
        self.assertEqual(result["computed"]["total_minutes"], 120)
        self.assertEqual(result["computed"]["final_end"], "21:30")
        durations = {row["type"]: row["duration"] for row in result["timeline"]}
        self.assertEqual(durations["table_topics_evaluation"], durations["table_topics"] / 2)
        self.assertEqual(durations["president_closing"], 2)

    def test_role_absence_removes_triggered_sections(self) -> None:
        data = example()
        data["roles"] = [
            row for row in data["roles"] if row["id"] not in {"ah_counter", "grammarian"}
        ]
        result, errors, _ = BUILDER.build_agenda(data)
        self.assertEqual(errors, [])
        types = [row["type"] for row in result["timeline"]]
        self.assertNotIn("ah_counter_intro", types)
        self.assertNotIn("ah_counter_report", types)
        self.assertNotIn("grammarian_intro", types)
        self.assertNotIn("grammarian_report", types)

    def test_unresolved_present_role_blocks_final(self) -> None:
        data = example()
        next(row for row in data["roles"] if row["id"] == "timer")["person"] = None
        _, errors, _ = BUILDER.build_agenda(data)
        self.assertTrue(any("timer" in error and "unresolved" in error for error in errors))

    def test_photographer_fills_photo_break_owner_without_creating_extra_row(self) -> None:
        result, errors, _ = BUILDER.build_agenda(example())
        self.assertEqual(errors, [])
        photo_rows = [row for row in result["timeline"] if row["type"] == "photo_break"]
        self.assertEqual(len(photo_rows), 1)
        self.assertEqual(photo_rows[0]["owner"], "成员J")
        self.assertFalse(any(row["type"] == "photographer" for row in result["timeline"]))

    def test_explicit_overrun_requires_confirmation(self) -> None:
        data = example()
        data["impromptu"]["minutes"] = 14
        data["impromptu"]["evaluation_minutes"] = 7
        data["standard_overrides"] = [
            {"id": "photo_break", "minutes": 4},
            {"id": "sharing", "minutes": 6},
        ]
        data["special_segments"] = [
            {"title": "额外工作坊", "owner": "成员K", "minutes": 10, "after": "guest_introduction"}
        ]
        result, errors, _ = BUILDER.build_agenda(data)
        self.assertEqual(result["computed"]["delta_minutes"], 11)
        self.assertTrue(any("overruns" in error for error in errors))

    def test_special_segment_uses_requested_anchor(self) -> None:
        data = example()
        data["special_segments"] = [
            {"title": "AI领航", "owner": "成员K", "minutes": 5, "after": "prepared_speech:1"}
        ]
        result, errors, _ = BUILDER.build_agenda(data)
        self.assertEqual(errors, [])
        ids = [row["id"] for row in result["timeline"]]
        self.assertEqual(ids.index("special:1"), ids.index("prepared_speech:1") + 1)

    def test_missing_end_defaults_to_two_hours(self) -> None:
        data = example()
        del data["meeting"]["end"]
        result, errors, _ = BUILDER.build_agenda(data)
        self.assertEqual(errors, [])
        self.assertEqual(result["computed"]["declared_window_minutes"], 120)
        self.assertEqual(result["computed"]["final_end"], "21:30")

    def test_exact_approved_overtime_is_honored(self) -> None:
        data = example()
        data["impromptu"]["minutes"] = 14
        data["impromptu"]["evaluation_minutes"] = 7
        data["standard_overrides"] = [
            {"id": "photo_break", "minutes": 4},
            {"id": "sharing", "minutes": 6},
        ]
        data["special_segments"] = [
            {"title": "额外工作坊", "owner": "成员K", "minutes": 10, "after": "guest_introduction"}
        ]
        data["meeting"]["approved_overtime_minutes"] = 11
        result, errors, _ = BUILDER.build_agenda(data)
        self.assertEqual(errors, [])
        self.assertEqual(result["computed"]["approved_overtime_minutes"], 11)
        self.assertEqual(result["computed"]["final_end"], "21:41")
        self.assertEqual(result["computed"]["status"], "exact_with_approved_overtime")

    def test_bilingual_labels_and_html_escape(self) -> None:
        data = example()
        data["club"]["language"] = "bilingual"
        data["meeting"]["theme"] = "<script>alert(1)</script>"
        result, errors, _ = BUILDER.build_agenda(data)
        self.assertEqual(errors, [])
        self.assertIn("规则介绍 / Meeting Rules", result["timeline"][0]["label"])
        rendered = BUILDER.render_html(result)
        self.assertNotIn("<script>alert(1)</script>", rendered)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", rendered)
        self.assertIn("会议流程 / Agenda", rendered)
        markdown = BUILDER.render_markdown(result)
        self.assertIn("主题 / Theme", markdown)

    def test_missing_evaluator_requires_explicit_decision(self) -> None:
        data = example()
        del data["prepared_speeches"][0]["evaluator"]
        _, errors, _ = BUILDER.build_agenda(data)
        self.assertTrue(any("requires an evaluator" in error for error in errors))

    def test_explicit_evaluation_disabled_omits_evaluation(self) -> None:
        data = example()
        speech = data["prepared_speeches"][0]
        speech.pop("evaluator")
        speech["evaluation_enabled"] = False
        result, errors, _ = BUILDER.build_agenda(data)
        self.assertEqual(errors, [])
        self.assertFalse(any(row["id"] == "prepared_evaluation:1" for row in result["timeline"]))

    def test_sparse_meeting_does_not_inflate_break_and_sharing(self) -> None:
        data = example()
        data["prepared_speeches"] = []
        data["impromptu"] = None
        data["roles"] = [
            row
            for row in data["roles"]
            if row["id"] not in {"timer", "ah_counter", "grammarian", "general_evaluator"}
        ]
        result, errors, _ = BUILDER.build_agenda(data)
        self.assertTrue(errors)
        flexible = {
            row["type"]: row["duration"]
            for row in result["timeline"]
            if row["type"] in {"photo_break", "sharing"}
        }
        self.assertLessEqual(flexible["photo_break"], 15)
        self.assertLessEqual(flexible["sharing"], 20)

    def test_equal_start_and_end_is_invalid(self) -> None:
        data = example()
        data["meeting"]["end"] = data["meeting"]["start"]
        _, errors, _ = BUILDER.build_agenda(data)
        self.assertTrue(any("must differ" in error for error in errors))

    def test_stale_overtime_approval_is_rejected(self) -> None:
        data = example()
        data["meeting"]["approved_overtime_minutes"] = 10
        _, errors, _ = BUILDER.build_agenda(data)
        self.assertTrue(any("no longer matches" in error for error in errors))

    def test_dense_agenda_paginates_without_dropping_rows(self) -> None:
        data = example()
        data["meeting"]["end"] = "23:30"
        data["prepared_speeches"] = [
            {
                "speaker": f"演讲者{i}",
                "title": f"演讲标题{i}",
                "evaluator": f"点评人{i}",
            }
            for i in range(1, 13)
        ]
        result, errors, _ = BUILDER.build_agenda(data)
        self.assertEqual(errors, [])
        self.assertEqual(result["computed"]["row_count"], 41)
        self.assertEqual(result["computed"]["page_count"], 2)
        rendered = BUILDER.render_html(result)
        self.assertIn('<meta name="agenda-page-count" content="2">', rendered)
        self.assertIn("备稿点评 12", rendered)
        self.assertEqual(rendered.count('class="page '), 2)


if __name__ == "__main__":
    unittest.main()
