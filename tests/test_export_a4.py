from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import tempfile
import time
import unittest
from copy import deepcopy
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "agenda_exporter", ROOT / "scripts" / "export_a4.py"
)
assert SPEC and SPEC.loader
EXPORTER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(EXPORTER)

BUILDER_SPEC = importlib.util.spec_from_file_location(
    "agenda_builder_for_export_tests", ROOT / "scripts" / "build_agenda.py"
)
assert BUILDER_SPEC and BUILDER_SPEC.loader
BUILDER = importlib.util.module_from_spec(BUILDER_SPEC)
BUILDER_SPEC.loader.exec_module(BUILDER)


def confirmed_example() -> dict:
    data = json.loads(
        (ROOT / "examples" / "meeting.fixture.json").read_text(encoding="utf-8")
    )
    data["standard_overrides"] = [
        {"id": "photo_break", "minutes": 4},
        {"id": "sharing", "minutes": 6},
    ]
    return data


class FakeChromeProcess:
    def __init__(self, return_code: int | None = None) -> None:
        self.return_code = return_code
        self.terminated = False
        self.killed = False

    def poll(self) -> int | None:
        return self.return_code

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True
        self.return_code = -9

    def wait(self, timeout: float | None = None) -> int:
        self.return_code = 0 if not self.killed else -9
        return self.return_code


