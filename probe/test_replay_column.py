"""Checks DuckDB extension preflight without installing a package or extension."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


class DuckDBExtensionPreflightTest(unittest.TestCase):
    def replay(self, mode, latest):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            probe = root / "probe"
            probe.mkdir()
            source = Path(__file__).resolve().parent
            for name in ("replay_column.sh", "columns.sh", "normalize.py", "column_diff.py"):
                shutil.copyfile(source / name, probe / name)
            (probe / "versions.env").write_text(
                "DUCKDB_VERSION=1.5.6\nDUCKDB_SUBSTRAIT_EXTENSION=fixture-extension\n")
            (probe / "versions-latest.env").write_text(
                '. "$(dirname "${BASH_SOURCE[0]}")/versions.env"\n'
                "DUCKDB_VERSION=latest\nDUCKDB_SUBSTRAIT_EXTENSION=latest\n")
            fake = root / "python"
            fake.write_text('''#!/usr/bin/env python3
import os
import sys
if sys.argv[1] == "-c":
    print("1.5.6")
elif os.environ["EXTENSION_TEST_MODE"] == "unavailable":
    print("HTTP Error: fixture community extension unavailable (HTTP 404)", file=sys.stderr)
    sys.exit(23)
else:
    print("another-extension" if os.environ["EXTENSION_TEST_MODE"] == "moved"
          else "fixture-extension")
''')
            fake.chmod(0o755)
            (probe / "setup.sh").write_text(
                'mkdir -p "$1/venv/bin"\n'
                'cp "$EXTENSION_TEST_PYTHON" "$1/venv/bin/python"\n')
            marker = root / "runner-was-called"
            (probe / "duckdb_all.sh").write_text(
                'printf reached > "$EXTENSION_TEST_MARKER"\n'
                'echo "fixture runner failure" >&2\nexit 23\n')
            (root / "derived-schema").mkdir()
            (root / "derived-schema" / "fixture.json").write_text("{}\n")
            (root / "expected.json").write_text("{}\n")
            (root / "results").mkdir()
            (root / "results" / "DUCKDB.txt").write_text("saved measurement\n")
            out = root / "out"
            env = dict(os.environ, LATEST=str(latest), OUT=str(out),
                       SUBSTRAIT_VERSIONS=str(probe / "versions.env"),
                       EXTENSION_TEST_MODE=mode, EXTENSION_TEST_PYTHON=str(fake),
                       EXTENSION_TEST_MARKER=str(marker))
            result = subprocess.run(["bash", str(probe / "replay_column.sh"), "DUCKDB"],
                                    cwd=root, env=env, capture_output=True, text=True)
            return result, marker.exists(), out.exists()

    def test_unavailable_extension_stops_before_cases_in_both_modes(self):
        for latest in (0, 1):
            with self.subTest(latest=latest):
                result, reached, artifacts = self.replay("unavailable", latest)
                self.assertEqual(result.returncode, 1)
                self.assertIn("FAILED: DuckDB substrait extension setup failed", result.stderr)
                self.assertIn("HTTP 404", result.stderr)
                self.assertFalse(reached)
                self.assertFalse(artifacts)

    def test_loaded_extension_reaches_runner_in_both_modes(self):
        for latest in (0, 1):
            with self.subTest(latest=latest):
                result, reached, _ = self.replay("ready", latest)
                self.assertTrue(reached, result.stdout + result.stderr)
                self.assertIn("runner returned 23", result.stderr)
                self.assertNotIn("extension setup failed", result.stderr)

    def test_another_extension_cannot_reproduce_a_pinned_measurement(self):
        result, reached, artifacts = self.replay("moved", 0)
        self.assertEqual(result.returncode, 1)
        self.assertIn("community extension is another-extension", result.stderr)
        self.assertFalse(reached)
        self.assertFalse(artifacts)


if __name__ == "__main__":
    unittest.main()
