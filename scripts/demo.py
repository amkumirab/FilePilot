"""Run an isolated preview -> organize -> undo demonstration."""

import json
import subprocess
import sys
import tempfile
from pathlib import Path


def main() -> None:
    demo_root = Path(__file__).resolve().parents[1] / ".demo"
    demo_root.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="inbox-", dir=demo_root) as directory:
        root = Path(directory)
        originals = {
            "invoice.pdf": b"demo invoice",
            "photo.png": b"demo picture",
            "sales.csv": b"month,total\n11,120\n",
            "notes.xyz": b"leave here",
        }
        for name, content in originals.items():
            (root / name).write_bytes(content)
        documents = root / "Documents"
        documents.mkdir()
        (documents / "invoice.pdf").write_bytes(b"existing file stays untouched")

        def run(*args: str) -> str:
            print(f"\n$ filepilot {' '.join(args)} <demo-folder>", flush=True)
            result = subprocess.run(
                [sys.executable, "-m", "filepilot", args[0], str(root), *args[1:]],
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=True,
            )
            print(result.stdout, end="", flush=True)
            return result.stdout

        run("scan")
        assert not (root / ".filepilot").exists(), "Preview unexpectedly created state"
        organized = json.loads(run("organize", "--apply", "--json"))
        assert organized["status"] == "completed"
        assert (documents / "invoice (2).pdf").read_bytes() == originals["invoice.pdf"]
        run("history")
        run("undo")
        run("undo", "--apply")
        for name, content in originals.items():
            assert (root / name).read_bytes() == content, f"Round trip failed: {name}"
        assert (documents / "invoice.pdf").read_bytes() == b"existing file stays untouched"
        print("\nDemo passed: original bytes restored; existing file preserved.")
    print("Temporary sample files cleaned up.")


if __name__ == "__main__":
    main()