class AgendaExporterTests(unittest.TestCase):
    def test_declared_multi_page_html_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            html_path = Path(temp_dir) / "agenda.html"
            html_path.write_text(
                '<meta name="agenda-page-count" content="2">', encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "exactly 1 A4 page"):
                EXPORTER.expected_page_count(html_path)

    def test_single_page_html_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            html_path = Path(temp_dir) / "agenda.html"
            html_path.write_text(
                '<meta name="agenda-page-count" content="1">', encoding="utf-8"
            )
            self.assertEqual(EXPORTER.expected_page_count(html_path), 1)

    def test_a4_portrait_size_tolerance(self) -> None:
        self.assertTrue(EXPORTER.is_a4_portrait((595.28, 841.89)))
        self.assertFalse(EXPORTER.is_a4_portrait((612, 792)))
        self.assertFalse(EXPORTER.is_a4_portrait((841.89, 595.28)))

    def test_visual_audit_dump_is_parsed(self) -> None:
        dump = (
            '<html data-agenda-audit="ok"><body>'
            '<script id="agenda-audit-result" type="application/json">'
            '{"ok":true,"failures":[]}'
            "</script></body></html>"
        )
        self.assertEqual(
            EXPORTER.parse_visual_audit_dump(dump),
            {"ok": True, "failures": []},
        )

    def test_missing_visual_audit_result_returns_none(self) -> None:
        self.assertIsNone(EXPORTER.parse_visual_audit_dump("<html></html>"))

    def test_visual_audit_requirement_is_explicit(self) -> None:
        self.assertTrue(
            EXPORTER.visual_audit_required(
                '<meta name="agenda-visual-audit" content="required">'
            )
        )
        self.assertFalse(EXPORTER.visual_audit_required("<html></html>"))

    def test_chrome_no_sandbox_flags_are_opt_in(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(EXPORTER.chrome_compatibility_flags(), [])
        with mock.patch.dict(
            os.environ, {"AGENDA_CHROME_NO_SANDBOX": "1"}, clear=True
        ):
            self.assertEqual(
                EXPORTER.chrome_compatibility_flags(),
                ["--no-sandbox", "--disable-software-rasterizer"],
            )

    def test_complete_file_checks_pdf_signature_and_eof(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = Path(temp_dir) / "agenda.pdf"
            pdf_path.write_bytes(b"%PDF-1.4\n" + b"x" * 1100 + b"\n%%EOF\n")
            self.assertTrue(EXPORTER.chrome_output_is_complete(pdf_path))
            pdf_path.write_bytes(b"%PDF-1.4\n" + b"x" * 1100)
            self.assertFalse(EXPORTER.chrome_output_is_complete(pdf_path))

    def test_complete_file_checks_png_signature_and_iend(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            png_path = Path(temp_dir) / "agenda.png"
            png_path.write_bytes(
                EXPORTER.PNG_SIGNATURE + b"x" * 1100 + EXPORTER.PNG_IEND
            )
            self.assertTrue(EXPORTER.chrome_output_is_complete(png_path))
            png_path.write_bytes(EXPORTER.PNG_SIGNATURE + b"x" * 1100)
            self.assertFalse(EXPORTER.chrome_output_is_complete(png_path))

    def test_run_chrome_stops_fake_process_after_complete_stable_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = Path(temp_dir) / "agenda.pdf"
            pdf_path.write_bytes(b"%PDF-1.4\n" + b"x" * 1100 + b"\n%%EOF\n")
            process = FakeChromeProcess()
            with mock.patch.object(EXPORTER.subprocess, "Popen", return_value=process), mock.patch.object(
                EXPORTER, "CHROME_FILE_STABLE_SECONDS", 0
            ), mock.patch.object(EXPORTER, "CHROME_POLL_INTERVAL_SECONDS", 0):
                self.assertEqual(
                    EXPORTER.run_chrome(["chrome"], pdf_path, timeout=1), 0
                )
            self.assertTrue(process.terminated)
            self.assertFalse(process.killed)

    def test_run_chrome_preserves_timeout_failure_for_incomplete_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = Path(temp_dir) / "agenda.pdf"
            pdf_path.write_bytes(b"%PDF-1.4\n" + b"x" * 1100)
            process = FakeChromeProcess()
            with mock.patch.object(EXPORTER.subprocess, "Popen", return_value=process):
                self.assertEqual(
                    EXPORTER.run_chrome(["chrome"], pdf_path, timeout=0), 124
                )
            self.assertTrue(process.terminated)

    def test_run_chrome_accepts_complete_output_from_failed_process(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            png_path = Path(temp_dir) / "agenda.png"
            png_path.write_bytes(
                EXPORTER.PNG_SIGNATURE + b"x" * 1100 + EXPORTER.PNG_IEND
            )
            process = FakeChromeProcess(return_code=7)
            with mock.patch.object(EXPORTER.subprocess, "Popen", return_value=process):
                self.assertEqual(
                    EXPORTER.run_chrome(["chrome"], png_path, timeout=1), 0
                )

    def test_stop_chrome_kills_fake_process_that_ignores_terminate(self) -> None:
        process = FakeChromeProcess()
        process.wait = mock.Mock(
            side_effect=[subprocess.TimeoutExpired("chrome", 3), -9]
        )
        EXPORTER.stop_chrome_process(process)
        self.assertTrue(process.terminated)
        self.assertTrue(process.killed)


class ChromeOutputCompletionRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.chrome = EXPORTER.find_chrome()

    def test_real_chrome_pdf_completes_without_waiting_for_timeout(self) -> None:
        if not self.chrome:
            self.skipTest("Chrome/Chromium is not available")
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            html_path = temp_path / "agenda.html"
            pdf_path = temp_path / "agenda.pdf"
            html_path.write_text(
                "<!doctype html><meta charset='utf-8'><style>"
                "@page{size:A4 portrait;margin:12mm}</style><h1>Agenda</h1>",
                encoding="utf-8",
            )
            profile = temp_path / "chrome-profile"
            command = [
                self.chrome,
                "--headless=new",
                "--disable-gpu",
                "--no-first-run",
                "--no-pdf-header-footer",
                f"--user-data-dir={profile}",
                f"--print-to-pdf={pdf_path}",
                html_path.as_uri(),
            ]
            started_at = time.monotonic()
            return_code = EXPORTER.run_chrome(command, pdf_path, timeout=12)
            elapsed = time.monotonic() - started_at
            self.assertEqual(return_code, 0)
            self.assertTrue(EXPORTER.chrome_output_is_complete(pdf_path))
            self.assertEqual(EXPORTER.page_count(pdf_path), 1)
            self.assertLess(elapsed, 10)






if __name__ == "__main__":
    unittest.main()
