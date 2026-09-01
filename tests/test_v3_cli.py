from __future__ import annotations

import argparse
import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BUILDER = load_module("v3_agenda_builder", ROOT / "scripts" / "build_agenda.py")
RUNNER = load_module("v3_agenda_runner", ROOT / "scripts" / "run_agenda.py")
RENDERER = load_module(
    "v3_agenda_renderer_for_cli_tests", ROOT / "scripts" / "agenda_renderer.py"
)


def example() -> dict:
    return json.loads(
        (ROOT / "examples" / "meeting.example.json").read_text(encoding="utf-8")
    )


def valid_pdf() -> bytes:
    return b"%PDF-1.7\n" + (b"P" * 1100)


def valid_png() -> bytes:
    return b"\x89PNG\r\n\x1a\n" + (b"N" * 1100)


def write_preview_bundle(directory: Path) -> tuple[Path, bytes, bytes]:
    directory.mkdir(parents=True, exist_ok=True)
    html_path = directory / "agenda.preview.html"
    pdf_path = directory / "agenda.preview.pdf"
    png_path = directory / "agenda.preview.png"
    html_path.write_text(
        '<html><head><meta name="agenda-workflow" content="v3-preview">'
        '<meta name="agenda-page-count" content="1"></head>'
        "<body>approved</body></html>",
        encoding="utf-8",
    )
    pdf_bytes = valid_pdf()
    png_bytes = valid_png()
    pdf_path.write_bytes(pdf_bytes)
    png_path.write_bytes(png_bytes)
    manifest = {
        "workflow_version": 3,
        "stage": "preview",
        "page_count": 1,
        "facts_sha256": "a" * 64,
        "view_sha256": "b" * 64,
        "html_sha256": RUNNER.file_sha256(html_path),
        "pdf_sha256": RUNNER.file_sha256(pdf_path),
        "png_sha256": RUNNER.file_sha256(png_path),
        "outputs": {
            "html": html_path.name,
            "pdf": pdf_path.name,
            "png": png_path.name,
        },
    }
    (directory / RUNNER.V3_PREVIEW_MANIFEST_NAME).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return html_path, pdf_bytes, png_bytes


def all_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value).union(*(all_keys(child) for child in value.values()))
    if isinstance(value, list):
        return set().union(*(all_keys(child) for child in value))
    return set()


