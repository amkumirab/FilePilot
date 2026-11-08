import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from filepilot.config import Rule, load_rules
from filepilot.paths import FilePilotError
from filepilot.planner import build_plan


class PlannerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_preview_is_read_only_and_matches_extensions_case_insensitively(self):
        (self.root / "report.PDF").write_bytes(b"hello")
        (self.root / "unknown.xyz").write_bytes(b"keep")
        before = sorted(self.root.rglob("*"))
        plan = build_plan(self.root)
        self.assertEqual(plan.moves[0].target, "Documents/report.PDF")
        self.assertEqual(sorted(self.root.rglob("*")), before)
        self.assertEqual(len(plan.skipped), 1)

    def test_collision_suffix_accounts_for_disk_and_planned_names(self):
        (self.root / "a.pdf").write_bytes(b"a")
        (self.root / "b.pdf").write_bytes(b"b")
        (self.root / "Docs").mkdir()
        (self.root / "Docs" / "same.pdf").write_bytes(b"existing")
        rules = (Rule("docs", ("pdf",), "Docs", rename="same{ext}"),)
        plan = build_plan(self.root, rules)
        self.assertEqual([m.target for m in plan.moves], ["Docs/same (2).pdf", "Docs/same (3).pdf"])

    def test_first_match_uses_modification_date_and_optional_rename(self):
        source = self.root / "invoice.pdf"
        source.write_bytes(b"invoice")
        # Midday UTC avoids local date changes in the example's month/year.
        os.utime(source, (1715774400, 1715774400))
        rules = (
            Rule(
                "invoices",
                (".PDF",),
                "Bills/{year}/{month}",
                contains="invoice",
                rename="{year}-{month}-{stem}{ext}",
            ),
            Rule("all", (), "Other"),
        )
        self.assertEqual(
            build_plan(self.root, rules).moves[0].target, "Bills/2024/05/2024-05-invoice.pdf"
        )

    def test_ignores_hidden_incomplete_and_nested_files(self):
        for name in (".private.pdf", "download.pdf.crdownload", "download.pdf.part"):
            (self.root / name).write_bytes(b"keep")
        (self.root / "nested").mkdir()
        (self.root / "nested" / "a.pdf").write_bytes(b"keep")
        self.assertFalse(build_plan(self.root).moves)

    def test_rejects_traversal_and_reserved_state_directory(self):
        (self.root / "a.pdf").write_bytes(b"a")
        for target in ("../outside", "/tmp/outside", "C:\\outside", ".filepilot/data"):
            with self.subTest(target=target), self.assertRaises(FilePilotError):
                build_plan(self.root, (Rule("bad", (), target),))

    def test_config_rejects_unknown_keys_and_invalid_templates(self):
        config = self.root / "rules.toml"
        for contents in (
            '[[rules]]\nname="x"\ntarget="Docs"\nextensons=["pdf"]',
            '[[rules]]\nname="x"\ntarget="{missing}"',
        ):
            config.write_text(contents, encoding="utf-8")
            with self.subTest(contents=contents), self.assertRaises(FilePilotError):
                load_rules(config)

    def test_loads_ordered_toml_rules(self):
        config = self.root / "rules.toml"
        config.write_text(
            '[[rules]]\nname="PDF"\nextensions=["pdf"]\ntarget="Docs"\ncontains="bill"\n',
            encoding="utf-8",
        )
        self.assertEqual(load_rules(config)[0].contains, "bill")

    def test_unrepresentable_modification_dates_have_readable_errors(self):
        source = self.root / "report.pdf"
        source.write_bytes(b"original")
        for error in (OverflowError("timestamp overflow"), ValueError("year out of range")):
            with (
                self.subTest(error=error),
                patch("filepilot.planner.datetime") as date,
                self.assertRaises(FilePilotError),
            ):
                date.fromtimestamp.side_effect = error
                build_plan(self.root)
        self.assertEqual(source.read_bytes(), b"original")
        self.assertFalse((self.root / ".filepilot").exists())


if __name__ == "__main__":
    unittest.main()
