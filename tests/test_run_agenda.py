from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "agenda_runner", ROOT / "scripts" / "run_agenda.py"
)
assert SPEC and SPEC.loader
RUNNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNNER)


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


if __name__ == "__main__":
    unittest.main()
