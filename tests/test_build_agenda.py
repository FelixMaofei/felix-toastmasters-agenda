from __future__ import annotations

import base64
import html as html_lib
import importlib.util
import json
import re
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("agenda_builder", ROOT / "scripts" / "build_agenda.py")
assert SPEC and SPEC.loader
BUILDER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILDER)


def example() -> dict:
    data = json.loads(
        (ROOT / "examples" / "meeting.fixture.json").read_text(encoding="utf-8")
    )
    data["impromptu"].update({"minutes": 14, "evaluation_minutes": 7})
    data["standard_overrides"] = [
        {"id": "photo_break", "minutes": 4},
        {"id": "sharing", "minutes": 6},
    ]
    return data


class AgendaBuilderTests(unittest.TestCase):
    def test_break_and_sharing_suggestions_are_returned_together(self) -> None:
        data = example()
        data["standard_overrides"] = []

        result, errors, _ = BUILDER.build_agenda(data)

        self.assertTrue(result["computed"]["duration_confirmation_required"])
        self.assertEqual(
            result["computed"]["suggested_agenda_overrides"],
            [
                {"id": "photo_break", "minutes": 10},
                {"id": "sharing", "minutes": 10},
            ],
        )
        self.assertEqual(
            [row["duration"] for row in result["timeline"] if row["id"] in {"photo_break", "sharing"}],
            [10, 10],
        )
        self.assertTrue(any("photo_break and sharing" in error for error in errors))

    def test_confirmed_break_and_sharing_are_locked_without_auto_allocation(self) -> None:
        data = example()
        data["standard_overrides"] = []
        data["agenda_overrides"] = [
            {"id": "photo_break", "minutes": 10},
            {"id": "sharing", "minutes": 10},
        ]
        data["meeting"]["end"] = "21:40"

        result, errors, _ = BUILDER.build_agenda(data)

        self.assertEqual(errors, [])
        self.assertFalse(result["computed"]["duration_confirmation_required"])
        self.assertEqual(result["computed"]["suggested_agenda_overrides"], [])
        by_id = {row["id"]: row for row in result["timeline"]}
        self.assertTrue(by_id["photo_break"]["duration_locked"])
        self.assertTrue(by_id["sharing"]["duration_locked"])
        self.assertFalse(by_id["photo_break"].get("computed_flexible", False))
        self.assertFalse(by_id["sharing"].get("computed_flexible", False))

    def test_disabled_flexible_items_are_not_requested(self) -> None:
        data = example()
        data["standard_overrides"] = []
        data["agenda_overrides"] = [{"id": "sharing", "enabled": False}]

        result, _, _ = BUILDER.build_agenda(data)
        self.assertEqual(
            result["computed"]["suggested_agenda_overrides"],
            [{"id": "photo_break", "minutes": 10}],
        )

        data["agenda_overrides"] = [
            {"id": "photo_break", "enabled": False},
            {"id": "sharing", "enabled": False},
        ]
        result, errors, _ = BUILDER.build_agenda(data)
        self.assertFalse(result["computed"]["duration_confirmation_required"])
        self.assertFalse(any("explicit confirmed durations" in error for error in errors))

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
        data["meeting"]["end"] = "21:16"
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

    def test_impromptu_requires_both_explicit_durations_without_auto_inference(
        self,
    ) -> None:
        data = example()
        data["impromptu"].pop("minutes")
        data["impromptu"].pop("evaluation_minutes")

        result, errors, _ = BUILDER.build_agenda(data)

        self.assertEqual(
            [error for error in errors if error.startswith("impromptu.")],
            [
                "impromptu.minutes needs an explicit confirmed duration",
                "impromptu.evaluation_minutes needs an explicit confirmed duration",
            ],
        )
        impromptu_rows = [
            row
            for row in result["timeline"]
            if row["type"] in {"table_topics", "table_topics_evaluation"}
        ]
        self.assertEqual(len(impromptu_rows), 2)
        self.assertTrue(all(row["duration_locked"] for row in impromptu_rows))
        self.assertTrue(
            all(not row.get("computed_flexible") for row in impromptu_rows)
        )

    def test_special_segment_uses_requested_anchor(self) -> None:
        data = example()
        data["meeting"]["end"] = "21:36"
        data["special_segments"] = [
            {"title": "AI领航", "owner": "成员K", "minutes": 5, "after": "prepared_speech:1"}
        ]
        result, errors, _ = BUILDER.build_agenda(data)
        self.assertEqual(errors, [])
        ids = [row["id"] for row in result["timeline"]]
        self.assertEqual(ids.index("special:1"), ids.index("prepared_speech:1") + 1)

    def test_special_segment_reports_all_required_fields_together(self) -> None:
        data = example()
        data["special_segments"] = [{}]
        result, errors, _ = BUILDER.build_agenda(data)
        special_errors = [
            error for error in errors if error.startswith("special segment 1")
        ]
        self.assertEqual(
            special_errors,
            [
                "special segment 1 has unresolved title",
                "special segment 1 has unresolved owner",
                "special segment 1 minutes must be positive in 0.5-minute increments",
                "special segment 1 has unresolved after anchor",
            ],
        )
        self.assertFalse(any(row["type"] == "special" for row in result["timeline"]))

    def test_special_segment_never_guesses_a_missing_anchor(self) -> None:
        data = example()
        data["special_segments"] = [
            {"title": "AI领航", "owner": "成员K", "minutes": 5}
        ]
        result, errors, _ = BUILDER.build_agenda(data)
        self.assertTrue(any("unresolved after anchor" in error for error in errors))
        self.assertFalse(any(row["type"] == "special" for row in result["timeline"]))

    def test_special_segment_rejects_generic_owner_roles_but_accepts_named_people(self) -> None:
        for owner in ("主持人", "Toastmaster", "负责人", "TBD"):
            with self.subTest(owner=owner):
                data = example()
                data["special_segments"] = [
                    {
                        "title": "AI领航",
                        "owner": owner,
                        "minutes": 5,
                        "after": "prepared_speech:1",
                    }
                ]
                result, errors, _ = BUILDER.build_agenda(data)
                self.assertTrue(any("owner" in error for error in errors))
                self.assertFalse(
                    any(row["type"] == "special" for row in result["timeline"])
                )

        for owner in ("主持人小王", "Toastmaster Jane"):
            with self.subTest(owner=owner):
                data = example()
                data["meeting"]["end"] = "21:36"
                data["special_segments"] = [
                    {
                        "title": "AI领航",
                        "owner": owner,
                        "minutes": 5,
                        "after": "prepared_speech:1",
                    }
                ]
                result, errors, _ = BUILDER.build_agenda(data)
                self.assertEqual(errors, [])
                special = next(
                    row for row in result["timeline"] if row["type"] == "special"
                )
                self.assertEqual(special["owner"], owner)



    def test_feature_item_can_be_explicitly_selected(self) -> None:
        data = example()
        data["meeting"]["end"] = "21:44"
        data["impromptu"].update({"minutes": 2, "evaluation_minutes": 1})
        data["special_segments"] = [
            {
                "title": "第一个重点",
                "owner": "成员K",
                "minutes": 15,
                "after": "guest_introduction",
            },
            {
                "title": "第二个重点",
                "owner": "成员L",
                "minutes": 15,
                "after": "guest_introduction",
            },
        ]
        data["meeting"]["feature_item"] = "special:2"
        result, errors, _ = BUILDER.build_agenda(data)
        self.assertEqual(errors, [])
        self.assertEqual(result["feature_item"], "special:2")


    def test_club_profile_keeps_only_reusable_club_facts(self) -> None:
        data = example()
        profile = BUILDER.club_profile_from_data(data)
        self.assertEqual(profile["club"]["name"], data["club"]["name"])
        self.assertEqual(
            profile["club"]["support_components"],
            data["club"]["support_components"],
        )
        self.assertNotIn("meeting", profile)
        self.assertNotIn("roles", profile)
        self.assertNotIn("prepared_speeches", profile)

    def test_current_meeting_facts_override_profile_without_mutating_it(self) -> None:
        stable = example()
        profile = BUILDER.club_profile_from_data(stable)
        current = example()
        current["club"] = {
            "name": stable["club"]["name"],
            "language": "bilingual",
        }
        current["meeting"]["location"] = "本期临时会场 / Temporary Venue"
        current["meeting"]["support_components"] = []

        merged = BUILDER.deep_merge(profile, current)
        result, errors, _ = BUILDER.build_agenda(merged)

        self.assertEqual(errors, [])
        self.assertEqual(result["club"]["language"], "bilingual")
        self.assertEqual(
            result["meeting"]["location"], "本期临时会场 / Temporary Venue"
        )
        self.assertEqual(result["support_components"], [])
        self.assertEqual(profile["club"]["language"], "zh")
        self.assertNotIn("meeting", profile)

    def test_stored_club_profile_path_is_stable_and_name_specific(self) -> None:
        first = BUILDER.stored_club_profile_path("星河头马演讲俱乐部")
        same = BUILDER.stored_club_profile_path("  星河头马演讲俱乐部  ")
        other = BUILDER.stored_club_profile_path("星河头马俱乐部")
        self.assertEqual(first, same)
        self.assertNotEqual(first, other)
        self.assertEqual(first.parent, BUILDER.PROFILE_ROOT)

    def test_saved_profile_copies_vpm_qr_into_stable_asset_folder(self) -> None:
        data = example()
        data["club"]["vpm_qr_image"] = "../assets/toastmasters-logo.png"
        with tempfile.TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir) / "club-profile.json"
            BUILDER.write_club_profile(
                data,
                destination,
                source_dir=ROOT / "examples",
            )
            profile = json.loads(destination.read_text(encoding="utf-8"))
            stored_qr = profile["club"]["vpm_qr_image"]
            self.assertFalse(Path(stored_qr).is_absolute())
            copied = destination.parent / stored_qr
            self.assertTrue(copied.is_file())
            self.assertEqual(
                copied.read_bytes(),
                (ROOT / "assets" / "toastmasters-logo.png").read_bytes(),
            )

    def test_layout_and_visual_theme_can_be_explicitly_overridden(self) -> None:
        data = example()
        data["meeting"]["feature_item"] = None
        data["meeting"]["layout"] = "feature"
        data["meeting"]["visual_theme"] = "wellness"
        result, errors, _ = BUILDER.build_agenda(data)
        self.assertEqual(errors, [])
        self.assertEqual(result["layout"], "feature")
        self.assertEqual(result["visual_theme"], "wellness")

        data["meeting"]["layout"] = "unknown"
        data["meeting"]["visual_theme"] = "unknown"
        _, invalid_errors, _ = BUILDER.build_agenda(data)
        self.assertTrue(any("meeting.layout must be" in error for error in invalid_errors))
        self.assertTrue(any("meeting.visual_theme must be" in error for error in invalid_errors))










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


    def test_missing_evaluator_requires_explicit_decision(self) -> None:
        data = example()
        del data["prepared_speeches"][0]["evaluator"]
        _, errors, _ = BUILDER.build_agenda(data)
        self.assertTrue(any("requires an evaluator" in error for error in errors))

    def test_explicit_evaluation_disabled_omits_evaluation(self) -> None:
        data = example()
        data["meeting"]["end"] = "21:26"
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

    def test_extreme_auto_break_or_sharing_duration_warns(self) -> None:
        warnings: list[str] = []
        BUILDER.validate_auto_flexible_durations(
            [
                {"type": "photo_break", "duration": 13, "computed_flexible": True},
                {"type": "sharing", "duration": 15, "computed_flexible": True},
            ],
            warnings,
        )
        self.assertEqual(len(warnings), 2)
        self.assertTrue(any("photo_break" in warning for warning in warnings))
        self.assertTrue(any("sharing" in warning for warning in warnings))

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

    def test_dense_agenda_is_blocked_instead_of_crossing_a4_pages(self) -> None:
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
        self.assertTrue(any("single-page A4 capacity exceeded" in error for error in errors))
        self.assertEqual(result["computed"]["row_count"], 41)
        self.assertEqual(result["computed"]["page_count"], 1)



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

    def test_missing_support_component_selection_uses_safe_defaults(self) -> None:
        data = example()
        del data["club"]["support_components"]
        result, errors, _ = BUILDER.build_agenda(data)
        self.assertEqual(errors, [])
        self.assertEqual(
            result["support_components"],
            [
                "timer_rules",
                "toastmasters_intro",
                "meeting_boundaries",
                "officers",
            ],
        )

    def test_missing_support_selection_does_not_require_officer_data(self) -> None:
        data = example()
        del data["club"]["support_components"]
        del data["club"]["officers"]
        result, errors, _ = BUILDER.build_agenda(data)
        self.assertEqual(errors, [])
        self.assertEqual(
            result["support_components"], BUILDER.DEFAULT_SUPPORT_COMPONENTS
        )

    def test_implicit_support_defaults_skip_incomplete_officer_team(self) -> None:
        data = example()
        del data["club"]["support_components"]
        data["club"]["officers"] = data["club"]["officers"][:-1]
        result, errors, _ = BUILDER.build_agenda(data)
        self.assertEqual(errors, [])
        self.assertEqual(
            result["support_components"], BUILDER.DEFAULT_SUPPORT_COMPONENTS
        )

    def test_selected_officer_component_requires_core_team(self) -> None:
        data = example()
        data["club"]["officers"] = data["club"]["officers"][:-1]
        _, errors, _ = BUILDER.build_agenda(data)
        self.assertTrue(any("missing core roles" in error for error in errors))

    def test_selected_intro_components_require_text(self) -> None:
        data = example()
        data["club"]["support_components"] = ["club_intro", "join_info"]
        data["club"].pop("club_intro")
        data["club"].pop("join_info", None)
        result, errors, _ = BUILDER.build_agenda(data)
        self.assertTrue(any("club.club_intro is empty" in error for error in errors))
        self.assertTrue(any("club.join_info is empty" in error for error in errors))
        self.assertEqual(result["club"]["join_info"], [])

    def test_existing_profile_selection_does_not_add_join_info(self) -> None:
        data = example()
        data["club"]["support_components"] = ["timer_rules"]
        data["club"].pop("join_info", None)

        result, errors, _ = BUILDER.build_agenda(data)

        self.assertEqual(errors, [])
        self.assertEqual(result["support_components"], ["timer_rules"])
        self.assertEqual(result["club"]["join_info"], [])

    def test_current_empty_support_selection_keeps_join_info_unselected(self) -> None:
        data = example()
        data["meeting"]["support_components"] = []
        data["club"].pop("join_info", None)

        result, errors, _ = BUILDER.build_agenda(data)

        self.assertEqual(errors, [])
        self.assertEqual(result["support_components"], [])
        self.assertEqual(result["club"]["join_info"], [])


    def test_selected_qr_component_rejects_missing_image(self) -> None:
        data = example()
        data["club"]["support_components"] = ["vpm_qr"]
        data["club"]["vpm_qr_image"] = "missing.png"
        _, errors, _ = BUILDER.build_agenda(data, source_dir=ROOT / "examples")
        self.assertTrue(any("does not exist" in error for error in errors))


    def test_custom_support_blocks_validate_identity_content_and_placement(self) -> None:
        data = example()
        data["club"]["custom_support_blocks"] = [
            {"id": "timer_rules", "title": "重复", "lines": ["内容"]},
            {"id": "new", "title": "", "lines": [], "placement": "sideways"},
        ]
        _, errors, _ = BUILDER.build_agenda(data)
        self.assertTrue(any("reserved custom support block id" in error for error in errors))
        self.assertTrue(any("missing title" in error for error in errors))
        self.assertTrue(any("has no content" in error for error in errors))
        self.assertTrue(any("placement must be auto" in error for error in errors))

    def test_meeting_custom_support_blocks_fully_override_club_blocks(self) -> None:
        data = example()
        data["club"]["custom_support_blocks"] = [
            {"id": "usual", "title": "常用块", "lines": ["长期内容"]}
        ]
        data["meeting"]["custom_support_blocks"] = []
        result, errors, _ = BUILDER.build_agenda(data)
        self.assertEqual(errors, [])
        self.assertEqual(result["custom_support_blocks"], [])

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
            {"id": "photo_break", "minutes": 4},
            {"id": "sharing", "minutes": 7},
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
        data["standard_overrides"] = [
            {"id": "photo_break", "minutes": 4},
            {"id": "sharing", "minutes": 7},
        ]
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

    def test_agenda_overrides_change_generated_items_and_reclose_timeline(self) -> None:
        data = example()
        data["meeting"]["end"] = "21:30:30"
        data["agenda_overrides"] = [
            {
                "id": "timer_intro",
                "minutes": 1,
                "owner": "新时间官",
                "label": "时间规则快速说明",
                "transition_after": 0.5,
            },
            {"id": "general_evaluation", "minutes": 10},
        ]
        result, errors, _ = BUILDER.build_agenda(data)
        self.assertEqual(errors, [])
        by_id = {row["id"]: row for row in result["timeline"]}
        self.assertEqual(by_id["timer_intro"]["duration"], 1)
        self.assertEqual(by_id["timer_intro"]["owner"], "新时间官")
        self.assertEqual(by_id["timer_intro"]["label"], "时间规则快速说明")
        self.assertEqual(by_id["timer_intro"]["transition_after"], 0.5)
        self.assertEqual(by_id["general_evaluation"]["duration"], 10)
        self.assertEqual(result["computed"]["total_minutes"], 120.5)
        self.assertEqual(result["computed"]["final_end"], "21:30:30")

    def test_agenda_override_can_remove_an_item_and_reclose_timeline(self) -> None:
        data = example()
        data["standard_overrides"] = [{"id": "sharing", "minutes": 10}]
        data["agenda_overrides"] = [{"id": "photo_break", "enabled": False}]
        result, errors, _ = BUILDER.build_agenda(data)
        self.assertEqual(errors, [])
        self.assertNotIn("photo_break", {row["id"] for row in result["timeline"]})
        self.assertEqual(result["computed"]["total_minutes"], 120)
        self.assertEqual(result["computed"]["final_end"], "21:30")

    def test_agenda_override_after_moves_item_without_changing_section(self) -> None:
        data = example()
        data["agenda_overrides"] = [
            {"id": "table_topics_evaluation", "after": "table_topics"}
        ]
        result, errors, _ = BUILDER.build_agenda(data)
        self.assertEqual(errors, [])

        ids = [row["id"] for row in result["timeline"]]
        table_topics_index = ids.index("table_topics")
        evaluation_index = ids.index("table_topics_evaluation")
        self.assertEqual(evaluation_index, table_topics_index + 1)
        self.assertLess(evaluation_index, ids.index("photo_break"))
        self.assertEqual(result["timeline"][table_topics_index]["section"], "first_half")
        self.assertEqual(result["timeline"][evaluation_index]["section"], "second_half")
        self.assertEqual(result["computed"]["total_minutes"], 120)
        self.assertEqual(result["computed"]["final_end"], "21:30")

    def test_agenda_override_accepts_all_explicit_sections(self) -> None:
        data = example()
        expected_sections = {
            "prepared_speech:1": "opening",
            "timer_intro": "first_half",
            "table_topics": "second_half",
            "prepared_evaluation:1": "closing",
        }
        data["agenda_overrides"] = [
            {"id": item_id, "section": section}
            for item_id, section in expected_sections.items()
        ]
        result, errors, _ = BUILDER.build_agenda(data)
        self.assertEqual(errors, [])

        by_id = {row["id"]: row for row in result["timeline"]}
        for item_id, section in expected_sections.items():
            with self.subTest(item_id=item_id, section=section):
                self.assertEqual(by_id[item_id]["section"], section)
        self.assertEqual(result["computed"]["total_minutes"], 120)
        self.assertEqual(result["computed"]["final_end"], "21:30")

    def test_agenda_override_rejects_invalid_section(self) -> None:
        data = example()
        data["agenda_overrides"] = [
            {"id": "table_topics_evaluation", "section": "intermission"}
        ]
        _, errors, _ = BUILDER.build_agenda(data)
        self.assertTrue(
            any(
                "section must be opening, first_half, second_half, or closing" in error
                for error in errors
            ),
            errors,
        )

    def test_agenda_override_after_rejects_invalid_reorder_graphs(self) -> None:
        baseline, baseline_errors, _ = BUILDER.build_agenda(example())
        self.assertEqual(baseline_errors, [])
        baseline_ids = [row["id"] for row in baseline["timeline"]]
        cases = (
            (
                [{"id": "table_topics_evaluation", "after": "not-a-real-item"}],
                "references missing after anchor",
            ),
            (
                [{"id": "table_topics", "after": "table_topics"}],
                "cannot be placed after itself",
            ),
            (
                [
                    {
                        "id": "prepared_evaluation:1",
                        "after": "prepared_evaluation:2",
                    },
                    {
                        "id": "prepared_evaluation:2",
                        "after": "prepared_evaluation:1",
                    },
                ],
                "contains a cycle",
            ),
        )
        for overrides, expected_error in cases:
            with self.subTest(expected_error=expected_error):
                data = example()
                data["agenda_overrides"] = overrides
                result, errors, _ = BUILDER.build_agenda(data)
                self.assertTrue(
                    any(expected_error in error for error in errors),
                    errors,
                )
                self.assertEqual(
                    [row["id"] for row in result["timeline"]],
                    baseline_ids,
                )

    def test_agenda_override_after_resolves_reverse_declared_dependency_chain(self) -> None:
        data = example()
        data["agenda_overrides"] = [
            {
                "id": "prepared_evaluation:3",
                "after": "prepared_evaluation:2",
            },
            {
                "id": "prepared_evaluation:2",
                "after": "prepared_evaluation:1",
            },
            {"id": "prepared_evaluation:1", "after": "table_topics"},
        ]
        result, errors, _ = BUILDER.build_agenda(data)
        self.assertEqual(errors, [])

        ids = [row["id"] for row in result["timeline"]]
        table_topics_index = ids.index("table_topics")
        self.assertEqual(
            ids[table_topics_index : table_topics_index + 4],
            [
                "table_topics",
                "prepared_evaluation:1",
                "prepared_evaluation:2",
                "prepared_evaluation:3",
            ],
        )
        self.assertLess(ids.index("prepared_evaluation:3"), ids.index("photo_break"))
        by_id = {row["id"]: row for row in result["timeline"]}
        for item_id in (
            "prepared_evaluation:1",
            "prepared_evaluation:2",
            "prepared_evaluation:3",
        ):
            self.assertEqual(by_id[item_id]["section"], "second_half")
        self.assertEqual(result["computed"]["total_minutes"], 120)
        self.assertEqual(result["computed"]["final_end"], "21:30")

    def test_agenda_override_rejects_evaluations_before_their_sessions(self) -> None:
        cases = (
            (
                {"id": "prepared_evaluation:1", "after": "guest_introduction"},
                "agenda order requires prepared_evaluation:1 after prepared_speech:1",
            ),
            (
                {"id": "table_topics_evaluation", "after": "prepared_speech:1"},
                "agenda order requires table_topics_evaluation after table_topics",
            ),
        )
        baseline, baseline_errors, _ = BUILDER.build_agenda(example())
        self.assertEqual(baseline_errors, [])
        baseline_ids = [row["id"] for row in baseline["timeline"]]

        for override, expected_error in cases:
            with self.subTest(override=override):
                data = example()
                data["agenda_overrides"] = [override]
                result, errors, _ = BUILDER.build_agenda(data)
                self.assertIn(expected_error, errors)
                self.assertEqual(
                    [row["id"] for row in result["timeline"]],
                    baseline_ids,
                )

    def test_agenda_override_keeps_general_evaluation_and_sharing_in_closing(self) -> None:
        cases = (
            (
                {"id": "general_evaluation", "after": "guest_introduction"},
                "agenda order requires general_evaluation after all main and feedback items",
            ),
            (
                {"id": "sharing", "after": "prepared_speech:1"},
                "agenda order requires sharing after all main and feedback items",
            ),
            (
                {"id": "general_evaluation", "section": "second_half"},
                "agenda order requires general_evaluation to remain in the closing section",
            ),
            (
                {"id": "sharing", "section": "first_half"},
                "agenda order requires sharing to remain in the closing section",
            ),
            (
                {"id": "general_evaluation", "after": "awards"},
                "agenda order requires general_evaluation before awards and meeting close",
            ),
            (
                {"id": "sharing", "after": "president_closing"},
                "agenda order requires sharing before awards and meeting close",
            ),
        )
        for override, expected_error in cases:
            with self.subTest(override=override):
                data = example()
                data["agenda_overrides"] = [override]
                _, errors, _ = BUILDER.build_agenda(data)
                self.assertTrue(
                    any(expected_error in error for error in errors),
                    errors,
                )

    def test_agenda_override_allows_general_evaluation_and_sharing_to_swap(self) -> None:
        data = example()
        data["agenda_overrides"] = [
            {"id": "general_evaluation", "after": "timer_report"}
        ]
        result, errors, _ = BUILDER.build_agenda(data)
        self.assertEqual(errors, [])

        ids = [row["id"] for row in result["timeline"]]
        self.assertLess(ids.index("timer_report"), ids.index("general_evaluation"))
        self.assertLess(ids.index("general_evaluation"), ids.index("sharing"))
        by_id = {row["id"]: row for row in result["timeline"]}
        self.assertEqual(by_id["general_evaluation"]["section"], "closing")
        self.assertEqual(by_id["sharing"]["section"], "closing")
        self.assertEqual(result["computed"]["total_minutes"], 120)
        self.assertEqual(result["computed"]["final_end"], "21:30")

    def test_agenda_override_keeps_president_closing_as_the_final_item(self) -> None:
        data = example()
        data["agenda_overrides"] = [
            {"id": "awards", "after": "president_closing"}
        ]

        _, errors, _ = BUILDER.build_agenda(data)

        self.assertIn(
            "agenda order requires president_closing to remain the final meeting item",
            errors,
        )

    def test_marathon_style_reorder_chain_preserves_original_sections(self) -> None:
        data = example()
        data["meeting"]["end"] = "21:31"
        data["impromptu"] = None
        data["prepared_speeches"] = [
            {
                "speaker": f"演讲者{index}",
                "title": f"演讲题目{index}",
                "evaluator": f"点评人{index}",
            }
            for index in range(1, 6)
        ]
        chain = [
            ("prepared_evaluation:1", "prepared_speech:1"),
            ("prepared_speech:2", "prepared_evaluation:1"),
            ("prepared_evaluation:2", "prepared_speech:2"),
            ("prepared_speech:3", "prepared_evaluation:2"),
            ("prepared_evaluation:3", "prepared_speech:3"),
            ("prepared_speech:4", "prepared_evaluation:3"),
            ("prepared_evaluation:4", "prepared_speech:4"),
            ("prepared_speech:5", "prepared_evaluation:4"),
            ("prepared_evaluation:5", "prepared_speech:5"),
            ("photo_break", "prepared_evaluation:5"),
            ("grammarian_report", "photo_break"),
            ("ah_counter_report", "grammarian_report"),
            ("timer_report", "ah_counter_report"),
            ("sharing", "timer_report"),
            ("general_evaluation", "sharing"),
            ("awards", "general_evaluation"),
            ("president_closing", "awards"),
        ]
        data["agenda_overrides"] = [
            {"id": item_id, "after": anchor_id}
            for item_id, anchor_id in reversed(chain)
        ]
        result, errors, _ = BUILDER.build_agenda(data)
        self.assertEqual(errors, [])
        self.assertEqual(result["layout"], "marathon")

        ids = [row["id"] for row in result["timeline"]]
        expected_tail = ["prepared_speech:1", *(item_id for item_id, _ in chain)]
        self.assertEqual(ids[ids.index("prepared_speech:1") :], expected_tail)

        by_id = {row["id"]: row for row in result["timeline"]}
        for index in range(1, 6):
            self.assertEqual(
                by_id[f"prepared_evaluation:{index}"]["section"],
                "second_half",
            )
        for item_id in (
            "sharing",
            "general_evaluation",
            "awards",
            "president_closing",
        ):
            self.assertEqual(by_id[item_id]["section"], "closing")
        self.assertEqual(result["computed"]["total_minutes"], 121)
        self.assertEqual(result["computed"]["final_end"], "21:31")

    def test_agenda_overrides_reject_missing_and_duplicate_definitions(self) -> None:
        missing_id = example()
        missing_id["agenda_overrides"] = [{"minutes": 1}]
        _, missing_id_errors, _ = BUILDER.build_agenda(missing_id)
        self.assertTrue(any("is missing id" in error for error in missing_id_errors))

        missing_target = example()
        missing_target["agenda_overrides"] = [
            {"id": "not-a-real-item", "minutes": 1}
        ]
        _, missing_target_errors, _ = BUILDER.build_agenda(missing_target)
        self.assertTrue(
            any("references missing item" in error for error in missing_target_errors)
        )

        duplicate = example()
        duplicate["agenda_overrides"] = [
            {"id": "timer_intro", "minutes": 1},
            {"id": "timer_intro", "owner": "新时间官"},
        ]
        _, duplicate_errors, _ = BUILDER.build_agenda(duplicate)
        self.assertTrue(
            any("duplicate agenda override" in error for error in duplicate_errors)
        )

        overlap = example()
        overlap["standard_overrides"] = [{"id": "photo_break", "minutes": 4}]
        overlap["agenda_overrides"] = [{"id": "photo_break", "minutes": 5}]
        _, overlap_errors, _ = BUILDER.build_agenda(overlap)
        self.assertTrue(any("overridden twice" in error for error in overlap_errors))

        duplicate_transition = example()
        duplicate_transition["agenda_overrides"] = [
            {"id": "timer_intro", "transition_after": 0.5}
        ]
        duplicate_transition["transition_overrides"] = [
            {"id": "timer_intro", "minutes": 0.5}
        ]
        _, duplicate_transition_errors, _ = BUILDER.build_agenda(
            duplicate_transition
        )
        self.assertTrue(
            any("defined twice" in error for error in duplicate_transition_errors)
        )

    def test_agenda_overrides_block_broken_speech_evaluation_relationships(self) -> None:
        cases = (
            (
                "prepared_speech:1",
                "prepared_evaluation:1 remains but prepared_speech:1 was removed",
            ),
            (
                "table_topics",
                "table_topics_evaluation remains but table_topics was removed",
            ),
        )
        for removed_id, expected_error in cases:
            with self.subTest(removed_id=removed_id):
                data = example()
                data["agenda_overrides"] = [
                    {"id": removed_id, "enabled": False}
                ]
                _, errors, _ = BUILDER.build_agenda(data)
                self.assertIn(expected_error, errors)

    def test_auto_evaluation_does_not_absorb_an_unrelated_time_gap(self) -> None:
        data = example()
        data["impromptu"]["minutes"] = 10
        data["impromptu"]["evaluation_minutes"] = 5
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
