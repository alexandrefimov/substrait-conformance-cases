import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


class SingleColumnRetakeTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        source = Path(__file__).resolve().parent
        for name in ("probe", "results", "docs"):
            (self.root / name).mkdir()
        for name in ("reverify.sh", "versions.env", "columns.sh"):
            shutil.copyfile(source / name, self.root / "probe" / name)
        (self.root / "probe" / "replay_column.sh").write_text(
            'if [ "$REPLAY_RESULT" = failed ]; then exit 1; fi\n'
            'printf "%s: replayed 2026-01-01T00:00, fixture\\n" "$1" > "$OUT/$1.txt"\n'
            'if [ "$REPLAY_RESULT" != partial ]; then\n'
            '  printf "{}\\n" > "$OUT/$1.json"\n'
            'fi\n'
            'if [ "$REPLAY_RESULT" = error ]; then exit 2; fi\n'
            'exit 1\n'
        )
        (self.root / "probe" / "check_expected.py").write_text(
            'import os\n'
            'if os.environ["REPLAY_RESULT"] == "unparsed": print("unparsed answer")\n'
            'answered = 0 if os.environ["REPLAY_RESULT"] == "unanswered" else 1\n'
            'print("matched: %d, differed: 0" % answered)\n'
        )
        for name in ("matrix.py", "diffs.py", "heatmap.py"):
            (self.root / "probe" / name).write_text('print("new summary")\n')
        for name in ("PYTHON.txt", "GO.txt", "MATRIX.txt", "DIFFS.md"):
            (self.root / "results" / name).write_text("old measurement\n")

    def run_retake(self, result="moved", update="1", latest="0", column="PYTHON"):
        env = dict(os.environ, REPLAY_RESULT=result, LATEST=latest)
        env.pop("UPDATE_COLUMNS", None)
        if update is not None:
            env["UPDATE_COLUMNS"] = update
        return subprocess.run(
            ["bash", str(self.root / "probe" / "reverify.sh"), column],
            cwd=self.root, env=env, capture_output=True, text=True,
        )

    def test_changed_column_is_saved_without_other_participants(self):
        result = self.run_retake()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((self.root / "results" / "PYTHON.txt").read_text(),
                         "PYTHON: column from run 2026-01-01T00:00, fixture\n")
        self.assertEqual((self.root / "results" / "GO.txt").read_text(), "old measurement\n")
        self.assertEqual((self.root / "results" / "MATRIX.txt").read_text(), "new summary\n")
        self.assertEqual((self.root / "docs" / "index.html").read_text(), "new summary\n")

    def test_failed_or_partial_replay_cannot_replace_saved_measurements(self):
        for mode in ("failed", "partial", "error", "unanswered", "unparsed"):
            with self.subTest(mode=mode):
                result = self.run_retake(result=mode)
                self.assertNotEqual(result.returncode, 0)
                for name in ("PYTHON.txt", "GO.txt", "MATRIX.txt", "DIFFS.md"):
                    self.assertEqual((self.root / "results" / name).read_text(),
                                     "old measurement\n")

    def test_retake_requires_an_explicit_pinned_update_and_known_column(self):
        for options in ({"update": None}, {"latest": "1"}, {"column": "UNKNOWN"}):
            with self.subTest(options=options):
                self.assertNotEqual(self.run_retake(**options).returncode, 0)
                self.assertEqual((self.root / "results" / "PYTHON.txt").read_text(),
                                 "old measurement\n")


if __name__ == "__main__":
    unittest.main()
