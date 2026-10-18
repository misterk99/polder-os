#!/usr/bin/env python3
"""Public Sluis CLI regressions. Run with POLDER_SLUISD pointing to the built binary."""
import json
import os
from pathlib import Path
import resource
import subprocess
import tempfile
import unittest


class SluisCLI(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="sluis-cli-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.home = self.root / "home"
        self.origin = self.home / "project"
        self.origin.mkdir(parents=True)
        runtime = self.root / "runtime"
        runtime.mkdir(mode=0o700)
        self.data = self.root / "data"
        self.binary = os.environ["POLDER_SLUISD"]
        self.env = dict(os.environ, HOME=str(self.home), XDG_RUNTIME_DIR=str(runtime),
                        POLDER_SLUIS_DIR=str(self.data), POLDER_LANG="en")
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))

    def cli(self, *args, extra=None, success=True):
        p = subprocess.run([self.binary, *map(str, args)], env=dict(self.env, **(extra or {})),
                           capture_output=True, text=True)
        if success:
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        else:
            self.assertNotEqual(p.returncode, 0, p.stdout + p.stderr)
        return json.loads(p.stdout) if p.stdout.strip() else None

    def create(self):
        (self.origin / "f").write_text("BASE!!\n")
        self.id = self.cli("create", "CLI test", self.origin)["meta"]["id"]
        self.upper = self.data / "polders" / self.id / "upper"
        (self.upper / "f").write_text("BRANCH\n")

    def test_reviewed_plan_accepts_unchanged_files_and_supports_rollback(self):
        self.create()
        preview = self.cli("plan", self.id, "f")
        report = self.cli("merge", self.id, "--review-token", preview["review_token"], "f")["report"]
        self.assertEqual(report["done"], ["f"])
        self.assertEqual((self.origin / "f").read_text(), "BRANCH\n")
        result = self.cli("rollback", self.id, report["merge_id"])
        self.assertTrue(result["report"]["rolled_back"])
        self.assertEqual((self.origin / "f").read_text(), "BASE!!\n")

    def test_preview_rejects_changes_to_either_version(self):
        self.create()
        for changed in (self.origin / "f", self.upper / "f"):
            preview = self.cli("plan", self.id, "--force", "f")
            changed.write_text("CHANGED after preview\n")
            expected = (self.origin / "f").read_text()
            result = self.cli("merge", self.id, "--review-token", preview["review_token"], "--force", "f", success=False)
            self.assertIn("preview", result["error"])
            self.assertEqual((self.origin / "f").read_text(), expected)
            self.assertIsNone(self.cli("pending", self.id)["pending"])

    def test_recovery_keeps_later_mainland_edit_as_a_conflict(self):
        self.create()
        self.cli("merge", self.id, "f", extra={"POLDER_SLUIS_CRASH": "applied"}, success=False)
        (self.origin / "f").write_text("OTHER!\n")  # same size: exercises the stat/hash cache too
        self.cli("resume", self.id)
        (self.upper / "f").write_text("NEXT!!\n")
        changes = self.cli("changes", self.id)["changes"]
        self.assertTrue(next(c for c in changes if c["path"] == "f")["conflict"])
        result = self.cli("merge", self.id, "f")["report"]
        self.assertFalse(result["done"])
        self.assertEqual((self.origin / "f").read_text(), "OTHER!\n")

    def test_child_flags_are_passed_through_without_changing_sandbox_options(self):
        self.create()
        stubs = self.root / "stubs"
        stubs.mkdir()
        runner = stubs / "bwrap"
        runner.write_text("#!/usr/bin/python3\nimport sys,json\nprint(json.dumps(sys.argv[1:]))\n")
        runner.chmod(0o755)
        argv = self.cli("run", self.id, "--", "printf", "%s", "--net", "--terminal",
                        extra={"PATH": str(stubs) + ":" + self.env["PATH"]})
        split = argv.index("--")
        self.assertNotIn("--share-net", argv[:split])
        self.assertEqual(argv[split + 1:], ["printf", "%s", "--net", "--terminal"])
        self.assertFalse(self.cli("info", self.id)["meta"]["network"])

    def test_conflicted_rename_preserves_both_mainland_files(self):
        self.create()
        # Produce real OverlayFS rename whiteouts, as the desktop runner does.
        (self.upper / "f").unlink()
        self.cli("run", self.id, "--", "sh", "-ec", "mv f destination")
        (self.origin / "destination").write_text("external destination\n")
        report = self.cli("merge", self.id, "destination")["report"]
        self.assertFalse(report["done"])
        self.assertEqual((self.origin / "f").read_text(), "BASE!!\n")
        self.assertEqual((self.origin / "destination").read_text(), "external destination\n")


if __name__ == "__main__":
    unittest.main()
