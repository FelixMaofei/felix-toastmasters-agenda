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
SPEC = importlib.util.spec_from_file_location(
    "agenda_runner", ROOT / "scripts" / "run_agenda.py"
)
assert SPEC and SPEC.loader
RUNNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNNER)


def valid_pdf(label: str) -> bytes:
    return b"%PDF-1.7\n" + label.encode("utf-8") + b"\n" + (b"P" * 1100)


def valid_png(label: str) -> bytes:
    return b"\x89PNG\r\n\x1a\n" + label.encode("utf-8") + b"\n" + (b"N" * 1100)


class AgendaRunnerTests(unittest.TestCase):
    def test_json_subprocess_output_is_parsed(self) -> None:
        code, payload = RUNNER.run_json_command(
            [sys.executable, "-c", 'print("{\\\"ok\\\": true}")']
        )
        self.assertEqual(code, 0)
        self.assertEqual(payload, {"ok": True})

    def test_non_json_subprocess_output_becomes_a_structured_error(self) -> None:
        code, payload = RUNNER.run_json_command(
            [sys.executable, "-c", 'print("not-json")']
        )
        self.assertEqual(code, 0)
        self.assertFalse(payload["ok"])
        self.assertIn("non-JSON", payload["errors"][0])

    def test_finalize_export_oserror_keeps_old_pair_and_returns_structured_failure(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            temp_dir = Path(temp_text)
            html_path = temp_dir / "agenda.html"
            output_dir = temp_dir / "output"
            html_path.write_text("<html></html>", encoding="utf-8")
            output_dir.mkdir()
            resolved_output_dir = output_dir.resolve()
            old_pdf = valid_pdf("previous valid pdf")
            old_png = valid_png("previous valid png")
            (output_dir / "agenda.pdf").write_bytes(old_pdf)
            (output_dir / "agenda.png").write_bytes(old_png)

            stderr = io.StringIO()
            args = argparse.Namespace(input_html=html_path, output_dir=output_dir)
            with mock.patch.object(
                RUNNER, "run_json_command", side_effect=OSError("exporter unavailable")
            ), contextlib.redirect_stderr(stderr):
                return_code = RUNNER.finalize(args)

            self.assertEqual(return_code, 2)
            self.assertEqual((output_dir / "agenda.pdf").read_bytes(), old_pdf)
            self.assertEqual((output_dir / "agenda.png").read_bytes(), old_png)
            payload = json.loads(stderr.getvalue())
            self.assertIs(payload["ok"], False)
            self.assertEqual(payload["stage"], "finalize_failed")
            self.assertEqual(payload["export_exit_code"], 2)
            self.assertTrue(payload["last_good_preserved"])
            self.assertIn("exporter unavailable", payload["errors"][0])
            self.assertEqual(
                payload["last_good_paths"],
                [
                    str(resolved_output_dir / "agenda.pdf"),
                    str(resolved_output_dir / "agenda.png"),
                ],
            )

    def test_incomplete_current_artifacts_are_never_reported_as_last_good(self) -> None:
        variants = {
            "pdf_only": {"agenda.pdf": valid_pdf("orphan pdf")},
            "png_only": {"agenda.png": valid_png("orphan png")},
            "page_fragment_only": {"agenda-page-1.png": b"orphan page"},
        }
        for name, files in variants.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temp_text:
                temp_dir = Path(temp_text)
                html_path = temp_dir / "agenda.html"
                output_dir = temp_dir / "output"
                html_path.write_text("<html></html>", encoding="utf-8")
                output_dir.mkdir()
                for filename, content in files.items():
                    (output_dir / filename).write_bytes(content)

                stderr = io.StringIO()
                args = argparse.Namespace(input_html=html_path, output_dir=output_dir)
                with mock.patch.object(
                    RUNNER,
                    "run_json_command",
                    return_value=(2, {"ok": False, "errors": ["export failed"]}),
                ), contextlib.redirect_stderr(stderr):
                    return_code = RUNNER.finalize(args)

                self.assertEqual(return_code, 2)
                payload = json.loads(stderr.getvalue())
                self.assertFalse(payload["last_good_preserved"])
                self.assertEqual(payload["last_good_paths"], [])
                self.assertNotIn(
                    "Keep the previous usable PDF and PNG",
                    payload["next_action"],
                )
                for filename, content in files.items():
                    self.assertEqual((output_dir / filename).read_bytes(), content)

    def test_zero_byte_current_pair_is_not_reported_as_last_good(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            temp_dir = Path(temp_text)
            html_path = temp_dir / "agenda.html"
            output_dir = temp_dir / "output"
            html_path.write_text("<html></html>", encoding="utf-8")
            output_dir.mkdir()
            (output_dir / "agenda.pdf").write_bytes(b"")
            (output_dir / "agenda.png").write_bytes(b"")

            stderr = io.StringIO()
            args = argparse.Namespace(input_html=html_path, output_dir=output_dir)
            with mock.patch.object(
                RUNNER,
                "run_json_command",
                return_value=(2, {"ok": False, "errors": ["export failed"]}),
            ), contextlib.redirect_stderr(stderr):
                return_code = RUNNER.finalize(args)

            self.assertEqual(return_code, 2)
            payload = json.loads(stderr.getvalue())
            self.assertFalse(payload["last_good_preserved"])
            self.assertEqual(payload["last_good_paths"], [])
            self.assertEqual((output_dir / "agenda.pdf").read_bytes(), b"")
            self.assertEqual((output_dir / "agenda.png").read_bytes(), b"")

    def test_nonzero_exit_overrides_true_payload_and_reports_exit_code(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            temp_dir = Path(temp_text)
            html_path = temp_dir / "agenda.html"
            output_dir = temp_dir / "output"
            html_path.write_text("<html></html>", encoding="utf-8")

            stderr = io.StringIO()
            args = argparse.Namespace(input_html=html_path, output_dir=output_dir)
            with mock.patch.object(
                RUNNER,
                "run_json_command",
                return_value=(9, {"ok": True, "pages": 1}),
            ), contextlib.redirect_stderr(stderr):
                return_code = RUNNER.finalize(args)

            self.assertEqual(return_code, 2)
            payload = json.loads(stderr.getvalue())
            self.assertIs(payload["ok"], False)
            self.assertEqual(payload["export_exit_code"], 9)
            self.assertIn("code 9", payload["errors"][0])
            self.assertFalse(payload["last_good_preserved"])
            self.assertNotIn(
                "Keep the previous usable PDF and PNG",
                payload["next_action"],
            )

    def test_invalid_staged_pairs_are_never_finalized(self) -> None:
        variants = {
            "zero_bytes": (b"", b""),
            "wrong_signatures": (b"X" * 1101, b"Y" * 1101),
        }
        for name, (staged_pdf, staged_png) in variants.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temp_text:
                temp_dir = Path(temp_text)
                html_path = temp_dir / "agenda.html"
                output_dir = temp_dir / "output"
                html_path.write_text("<html></html>", encoding="utf-8")

                def invalid_export(command: list[str], **_kwargs: object):
                    staging_dir = Path(command[-1])
                    (staging_dir / "agenda.pdf").write_bytes(staged_pdf)
                    (staging_dir / "agenda.png").write_bytes(staged_png)
                    return 0, {"ok": True, "pages": 1}

                stderr = io.StringIO()
                args = argparse.Namespace(input_html=html_path, output_dir=output_dir)
                with mock.patch.object(
                    RUNNER, "run_json_command", side_effect=invalid_export
                ), contextlib.redirect_stderr(stderr):
                    return_code = RUNNER.finalize(args)

                self.assertEqual(return_code, 2)
                self.assertFalse((output_dir / "agenda.pdf").exists())
                self.assertFalse((output_dir / "agenda.png").exists())
                payload = json.loads(stderr.getvalue())
                self.assertIs(payload["ok"], False)
                self.assertEqual(payload["stage"], "finalize_failed")
                self.assertFalse(payload["last_good_preserved"])
                self.assertIn("complete PDF and PNG pair", payload["errors"][0])

    def test_incomplete_current_pair_does_not_partially_update_previous_pair(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            temp_dir = Path(temp_text)
            html_path = temp_dir / "agenda.html"
            output_dir = temp_dir / "output"
            html_path.write_text("<html></html>", encoding="utf-8")
            output_dir.mkdir()
            old_previous_pdf = valid_pdf("older previous pdf")
            old_previous_png = valid_png("older previous png")
            new_pdf = valid_pdf("new valid pdf")
            new_png = valid_png("new valid png")
            (output_dir / "agenda.pdf").write_bytes(valid_pdf("orphan current pdf"))
            (output_dir / "agenda.previous.pdf").write_bytes(old_previous_pdf)
            (output_dir / "agenda.previous.png").write_bytes(old_previous_png)

            def successful_export(command: list[str], **_kwargs: object):
                staging_dir = Path(command[-1])
                (staging_dir / "agenda.pdf").write_bytes(new_pdf)
                (staging_dir / "agenda.png").write_bytes(new_png)
                return 0, {"ok": True, "pages": 1}

            stdout = io.StringIO()
            args = argparse.Namespace(input_html=html_path, output_dir=output_dir)
            with mock.patch.object(
                RUNNER, "run_json_command", side_effect=successful_export
            ), contextlib.redirect_stdout(stdout):
                return_code = RUNNER.finalize(args)

            self.assertEqual(return_code, 0)
            self.assertEqual((output_dir / "agenda.pdf").read_bytes(), new_pdf)
            self.assertEqual((output_dir / "agenda.png").read_bytes(), new_png)
            self.assertEqual(
                (output_dir / "agenda.previous.pdf").read_bytes(), old_previous_pdf
            )
            self.assertEqual(
                (output_dir / "agenda.previous.png").read_bytes(), old_previous_png
            )
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["previous_version_paths"], [])

    def test_sixth_copy_failure_rolls_back_previous_and_current_files(self) -> None:
        self._assert_transaction_failure_rolls_back_all_files("copy2", 6)

    def test_archive_replace_failure_rolls_back_previous_and_current_files(
        self,
    ) -> None:
        self._assert_transaction_failure_rolls_back_all_files("replace", 2)

    def test_new_version_replace_failure_rolls_back_previous_and_current_files(
        self,
    ) -> None:
        self._assert_transaction_failure_rolls_back_all_files("replace", 4)

    def _assert_transaction_failure_rolls_back_all_files(
        self,
        method_name: str,
        fail_at: int,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            temp_dir = Path(temp_text)
            html_path = temp_dir / "agenda.html"
            output_dir = temp_dir / "output"
            html_path.write_text("<html></html>", encoding="utf-8")
            output_dir.mkdir()
            current_pdf = valid_pdf("current old pdf")
            current_png = valid_png("current old png")
            previous_pdf = valid_pdf("previous older pdf")
            previous_png = valid_png("previous older png")
            new_pdf = valid_pdf("new valid pdf")
            new_png = valid_png("new valid png")
            (output_dir / "agenda.pdf").write_bytes(current_pdf)
            (output_dir / "agenda.png").write_bytes(current_png)
            (output_dir / "agenda.previous.pdf").write_bytes(previous_pdf)
            (output_dir / "agenda.previous.png").write_bytes(previous_png)

            def successful_export(command: list[str], **_kwargs: object):
                staging_dir = Path(command[-1])
                (staging_dir / "agenda.pdf").write_bytes(new_pdf)
                (staging_dir / "agenda.png").write_bytes(new_png)
                return 0, {"ok": True, "pages": 1}

            if method_name == "copy2":
                patch_target = RUNNER.shutil
                original = RUNNER.shutil.copy2
            else:
                patch_target = RUNNER.os
                original = RUNNER.os.replace
            call_count = 0

            def fail_selected_call(*call_args: object, **call_kwargs: object):
                nonlocal call_count
                call_count += 1
                if call_count == fail_at:
                    raise OSError(f"{method_name} call {fail_at} failed")
                return original(*call_args, **call_kwargs)

            stderr = io.StringIO()
            args = argparse.Namespace(input_html=html_path, output_dir=output_dir)
            with mock.patch.object(
                RUNNER, "run_json_command", side_effect=successful_export
            ), mock.patch.object(
                patch_target, method_name, side_effect=fail_selected_call
            ), contextlib.redirect_stderr(stderr):
                return_code = RUNNER.finalize(args)

            self.assertEqual(return_code, 2)
            self.assertGreaterEqual(call_count, fail_at)
            self.assertEqual((output_dir / "agenda.pdf").read_bytes(), current_pdf)
            self.assertEqual((output_dir / "agenda.png").read_bytes(), current_png)
            self.assertEqual(
                (output_dir / "agenda.previous.pdf").read_bytes(), previous_pdf
            )
            self.assertEqual(
                (output_dir / "agenda.previous.png").read_bytes(), previous_png
            )
            payload = json.loads(stderr.getvalue())
            self.assertIs(payload["ok"], False)
            self.assertIn(
                f"{method_name} call {fail_at} failed",
                payload["errors"][0],
            )

    def test_finalize_success_keeps_new_files_and_archives_previous_version(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            temp_dir = Path(temp_text)
            html_path = temp_dir / "agenda.html"
            output_dir = temp_dir / "output"
            html_path.write_text("<html></html>", encoding="utf-8")
            output_dir.mkdir()
            resolved_output_dir = output_dir.resolve()
            old_pdf = valid_pdf("previous valid pdf")
            old_png = valid_png("previous valid png")
            new_pdf = valid_pdf("new valid pdf")
            new_png = valid_png("new valid png")
            (output_dir / "agenda.pdf").write_bytes(old_pdf)
            (output_dir / "agenda.png").write_bytes(old_png)

            def successful_export(command: list[str], **_kwargs: object):
                staging_dir = Path(command[-1])
                (staging_dir / "agenda.pdf").write_bytes(new_pdf)
                (staging_dir / "agenda.png").write_bytes(new_png)
                return 0, {"ok": True, "pages": 1}

            stdout = io.StringIO()
            args = argparse.Namespace(input_html=html_path, output_dir=output_dir)
            with mock.patch.object(
                RUNNER, "run_json_command", side_effect=successful_export
            ), contextlib.redirect_stdout(stdout):
                return_code = RUNNER.finalize(args)

            self.assertEqual(return_code, 0)
            self.assertEqual((output_dir / "agenda.pdf").read_bytes(), new_pdf)
            self.assertEqual((output_dir / "agenda.png").read_bytes(), new_png)
            self.assertEqual(
                (output_dir / "agenda.previous.pdf").read_bytes(), old_pdf
            )
            self.assertEqual(
                (output_dir / "agenda.previous.png").read_bytes(), old_png
            )

            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["stage"], "finalized")
            self.assertEqual(payload["pdf"], str(resolved_output_dir / "agenda.pdf"))
            self.assertEqual(payload["png"], str(resolved_output_dir / "agenda.png"))
            self.assertEqual(
                set(payload["previous_version_paths"]),
                {
                    str(resolved_output_dir / "agenda.previous.pdf"),
                    str(resolved_output_dir / "agenda.previous.png"),
                },
            )


if __name__ == "__main__":
    unittest.main()
