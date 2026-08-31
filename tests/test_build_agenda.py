from __future__ import annotations

import base64
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
        auto_durations = [
            row["duration"]
            for row in result["timeline"]
            if row.get("computed_flexible")
        ]
        self.assertTrue(all(isinstance(value, int) for value in auto_durations))

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
        self.assertEqual(result["computed"]["page_count"], 3)
        rendered = BUILDER.render_html(result)
        self.assertIn('<meta name="agenda-page-count" content="3">', rendered)
        self.assertIn("备稿点评 12", rendered)
        self.assertEqual(rendered.count('class="page '), 3)

    def test_recommended_support_components_create_second_page(self) -> None:
        result, errors, _ = BUILDER.build_agenda(example())
        self.assertEqual(errors, [])
        self.assertEqual(result["computed"]["page_count"], 2)
        rendered = BUILDER.render_html(result)
        self.assertIn("时间官规则", rendered)
        self.assertIn("当届官员团队", rendered)
        self.assertIn("四类禁忌", rendered)
        self.assertEqual(rendered.count('class="page '), 2)

    def test_empty_support_components_keep_agenda_only(self) -> None:
        data = example()
        data["club"]["support_components"] = []
        result, errors, _ = BUILDER.build_agenda(data)
        self.assertEqual(errors, [])
        self.assertEqual(result["computed"]["page_count"], 1)
        rendered = BUILDER.render_html(result)
        self.assertNotIn('<main class="page support-page', rendered)
        self.assertTrue(any(row["type"] == "president_opening" for row in result["timeline"]))

    def test_meeting_support_components_fully_override_club_selection(self) -> None:
        data = example()
        data["meeting"]["support_components"] = []
        result, errors, _ = BUILDER.build_agenda(data)
        self.assertEqual(errors, [])
        self.assertEqual(result["support_components"], [])
        self.assertEqual(result["computed"]["page_count"], 1)

    def test_full_english_officer_titles_are_accepted(self) -> None:
        data = example()
        data["club"]["officers"] = [
            {"role": "President", "name": "Member A"},
            {"role": "Vice President Education", "name": "Member B"},
            {"role": "Vice President Membership", "name": "Member C"},
            {"role": "Vice President Public Relations", "name": "Member D"},
            {"role": "Secretary", "name": "Member E"},
            {"role": "Treasurer", "name": "Member F"},
            {"role": "Sergeant at Arms", "name": "Member G"},
        ]
        _, errors, _ = BUILDER.build_agenda(data)
        self.assertEqual(errors, [])

    def test_support_component_selection_is_required(self) -> None:
        data = example()
        del data["club"]["support_components"]
        _, errors, _ = BUILDER.build_agenda(data)
        self.assertTrue(any("support_components must be an explicit array" in error for error in errors))

    def test_selected_officer_component_requires_core_team(self) -> None:
        data = example()
        data["club"]["officers"] = data["club"]["officers"][:-1]
        _, errors, _ = BUILDER.build_agenda(data)
        self.assertTrue(any("missing core roles" in error for error in errors))

    def test_selected_intro_components_require_text(self) -> None:
        data = example()
        data["club"]["support_components"] = ["club_intro", "join_info"]
        data["club"].pop("club_intro")
        data["club"].pop("join_info")
        _, errors, _ = BUILDER.build_agenda(data)
        self.assertTrue(any("club.club_intro is empty" in error for error in errors))
        self.assertTrue(any("club.join_info is empty" in error for error in errors))

    def test_selected_qr_components_embed_user_images(self) -> None:
        data = example()
        data["club"]["support_components"] = [
            "timer_rules",
            "toastmasters_intro",
            "meeting_boundaries",
            "officers",
            "club_intro",
            "join_info",
            "vpm_qr",
            "voting_qr",
        ]
        data["club"]["vpm_qr_image"] = "../assets/toastmasters-logo.png"
        data["meeting"]["voting_qr_image"] = "../assets/toastmasters-logo.png"
        result, errors, _ = BUILDER.build_agenda(data, source_dir=ROOT / "examples")
        self.assertEqual(errors, [])
        self.assertTrue(result["club"]["vpm_qr_present"])
        self.assertTrue(result["meeting"]["voting_qr_present"])
        rendered = BUILDER.render_html(result)
        self.assertIn("入会咨询", rendered)
        self.assertIn("本期投票", rendered)
        encoded = result["_assets"]["vpm_qr_data_uri"].split(",", 1)[1]
        self.assertEqual(
            base64.b64decode(encoded),
            (ROOT / "assets" / "toastmasters-logo.png").read_bytes(),
        )

    def test_selected_qr_component_rejects_missing_image(self) -> None:
        data = example()
        data["club"]["support_components"] = ["vpm_qr"]
        data["club"]["vpm_qr_image"] = "missing.png"
        _, errors, _ = BUILDER.build_agenda(data, source_dir=ROOT / "examples")
        self.assertTrue(any("does not exist" in error for error in errors))

    def test_half_minute_overtime_requires_exact_approval(self) -> None:
        data = example()
        data["impromptu"]["minutes"] = 14
        data["impromptu"]["evaluation_minutes"] = 7
        data["standard_overrides"] = [
            {"id": "photo_break", "minutes": 4},
            {"id": "sharing", "minutes": 6},
        ]
        data["special_segments"] = [
            {
                "title": "额外工作坊",
                "owner": "成员K",
                "minutes": 10.5,
                "after": "guest_introduction",
            }
        ]
        data["meeting"]["approved_overtime_minutes"] = 11.5
        result, errors, _ = BUILDER.build_agenda(data)
        self.assertEqual(errors, [])
        self.assertEqual(result["computed"]["delta_minutes"], 11.5)
        self.assertEqual(result["computed"]["final_end"], "21:41:30")
        self.assertEqual(result["computed"]["status"], "exact_with_approved_overtime")

        data["meeting"]["approved_overtime_minutes"] = 11
        _, mismatch_errors, _ = BUILDER.build_agenda(data)
        self.assertTrue(
            any("approve exactly 11.5 minutes" in error for error in mismatch_errors)
        )

    def test_half_minute_start_defaults_across_midnight(self) -> None:
        data = example()
        data["meeting"]["start"] = "23:30:30"
        del data["meeting"]["end"]
        result, errors, _ = BUILDER.build_agenda(data)
        self.assertEqual(errors, [])
        self.assertEqual(result["computed"]["declared_end"], "01:30:30")
        self.assertEqual(result["computed"]["final_end"], "01:30:30")

    def test_half_minute_transitions_accumulate_without_removing_others(self) -> None:
        data = example()
        data["standard_overrides"] = [
            {"id": "guest_introduction", "transition_after": 0.5},
            {"id": "awards", "transition_after": 0.5},
        ]
        result, errors, _ = BUILDER.build_agenda(data)
        self.assertEqual(errors, [])
        self.assertEqual(result["computed"]["transition_minutes"], 18)
        self.assertEqual(result["computed"]["total_minutes"], 120)
        guest_index = next(
            index
            for index, row in enumerate(result["timeline"])
            if row["type"] == "guest_introduction"
        )
        self.assertEqual(result["timeline"][guest_index]["transition_after"], 0.5)
        self.assertTrue(result["timeline"][guest_index + 1]["start"].endswith(":30"))

    def test_role_triggered_items_accept_individual_transition_overrides(self) -> None:
        data = example()
        data["transition_overrides"] = [
            {"id": "prepared_evaluation:1", "minutes": 0.5},
            {"id": "table_topics_evaluation", "minutes": 0.5},
        ]
        result, errors, _ = BUILDER.build_agenda(data)
        self.assertEqual(errors, [])
        by_id = {row["id"]: row for row in result["timeline"]}
        self.assertEqual(by_id["prepared_evaluation:1"]["transition_after"], 0.5)
        self.assertEqual(by_id["table_topics_evaluation"]["transition_after"], 0.5)
        self.assertEqual(result["computed"]["transition_minutes"], 18)
        self.assertEqual(result["computed"]["total_minutes"], 120)

    def test_auto_evaluation_does_not_absorb_an_unrelated_time_gap(self) -> None:
        data = example()
        data["impromptu"]["minutes"] = 10
        data["standard_overrides"] = [
            {"id": "photo_break", "minutes": 5},
            {"id": "sharing", "minutes": 6},
        ]
        data["transition_overrides"] = [
            {"id": "prepared_evaluation:1", "minutes": 0.5},
            {"id": "prepared_evaluation:2", "minutes": 0.5},
            {"id": "prepared_evaluation:3", "minutes": 0.5},
            {"id": "table_topics_evaluation", "minutes": 0.5},
            {"id": "grammarian_report", "minutes": 0.5},
            {"id": "ah_counter_report", "minutes": 0.5},
            {"id": "timer_report", "minutes": 0.5},
        ]
        result, errors, _ = BUILDER.build_agenda(data)
        self.assertEqual(result["computed"]["delta_minutes"], -8.5)
        self.assertTrue(any("8.5 unexplained minutes" in error for error in errors))
        evaluation = next(
            row
            for row in result["timeline"]
            if row["type"] == "table_topics_evaluation"
        )
        self.assertEqual(evaluation["duration"], 5)

    def test_transition_override_rejects_missing_or_duplicate_targets(self) -> None:
        missing = example()
        missing["transition_overrides"] = [
            {"id": "not-a-real-item", "minutes": 0.5}
        ]
        _, missing_errors, _ = BUILDER.build_agenda(missing)
        self.assertTrue(any("references missing item" in error for error in missing_errors))

        duplicate = example()
        duplicate["standard_overrides"] = [
            {"id": "guest_introduction", "transition_after": 0.5}
        ]
        duplicate["transition_overrides"] = [
            {"id": "guest_introduction", "minutes": 0.5}
        ]
        _, duplicate_errors, _ = BUILDER.build_agenda(duplicate)
        self.assertTrue(any("defined twice" in error for error in duplicate_errors))

    def test_all_explicit_time_fields_accept_half_minute_increments(self) -> None:
        data = example()
        data["standard_overrides"] = [
            {"id": "guest_introduction", "minutes": 4.5, "transition_after": 0.5}
        ]
        data["prepared_speeches"][0]["minutes"] = 6.5
        data["prepared_speeches"][0]["evaluation_minutes"] = 2.5
        data["impromptu"]["minutes"] = 10.5
        data["impromptu"]["evaluation_minutes"] = 5.5
        data["special_segments"] = [
            {
                "title": "30秒提醒",
                "owner": "成员K",
                "minutes": 0.5,
                "after": "guest_introduction",
                "transition_after": 0.5,
            }
        ]
        result, errors, _ = BUILDER.build_agenda(data)
        self.assertEqual(errors, [])
        self.assertEqual(result["computed"]["total_minutes"], 120)
        first_speech = next(
            row for row in result["timeline"] if row["id"] == "prepared_speech:1"
        )
        self.assertEqual(first_speech["duration"], 6.5)
        markdown = BUILDER.render_markdown(result)
        rendered = BUILDER.render_html(result)
        self.assertIn("6.5 min", markdown)
        self.assertIn("0.5 min", rendered)
        self.assertNotIn("2.0 min", rendered)

    def test_invalid_half_minute_values_are_rejected(self) -> None:
        for invalid in (0.25, True, "0.5", -0.5, float("nan"), float("inf")):
            with self.subTest(invalid=invalid):
                data = example()
                data["standard_overrides"] = [
                    {"id": "guest_introduction", "transition_after": invalid}
                ]
                _, errors, _ = BUILDER.build_agenda(data)
                self.assertTrue(
                    any("0.5-minute increments" in error for error in errors)
                )


if __name__ == "__main__":
    unittest.main()
