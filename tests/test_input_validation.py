"""Invalid configuration and journal data are rejected safely."""

import copy
import json
import tempfile
import unittest
from pathlib import Path

from filepilot.config import load_rules
from filepilot.engine import execute, load_run
from filepilot.paths import FilePilotError
from filepilot.planner import build_plan


class InputValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def file(self, name="report.pdf", content=b"original"):
        path = self.root / name
        path.write_bytes(content)
        return path

    def test_invalid_journal_shapes_are_rejected_without_modifying_files(self):
        self.file()
        run = execute(build_plan(self.root))
        path = self.root / ".filepilot/runs" / f"{run['id']}.json"
        variants = [
            None,
            [],
            {},
            {**run, "entries": None},
            {**run, "status": {}},
            {**run, "root": str(self.root.parent)},
        ]
        for field, value in (
            ("status", []),
            ("source", "../outside.pdf"),
            ("target", ".filepilot/lock"),
            ("sha256", None),
            ("sha256", "invalid"),
        ):
            altered = copy.deepcopy(run)
            altered["entries"][0][field] = value
            variants.append(altered)
        duplicate = copy.deepcopy(run)
        duplicate["entries"].append(copy.deepcopy(duplicate["entries"][0]))
        variants.append(duplicate)
        for document in variants:
            path.write_text(json.dumps(document), encoding="utf-8")
            with self.subTest(document=document), self.assertRaises(FilePilotError):
                load_run(self.root, run["id"])
        self.assertEqual((self.root / "Documents/report.pdf").read_bytes(), b"original")

    def test_malformed_json_and_non_utf8_journals_are_readable_errors(self):
        self.file()
        run = execute(build_plan(self.root))
        path = self.root / ".filepilot/runs" / f"{run['id']}.json"
        for contents in (b"{broken", b"\xff\xfe"):
            path.write_bytes(contents)
            with self.subTest(contents=contents), self.assertRaises(FilePilotError):
                load_run(self.root, run["id"])

    def test_invalid_config_values_are_rejected(self):
        path = self.root / "rules.toml"
        contents = [
            "rules = []",
            'rules = "wrong"',
            "[[rules]]\nname=42\ntarget='Docs'",
            "[[rules]]\nname='a'\ntarget=42",
            "[[rules]]\nname='a'\ntarget='Docs'\ncontains=42",
            "[[rules]]\nname='a'\ntarget='Docs'\nextensions='pdf'",
            "[[rules]]\nname='a'\ntarget='Docs'\nextensions=[1]",
            "[[rules]]\nname='a'\ntarget='Docs'\nrename='nested/{name}'",
            "[[rules]]\nname='a'\ntarget='Docs'\nrename='{name'",
            "[[rules]]\nname='a'",
        ]
        for text in contents:
            path.write_text(text, encoding="utf-8")
            with self.subTest(text=text), self.assertRaises(FilePilotError):
                load_rules(path)


if __name__ == "__main__":
    unittest.main()