class V3FactsTests(unittest.TestCase):
    def test_v3_facts_reject_bilingual_language(self) -> None:
        data = example()
        data["club"]["language"] = "bilingual"

        _, errors, _ = BUILDER.build_agenda(data, facts_only=True)

        self.assertIn(
            "V3 club.language must be zh or en; bilingual is supported only by V2",
            errors,
        )

    def test_v2_facts_keep_bilingual_compatibility(self) -> None:
        data = example()
        data["club"]["language"] = "bilingual"

        result, errors, _ = BUILDER.build_agenda(data, facts_only=False)

        self.assertEqual(errors, [])
        self.assertEqual(result["club"]["language"], "bilingual")
        self.assertIn("会议流程 / Agenda", BUILDER.render_html(result))

    def test_facts_ignore_v2_visual_input_and_row_limit(self) -> None:
        data = example()
        data["meeting"].update(
            {
                "layout": "not-a-layout",
                "feature_item": "missing-item",
                "visual_theme": "not-a-theme",
                "visual_preferences": {"unknown": "value"},
                "theme_image": "missing-image.png",
                "end": "23:30",
            }
        )
        data["prepared_speeches"] = [
            {
                "speaker": f"Speaker {index}",
                "title": f"Speech {index}",
                "evaluator": f"Evaluator {index}",
            }
            for index in range(1, 13)
        ]

        result, errors, _ = BUILDER.build_agenda(data, facts_only=True)

        self.assertEqual(errors, [])
        self.assertEqual(result["schema_version"], 3)
        self.assertEqual(result["computed"]["row_count"], 41)
        forbidden = {
            "layout",
            "feature_item",
            "visual_theme",
            "visual_preferences",
            "page_count",
            "theme_image",
        }
        self.assertTrue(forbidden.isdisjoint(all_keys(result)))

    def test_support_blocks_are_materialized_and_qr_is_self_contained(self) -> None:
        data = example()
        data["club"]["support_components"].extend(["vpm_qr", "voting_qr"])
        data["club"]["vpm_qr_image"] = "../assets/toastmasters-logo.png"
        data["meeting"]["voting_qr_image"] = "../assets/toastmasters-logo.png"

        result, errors, _ = BUILDER.build_agenda(
            data,
            source_dir=ROOT / "examples",
            facts_only=True,
        )

        self.assertEqual(errors, [])
        blocks = {block["id"]: block for block in result["support_blocks"]}
        self.assertEqual(blocks["timer_rules"]["kind"], "timing")
        self.assertTrue(blocks["timer_rules"]["entries"])
        self.assertEqual(blocks["officers"]["kind"], "pairs")
        self.assertTrue(blocks["toastmasters_intro"]["lines"])
        self.assertTrue(blocks["meeting_boundaries"]["lines"])
        for component in ("vpm_qr", "voting_qr"):
            self.assertEqual(blocks[component]["kind"], "image")
            self.assertTrue(blocks[component]["data_uri"].startswith("data:image/png"))

    def test_pathways_are_attached_by_exact_owner_name_only(self) -> None:
        data = example()
        data["participant_pathways"] = {
            "成员B": "PM L1",
            "不存在的人": "DL L5",
        }

        result, errors, _ = BUILDER.build_agenda(data, facts_only=True)

        self.assertEqual(errors, [])
        owned = [row for row in result["timeline"] if row["owner"] == "成员B"]
        self.assertTrue(owned)
        self.assertTrue(all(row["pathways"] == "PM L1" for row in owned))
        self.assertTrue(
            all(
                row["pathways"] == ""
                for row in result["timeline"]
                if row["owner"] != "成员B"
            )
        )
        markdown = BUILDER.render_markdown(result)
        self.assertIn("Pathways 进展", markdown)
        self.assertIn("PM L1", markdown)

    def test_invalid_pathways_and_custom_backstage_are_explicit_errors(self) -> None:
        data = example()
        data["participant_pathways"] = {"成员A": ""}
        data["club"]["custom_support_blocks"] = [
            {"id": "backstage", "title": "幕后", "lines": ["不应覆盖"]}
        ]

        _, errors, _ = BUILDER.build_agenda(data, facts_only=True)

        self.assertTrue(any("non-empty string" in error for error in errors))
        self.assertTrue(any("conflicts with" in error for error in errors))

    def test_custom_support_block_can_be_classified_in_either_view_group(self) -> None:
        data = example()
        data["club"]["support_components"] = []
        data["club"]["custom_support_blocks"] = [
            {"id": "room_notes", "title": "现场提醒", "lines": ["记得签到"]}
        ]
        result, errors, _ = BUILDER.build_agenda(data, facts_only=True)
        self.assertEqual(errors, [])
        custom = next(
            block for block in result["support_blocks"] if block["id"] == "room_notes"
        )
        self.assertNotIn("group", custom)

        base_view = {
            "view_version": 1,
            "content_emphasis": None,
            "display_columns": ["time", "activity", "owner", "duration"],
            "density": "balanced",
            "design": {"text_scale": "standard", "contrast": "clear"},
        }
        for group in ("operations", "background"):
            view = {
                **base_view,
                "component_flow": {
                    "operations": ["backstage"],
                    "background": [],
                },
            }
            view["component_flow"][group].append("room_notes")
            RENDERER.validate_view(result, view)

    def test_pathways_column_requires_materialized_timeline_data(self) -> None:
        def view_for(result: dict) -> dict:
            operations = ["backstage"] if result["backstage"] else []
            background: list[str] = []
            for block in result["support_blocks"]:
                target = operations if block.get("group") == "operations" else background
                target.append(block["id"])
            return {
                "view_version": 1,
                "content_emphasis": None,
                "display_columns": [
                    "time",
                    "activity",
                    "owner",
                    "pathways",
                    "duration",
                ],
                "component_flow": {
                    "operations": operations,
                    "background": background,
                },
                "density": "balanced",
                "design": {"text_scale": "standard", "contrast": "clear"},
            }

        without_pathways, errors, _ = BUILDER.build_agenda(
            example(), facts_only=True
        )
        self.assertEqual(errors, [])
        with self.assertRaisesRegex(RENDERER.AgendaRenderError, "no real data"):
            RENDERER.validate_view(without_pathways, view_for(without_pathways))

        data = example()
        data["participant_pathways"] = {"成员B": "PM L1"}
        with_pathways, errors, _ = BUILDER.build_agenda(data, facts_only=True)
        self.assertEqual(errors, [])
        RENDERER.validate_view(with_pathways, view_for(with_pathways))


