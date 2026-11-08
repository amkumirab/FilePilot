"""Regression and real-filesystem cases beyond the happy-path CLI demo."""

import copy
import errno
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from filepilot.config import DEFAULT_RULES, Rule, load_rules
from filepilot.engine import _move_no_replace, execute, history, load_run, preview_undo, undo
from filepilot.journal import locked
from filepilot.paths import FilePilotError
from filepilot.planner import build_plan


class ExtendedTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def file(self, name="report.pdf", content=b"original"):
        path = self.root / name
        path.write_bytes(content)
        return path

    def test_every_builtin_extension_has_its_expected_category(self):
        for rule in DEFAULT_RULES:
            for extension in rule.extensions:
                self.file(f"sample.{extension.upper()}")
        plan = build_plan(self.root)
        expected = {
            f"sample.{ext.upper()}": f"{rule.target}/sample.{ext.upper()}"
            for rule in DEFAULT_RULES
            for ext in rule.extensions
        }
        self.assertEqual({move.source: move.target for move in plan.moves}, expected)

    def test_numbering_skips_existing_files_and_directories(self):
        self.file()
        directory = self.root / "Documents"
        directory.mkdir()
        (directory / "report.pdf").write_bytes(b"existing")
        (directory / "report (2).pdf").mkdir()
        plan = build_plan(self.root)
        self.assertEqual(plan.moves[0].target, "Documents/report (3).pdf")
        run = execute(plan)
        self.assertEqual(undo(self.root, run["id"])["status"], "undone")
        self.assertEqual((directory / "report.pdf").read_bytes(), b"existing")
        self.assertTrue((directory / "report (2).pdf").is_dir())

    def test_zero_byte_and_large_binary_files_round_trip(self):
        payloads = {"empty.pdf": b"", "large.zip": bytes(range(256)) * 65536 + b"end"}
        for name, contents in payloads.items():
            self.file(name, contents)
        run = execute(build_plan(self.root))
        for entry in run["entries"]:
            self.assertEqual(entry["sha256"], hashlib.sha256(payloads[entry["source"]]).hexdigest())
        self.assertEqual(undo(self.root)["status"], "undone")
        for name, contents in payloads.items():
            self.assertEqual((self.root / name).read_bytes(), contents)

    def test_custom_catchall_handles_extensionless_files_and_spaces(self):
        self.file("README", b"no extension")
        self.file("notes with spaces.txt")
        rules = (Rule("all", (), "My Files/{year}", rename="saved_{name}"),)
        run = execute(build_plan(self.root, rules))
        self.assertEqual(len(run["entries"]), 2)
        self.assertEqual(undo(self.root)["status"], "undone")
        self.assertEqual((self.root / "README").read_bytes(), b"no extension")
        self.assertTrue((self.root / "notes with spaces.txt").exists())

    def test_empty_rule_set_and_unmatched_files_stay_in_place(self):
        source = self.file()
        self.assertFalse(build_plan(self.root, ()).moves)
        self.assertEqual(list(self.root.iterdir()), [source])

    def test_file_occupying_target_directory_blocks_preview_without_changes(self):
        source = self.file()
        blocker = self.file("Documents", b"do not replace")
        with self.assertRaises(FilePilotError):
            build_plan(self.root)
        self.assertEqual(source.read_bytes(), b"original")
        self.assertEqual(blocker.read_bytes(), b"do not replace")
        self.assertFalse((self.root / ".filepilot").exists())

    def test_directory_replacing_organized_file_blocks_undo(self):
        self.file()
        execute(build_plan(self.root))
        target = self.root / "Documents/report.pdf"
        target.unlink()
        target.mkdir()
        result = undo(self.root)
        self.assertEqual(result["status"], "undo_partial")
        self.assertIn("Not a regular file", result["entries"][0]["error"])
        self.assertTrue(target.is_dir())
        self.assertFalse((self.root / "report.pdf").exists())

    def test_native_open_file_behavior_preserves_original_content(self):
        source = self.file()
        plan = build_plan(self.root)
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes

            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.CreateFileW.argtypes = [
                wintypes.LPCWSTR,
                wintypes.DWORD,
                wintypes.DWORD,
                wintypes.LPVOID,
                wintypes.DWORD,
                wintypes.DWORD,
                wintypes.HANDLE,
            ]
            kernel.CreateFileW.restype = wintypes.HANDLE
            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            kernel.CloseHandle.restype = wintypes.BOOL
            handle = kernel.CreateFileW(str(source), 0x80000000, 0, None, 3, 128, None)
            self.assertNotEqual(handle, ctypes.c_void_p(-1).value, ctypes.get_last_error())
            try:
                result = execute(plan)
                self.assertEqual(result["status"], "partial")
                self.assertTrue(source.exists())
            finally:
                self.assertTrue(kernel.CloseHandle(handle))
            # Retry once the application's exclusive file handle has closed.
            result = execute(build_plan(self.root))
        else:
            # POSIX permits renaming an open file; the handle still sees the bytes.
            with source.open("rb") as stream:
                result = execute(plan)
                self.assertEqual(stream.read(), b"original")
        self.assertEqual(result["status"], "completed")
        self.assertEqual(undo(self.root, result["id"])["status"], "undone")
        self.assertEqual(source.read_bytes(), b"original")

    def test_deleted_source_is_reported_without_creating_destination(self):
        source = self.file()
        plan = build_plan(self.root)
        source.unlink()
        run = execute(plan)
        self.assertEqual(run["status"], "partial")
        self.assertFalse((self.root / "Documents/report.pdf").exists())

    def test_existing_state_file_blocks_execution_without_moving_data(self):
        source = self.file()
        self.file(".filepilot", b"occupied")
        with self.assertRaises(OSError):
            execute(build_plan(self.root))
        self.assertEqual(source.read_bytes(), b"original")
        self.assertEqual((self.root / ".filepilot").read_bytes(), b"occupied")

    def test_undo_twice_by_id_is_idempotent(self):
        self.file()
        run = execute(build_plan(self.root))
        self.assertEqual(undo(self.root, run["id"])["status"], "undone")
        self.assertEqual(undo(self.root, run["id"])["status"], "undone")
        self.assertEqual((self.root / "report.pdf").read_bytes(), b"original")
        with self.assertRaises(FilePilotError):
            undo(self.root)

    def test_latest_undo_then_previous_undo_uses_distinct_runs(self):
        self.file("first.pdf", b"one")
        first = execute(build_plan(self.root))
        self.file("second.pdf", b"two")
        second = execute(build_plan(self.root))
        self.assertEqual(undo(self.root)["id"], second["id"])
        self.assertTrue((self.root / "second.pdf").exists())
        self.assertFalse((self.root / "first.pdf").exists())
        self.assertEqual(undo(self.root)["id"], first["id"])
        self.assertEqual(len(history(self.root)), 2)

    def test_missing_organized_file_blocks_undo_and_preview_is_read_only(self):
        self.file()
        run = execute(build_plan(self.root))
        (self.root / "Documents/report.pdf").unlink()
        journal = self.root / ".filepilot/runs" / f"{run['id']}.json"
        before = journal.read_bytes()
        preview = preview_undo(self.root)
        self.assertEqual(preview[0]["status"], "blocked")
        self.assertIn("missing", preview[0]["reason"])
        self.assertEqual(journal.read_bytes(), before)
        self.assertEqual(undo(self.root)["status"], "undo_partial")

    def test_undo_move_failure_is_retryable(self):
        self.file()
        execute(build_plan(self.root))
        with patch("filepilot.engine._move_no_replace", side_effect=PermissionError("locked")):
            run = undo(self.root)
        self.assertEqual(run["status"], "undo_partial")
        self.assertEqual((self.root / "Documents/report.pdf").read_bytes(), b"original")
        self.assertFalse((self.root / "report.pdf").exists())
        self.assertEqual(undo(self.root)["status"], "undone")

    def test_failed_undo_journal_write_never_moves_file(self):
        self.file()
        execute(build_plan(self.root))
        with (
            patch("filepilot.engine.save_run", side_effect=OSError("disk full")),
            self.assertRaises(OSError),
        ):
            undo(self.root)
        self.assertFalse((self.root / "report.pdf").exists())
        self.assertEqual((self.root / "Documents/report.pdf").read_bytes(), b"original")
        self.assertEqual(undo(self.root)["status"], "undone")

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

    def test_posix_unlink_failure_rolls_back_the_new_hard_link(self):
        source = self.file()
        target = self.root / "destination.pdf"
        original_unlink = Path.unlink

        def unlink(path, *args, **kwargs):
            if path == source:
                raise PermissionError("test: source cannot be unlinked")
            return original_unlink(path, *args, **kwargs)

        with (
            patch("filepilot.engine.os.name", "posix"),
            patch.object(Path, "unlink", unlink),
            self.assertRaises(PermissionError),
        ):
            _move_no_replace(source, target)
        self.assertEqual(source.read_bytes(), b"original")
        self.assertFalse(target.exists())

    def test_posix_cross_device_error_preserves_source(self):
        source = self.file()
        target = self.root / "destination.pdf"
        with (
            patch("filepilot.engine.os.name", "posix"),
            patch("filepilot.engine.os.link", side_effect=OSError(errno.EXDEV, "cross-device")),
            self.assertRaises(OSError),
        ):
            _move_no_replace(source, target)
        self.assertEqual(source.read_bytes(), b"original")
        self.assertFalse(target.exists())

    def test_real_process_exit_after_move_is_recoverable(self):
        source = self.file()
        program = """
import os, sys
from pathlib import Path
import filepilot.engine as engine
from filepilot.planner import build_plan
original = engine._move_no_replace
def crash(source, target):
    original(source, target)
    os._exit(23)
engine._move_no_replace = crash
engine.execute(build_plan(Path(sys.argv[1])))
"""
        result = subprocess.run(
            [sys.executable, "-c", program, str(self.root)], capture_output=True, timeout=20
        )
        self.assertEqual(result.returncode, 23, result.stderr)
        self.assertFalse(source.exists())
        self.assertEqual(history(self.root)[0]["entries"][0]["status"], "pending")
        self.assertEqual(undo(self.root)["status"], "undone")
        self.assertEqual(source.read_bytes(), b"original")

    def test_pending_move_before_execution_is_safely_marked_undone(self):
        source = self.file()
        with (
            patch("filepilot.engine._move_no_replace", side_effect=KeyboardInterrupt),
            self.assertRaises(KeyboardInterrupt),
        ):
            execute(build_plan(self.root))
        self.assertEqual(preview_undo(self.root)[0]["status"], "already in place")
        self.assertEqual(undo(self.root)["status"], "undone")
        self.assertEqual(source.read_bytes(), b"original")

    def test_ambiguous_link_interruption_preserves_both_copies(self):
        source = self.file()
        with (
            patch("filepilot.engine._move_no_replace", side_effect=KeyboardInterrupt),
            self.assertRaises(KeyboardInterrupt),
        ):
            execute(build_plan(self.root))
        target = self.root / "Documents/report.pdf"
        os.link(source, target)
        self.assertEqual(undo(self.root)["status"], "undo_partial")
        self.assertEqual(source.read_bytes(), b"original")
        self.assertEqual(target.read_bytes(), b"original")

    def test_lock_is_released_when_the_holding_process_is_terminated(self):
        program = """
import sys, time
from pathlib import Path
from filepilot.journal import locked
with locked(Path(sys.argv[1])):
    print('ready', flush=True)
    time.sleep(30)
"""
        process = subprocess.Popen(
            [sys.executable, "-c", program, str(self.root)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            self.assertEqual(process.stdout.readline().strip(), "ready")
            process.terminate()
            process.communicate(timeout=10)
            with locked(self.root):
                self.assertTrue((self.root / ".filepilot/lock").exists())
        finally:
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=10)

    def test_dense_collision_dataset_round_trips_every_original_byte(self):
        originals = {}
        for number in range(96):
            name = f"document {number:03}.pdf"
            payload = hashlib.sha256(str(number).encode()).digest() * (number + 1)
            self.file(name, payload)
            originals[name] = payload
        directory = self.root / "Documents"
        directory.mkdir()
        for number in range(1, 9):
            name = "same.pdf" if number == 1 else f"same ({number}).pdf"
            (directory / name).write_bytes(b"sentinel")
        rules = (Rule("all", ("pdf",), "Documents", rename="same{ext}"),)
        plan = build_plan(self.root, rules)
        self.assertEqual(len({move.target.casefold() for move in plan.moves}), len(originals))
        run = execute(plan)
        self.assertEqual(run["status"], "completed")
        self.assertEqual(undo(self.root)["status"], "undone")
        for name, payload in originals.items():
            self.assertEqual((self.root / name).read_bytes(), payload)
        self.assertEqual(len(list(directory.iterdir())), 8)
        for sentinel in directory.iterdir():
            self.assertEqual(sentinel.read_bytes(), b"sentinel")


if __name__ == "__main__":
    unittest.main()
