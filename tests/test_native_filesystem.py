"""Native file handles, POSIX move semantics, and process locks."""

import errno
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from filepilot.engine import _move_no_replace, execute, undo
from filepilot.journal import locked
from filepilot.planner import build_plan


class NativeFilesystemTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def file(self, name="report.pdf", content=b"original"):
        path = self.root / name
        path.write_bytes(content)
        return path

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


if __name__ == "__main__":
    unittest.main()