class V3RunnerTests(unittest.TestCase):
    def test_draft_writes_only_fact_stage_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            output_dir = Path(temp_text) / "output"
            args = argparse.Namespace(
                input_json=ROOT / "examples" / "meeting.example.json",
                output_dir=output_dir,
                club_profile=None,
                update_club_profile=False,
                profile_root=None,
            )
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                return_code = RUNNER.draft(args)

            self.assertEqual(return_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["stage"], "drafted")
            self.assertEqual(
                {path.name for path in output_dir.iterdir()},
                {
                    "agenda.computed.json",
                    "agenda.md",
                    "agenda.diagnostics.json",
                    "agenda.manifest.json",
                },
            )
            self.assertFalse((output_dir / "agenda.html").exists())

    def test_first_builds_facts_and_complete_preview_in_one_call(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            temp_dir = Path(temp_text)
            input_path = temp_dir / "meeting.json"
            output_dir = temp_dir / "output"
            input_path.write_text(
                json.dumps(example(), ensure_ascii=False), encoding="utf-8"
            )
            original_run_json_command = RUNNER.run_json_command
            commands: list[list[str]] = []

            def fake_export(command: list[str], **kwargs: object):
                commands.append(command)
                if Path(command[1]) != RUNNER.EXPORT_SCRIPT:
                    return original_run_json_command(command, **kwargs)
                staging_dir = Path(command[-1])
                (staging_dir / "agenda.pdf").write_bytes(valid_pdf())
                (staging_dir / "agenda.png").write_bytes(valid_png())
                return 0, {"ok": True, "pages": 1}

            args = argparse.Namespace(
                input_json=input_path,
                output_dir=output_dir,
                club_profile=None,
                update_club_profile=False,
                profile_root=None,
            )
            stdout = io.StringIO()
            with mock.patch.object(
                RUNNER, "run_json_command", side_effect=fake_export
            ), mock.patch.object(
                RUNNER, "load_v3_renderer", return_value=RENDERER.render_agenda
            ) as v3_loader, contextlib.redirect_stdout(stdout):
                return_code = RUNNER.first(args)

            self.assertEqual(return_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["stage"], "first_previewed")
            self.assertEqual(payload["density"], "balanced")
            self.assertFalse(payload["compact_retry"])
            for name in (
                "agenda.computed.json",
                "agenda.md",
                "agenda.diagnostics.json",
                "agenda.manifest.json",
                "agenda.view.json",
                "agenda.preview.html",
                "agenda.preview.pdf",
                "agenda.preview.png",
                RUNNER.V3_PREVIEW_MANIFEST_NAME,
            ):
                self.assertTrue((output_dir / name).is_file(), name)
            v3_loader.assert_called_once_with()
            build_command = next(
                command for command in commands if Path(command[1]) == RUNNER.BUILD_SCRIPT
            )
            self.assertIn("--facts-only", build_command)
            self.assertNotIn("--html-renderer", build_command)
            self.assertEqual(
                sum(Path(command[1]) == RUNNER.EXPORT_SCRIPT for command in commands),
                1,
            )

    def test_first_stops_before_rendering_when_facts_are_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            temp_dir = Path(temp_text)
            input_path = temp_dir / "meeting.json"
            data = example()
            data["meeting"].pop("date")
            input_path.write_text(
                json.dumps(data, ensure_ascii=False), encoding="utf-8"
            )
            args = argparse.Namespace(
                input_json=input_path,
                output_dir=temp_dir / "output",
                club_profile=None,
                update_club_profile=False,
                profile_root=None,
            )
            stderr = io.StringIO()

            with mock.patch.object(RUNNER, "load_v3_renderer") as renderer_loader, \
                contextlib.redirect_stderr(stderr):
                return_code = RUNNER.first(args)

            self.assertEqual(return_code, 2)
            renderer_loader.assert_not_called()
            payload = json.loads(stderr.getvalue())
            self.assertEqual(payload["stage"], "first_failed")
            self.assertEqual(payload["failed_stage"], "facts")
            self.assertFalse((temp_dir / "output" / "agenda.preview.png").exists())

    def test_default_first_view_covers_components_pathways_and_one_special(self) -> None:
        data = example()
        data["participant_pathways"] = {"成员B": "PM L1"}
        data["special_segments"] = [
            {
                "title": "AI 工作坊",
                "owner": "成员K",
                "minutes": 5,
                "after": "prepared_speech:1",
            }
        ]
        data["club"]["custom_support_blocks"] = [
            {"id": "room_notes", "title": "现场提醒", "lines": ["记得签到"]},
            {"id": "checklist", "title": "执行清单", "lines": ["检查麦克风"]},
        ]
        computed, errors, _ = BUILDER.build_agenda(data, facts_only=True)
        self.assertEqual(errors, [])
        next(
            block
            for block in computed["support_blocks"]
            if block["id"] == "checklist"
        )["group"] = "operations"

        view = RUNNER.build_default_view(computed)

        operations = view["component_flow"]["operations"]
        background = view["component_flow"]["background"]
        expected_ids = {"backstage"}.union(
            block["id"] for block in computed["support_blocks"]
        )
        self.assertEqual(set(operations + background), expected_ids)
        self.assertEqual(len(operations + background), len(expected_ids))
        self.assertIn("backstage", operations)
        self.assertIn("checklist", operations)
        self.assertIn("room_notes", background)
        self.assertEqual(
            view["display_columns"],
            ["time", "activity", "owner", "pathways", "duration"],
        )
        self.assertEqual(
            view["content_emphasis"],
            {"item_id": "special:1", "strength": "clear"},
        )
        self.assertEqual(view["density"], "balanced")
        self.assertEqual(
            view["design"], {"text_scale": "standard", "contrast": "clear"}
        )
        RENDERER.validate_view(computed, view)

    def test_first_retries_compact_only_after_single_page_overflow(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            temp_dir = Path(temp_text)
            input_path = temp_dir / "meeting.json"
            output_dir = temp_dir / "output"
            input_path.write_text(
                json.dumps(example(), ensure_ascii=False), encoding="utf-8"
            )
            original_run_json_command = RUNNER.run_json_command
            export_attempts = 0
            rendered_densities: list[str] = []

            def fake_commands(command: list[str], **kwargs: object):
                nonlocal export_attempts
                if Path(command[1]) != RUNNER.EXPORT_SCRIPT:
                    return original_run_json_command(command, **kwargs)
                export_attempts += 1
                if export_attempts == 1:
                    return 2, {
                        "ok": False,
                        "errors": [
                            "final agenda content does not fit on one A4 page: "
                            "PDF contains 2 pages. Reduce agenda rows or fixed-information "
                            "components before exporting"
                        ],
                    }
                staging_dir = Path(command[-1])
                (staging_dir / "agenda.pdf").write_bytes(valid_pdf())
                (staging_dir / "agenda.png").write_bytes(valid_png())
                return 0, {"ok": True, "pages": 1}

            def fake_renderer(
                _computed: dict, view: dict, **_kwargs: object
            ) -> str:
                rendered_densities.append(view["density"])
                return "<html><body>preview</body></html>"

            args = argparse.Namespace(
                input_json=input_path,
                output_dir=output_dir,
                club_profile=None,
                update_club_profile=False,
                profile_root=None,
            )
            stdout = io.StringIO()
            with mock.patch.object(
                RUNNER, "run_json_command", side_effect=fake_commands
            ), mock.patch.object(
                RUNNER, "load_v3_renderer", return_value=fake_renderer
            ), contextlib.redirect_stdout(stdout):
                return_code = RUNNER.first(args)

            self.assertEqual(return_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertTrue(payload["compact_retry"])
            self.assertEqual(payload["density"], "compact")
            self.assertEqual(rendered_densities, ["balanced", "compact"])
            view = json.loads(
                (output_dir / "agenda.view.json").read_text(encoding="utf-8")
            )
            self.assertEqual(view["density"], "compact")
            self.assertEqual(view["design"]["text_scale"], "standard")

    def test_preview_atomically_saves_the_complete_approved_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            temp_dir = Path(temp_text)
            computed_path = temp_dir / "agenda.computed.json"
            view_path = temp_dir / "agenda.view.json"
            output_dir = temp_dir / "output"
            computed_path.write_text('{"schema_version": 3}', encoding="utf-8")
            view_path.write_text('{"view_version": 1}', encoding="utf-8")

            def fake_export(command: list[str], **_kwargs: object):
                self.assertEqual(Path(command[1]), RUNNER.EXPORT_SCRIPT)
                self.assertNotIn(str(RUNNER.BUILD_SCRIPT), command)
                staging_dir = Path(command[-1])
                (staging_dir / "agenda.pdf").write_bytes(valid_pdf())
                (staging_dir / "agenda.png").write_bytes(valid_png())
                return 0, {"ok": True, "pages": 1}

            args = argparse.Namespace(
                input_computed=computed_path,
                view=view_path,
                output_dir=output_dir,
            )
            stdout = io.StringIO()
            with mock.patch.object(
                RUNNER,
                "load_v3_renderer",
                return_value=lambda *_args, **_kwargs: "<html><body>preview</body></html>",
            ), mock.patch.object(
                RUNNER, "run_json_command", side_effect=fake_export
            ), contextlib.redirect_stdout(stdout):
                return_code = RUNNER.preview(args)

            self.assertEqual(return_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["stage"], "previewed")
            self.assertTrue((output_dir / "agenda.preview.html").is_file())
            self.assertTrue((output_dir / "agenda.preview.pdf").is_file())
            self.assertTrue((output_dir / "agenda.preview.png").is_file())
            self.assertTrue(
                (output_dir / RUNNER.V3_PREVIEW_MANIFEST_NAME).is_file()
            )
            self.assertGreater((output_dir / "agenda.preview.png").stat().st_size, 1000)
            self.assertFalse((output_dir / "agenda.pdf").exists())
            manifest = json.loads(
                (output_dir / RUNNER.V3_PREVIEW_MANIFEST_NAME).read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(manifest["page_count"], 1)
            for artifact in ("html", "pdf", "png"):
                path = output_dir / manifest["outputs"][artifact]
                self.assertEqual(
                    manifest[f"{artifact}_sha256"], RUNNER.file_sha256(path)
                )
            self.assertEqual(manifest["facts_sha256"], RUNNER.file_sha256(computed_path))
            self.assertEqual(manifest["view_sha256"], RUNNER.file_sha256(view_path))

    def test_final_promotes_approved_bytes_without_calling_exporter(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            temp_dir = Path(temp_text)
            preview_dir = temp_dir / "preview"
            output_dir = temp_dir / "output"
            html_path, preview_pdf, preview_png = write_preview_bundle(preview_dir)
            output_dir.mkdir()
            old_pdf = valid_pdf() + b"previous"
            old_png = valid_png() + b"previous"
            (output_dir / "agenda.pdf").write_bytes(old_pdf)
            (output_dir / "agenda.png").write_bytes(old_png)

            args = argparse.Namespace(
                input_html=html_path,
                output_dir=output_dir,
                v3_final=True,
            )
            stdout = io.StringIO()
            with mock.patch.object(RUNNER, "run_json_command") as exporter, \
                contextlib.redirect_stdout(stdout):
                return_code = RUNNER.finalize(args)

            self.assertEqual(return_code, 0)
            exporter.assert_not_called()
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["stage"], "finalized")
            self.assertNotIn("deprecated", payload)
            self.assertEqual((output_dir / "agenda.pdf").read_bytes(), preview_pdf)
            self.assertEqual((output_dir / "agenda.png").read_bytes(), preview_png)
            self.assertEqual(
                (output_dir / "agenda.previous.pdf").read_bytes(), old_pdf
            )
            self.assertEqual(
                (output_dir / "agenda.previous.png").read_bytes(), old_png
            )

    def test_final_rejects_any_tampered_preview_artifact_and_keeps_last_good(self) -> None:
        for artifact in ("html", "pdf", "png"):
            with self.subTest(artifact=artifact), tempfile.TemporaryDirectory() as temp_text:
                temp_dir = Path(temp_text)
                preview_dir = temp_dir / "preview"
                output_dir = temp_dir / "output"
                html_path, _, _ = write_preview_bundle(preview_dir)
                output_dir.mkdir()
                old_pdf = valid_pdf() + b"old"
                old_png = valid_png() + b"old"
                (output_dir / "agenda.pdf").write_bytes(old_pdf)
                (output_dir / "agenda.png").write_bytes(old_png)
                target = preview_dir / f"agenda.preview.{artifact}"
                target.write_bytes(target.read_bytes() + b"tampered")

                args = argparse.Namespace(
                    input_html=html_path,
                    output_dir=output_dir,
                    v3_final=True,
                )
                stderr = io.StringIO()
                with mock.patch.object(RUNNER, "run_json_command") as exporter, \
                    contextlib.redirect_stderr(stderr):
                    return_code = RUNNER.finalize(args)

                self.assertEqual(return_code, 2)
                exporter.assert_not_called()
                self.assertEqual((output_dir / "agenda.pdf").read_bytes(), old_pdf)
                self.assertEqual((output_dir / "agenda.png").read_bytes(), old_png)
                payload = json.loads(stderr.getvalue())
                self.assertEqual(payload["stage"], "finalize_failed")
                self.assertTrue(payload["last_good_preserved"])
                self.assertTrue(
                    any(artifact.upper() in error for error in payload["errors"])
                )

    def test_final_rejects_unmarked_html_and_preserves_previous_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            temp_dir = Path(temp_text)
            html_path = temp_dir / "not-a-preview.html"
            output_dir = temp_dir / "output"
            output_dir.mkdir()
            html_path.write_text("<html><body>unapproved</body></html>", encoding="utf-8")
            old_pdf = valid_pdf()
            old_png = valid_png()
            (output_dir / "agenda.pdf").write_bytes(old_pdf)
            (output_dir / "agenda.png").write_bytes(old_png)
            args = argparse.Namespace(
                input_html=html_path,
                output_dir=output_dir,
                v3_final=True,
            )
            stderr = io.StringIO()

            with mock.patch.object(RUNNER, "run_json_command") as exporter, \
                contextlib.redirect_stderr(stderr):
                return_code = RUNNER.finalize(args)

            self.assertEqual(return_code, 2)
            exporter.assert_not_called()
            self.assertEqual((output_dir / "agenda.pdf").read_bytes(), old_pdf)
            self.assertEqual((output_dir / "agenda.png").read_bytes(), old_png)
            payload = json.loads(stderr.getvalue())
            self.assertEqual(payload["stage"], "finalize_failed")
            self.assertTrue(payload["last_good_preserved"])
            self.assertIn("v3-preview marker is missing", payload["errors"][0])


if __name__ == "__main__":
    unittest.main()
