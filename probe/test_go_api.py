"""Checks adapter selection without downloading or compiling a Go module."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent
MODULE = "github.com/substrait-io/substrait-go/v9"
CODEC = "github.com/substrait-io/substrait-go/codec/v9"
PROTO_CODEC = "github.com/substrait-io/substrait-go/encoding/substraitproto"
PSEUDO_VERSION = "v9.0.0-alpha.1.0.20261016221056-c1c73027eea8"

FAKE_GO = r"""#!/usr/bin/env python3
import json
import os
from pathlib import Path
import sys

args = sys.argv[1:]
with open(os.environ["GO_API_LOG"], "a") as log:
    log.write(json.dumps(args) + "\n")
if args[:2] == ["version", "-m"]:
    print(os.environ["GO_API_BUILD_INFO"])
elif args[:3] == ["list", "-m", "-f"]:
    if args[3] == "{{.Dir}}":
        print(os.environ["GO_API_MODULE_DIR"])
    elif args[3] == "{{.Version}}":
        print(os.environ["GO_API_VERSION"])
    elif args[3] == "{{.Origin.Hash}}":
        print("c1c73027eea80000000000000000000000000000")
    else:
        sys.exit(2)
elif args[:2] == ["mod", "edit"]:
    pass
elif args[0] == "get":
    sys.exit(int(os.environ.get("GO_API_GET_STATUS", "0")))
else:
    sys.exit(2)
"""


class GoApiTest(unittest.TestCase):
    def select(self, era, version=PSEUDO_VERSION, get_status=0, codec_module=None):
        with tempfile.TemporaryDirectory() as tmp:
            build = Path(tmp)
            module = build / "core"
            (module / "plan").mkdir(parents=True)
            legacy = "func FromProto(p *proto.Plan, c *extensions.Collection) (*Plan, error) {}"
            (module / "plan" / "plan.go").write_text(
                "package plan\n" + (legacy if era == "legacy" else ""))
            if era == "wire":
                (module / "wire").mkdir()
                (module / "wire" / "plan.go").write_text("package wire\n")
            elif era == "staging":
                (module / "plan" / "plan.go").write_text("package plan\n" + legacy)
                (module / "wire").mkdir()
                (module / "wire" / "doc.go").write_text("package wire\n")
            bindir = build / "bin"
            bindir.mkdir()
            go = bindir / "go"
            go.write_text(FAKE_GO)
            go.chmod(0o755)
            log = build / "commands.jsonl"
            env = dict(os.environ, PATH=str(bindir) + os.pathsep + os.environ["PATH"],
                       GO_API_MODULE_DIR=str(module), GO_API_VERSION=version,
                       GO_API_LOG=str(log), GO_API_GET_STATUS=str(get_status))
            command = ["bash", str(ROOT / "go" / "prepare_api.sh"), MODULE]
            if codec_module is not None:
                command.append(codec_module)
            result = subprocess.run(
                command,
                cwd=build, env=env, capture_output=True, text=True)
            commands = [json.loads(line) for line in log.read_text().splitlines()]
            adapter = (build / "api.go").read_text() if (build / "api.go").exists() else None
            return result, commands, adapter

    def check_adapter(self, era, name):
        result, commands, adapter = self.select(era)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(adapter, (ROOT / "go" / name).read_text())
        self.assertEqual(len(commands), 1)

    def test_legacy_without_wire(self):
        self.check_adapter("legacy", "api_legacy.go")

    def test_staging_wire_package_still_uses_legacy(self):
        self.check_adapter("staging", "api_legacy.go")

    def test_in_tree_wire(self):
        self.check_adapter("wire", "api_wire.go")

    def test_codec_uses_the_core_commit_and_keeps_the_core_pin(self):
        result, commands, adapter = self.select("codec")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(adapter, (ROOT / "go" / "api_codec.go").read_text())
        self.assertIn(["mod", "edit", "-replace=" + MODULE + "=" + MODULE + "@" +
                       PSEUDO_VERSION], commands)
        self.assertIn(["get", CODEC + "@c1c73027eea8"], commands)

    def test_codec_release_resolves_the_core_tag_to_its_commit(self):
        result, commands, adapter = self.select("codec", version="v9.0.0")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(adapter, (ROOT / "go" / "api_codec.go").read_text())
        self.assertIn(["list", "-m", "-f", "{{.Origin.Hash}}", MODULE + "@v9.0.0"], commands)
        self.assertIn(["get", CODEC + "@c1c73027eea80000000000000000000000000000"], commands)
        self.assertIn(["mod", "edit", "-replace=" + MODULE + "=" + MODULE + "@v9.0.0"],
                      commands)

    def test_substraitproto_uses_the_same_commit_as_core(self):
        result, commands, adapter = self.select("codec", codec_module=PROTO_CODEC)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(adapter, (ROOT / "go" / "api_substraitproto.go").read_text())
        self.assertIn(["get", PROTO_CODEC + "@c1c73027eea8"], commands)
        self.assertIn(["mod", "edit", "-replace=" + MODULE + "=" + MODULE + "@" +
                       PSEUDO_VERSION], commands)

    def test_substraitproto_release_resolves_core_tag_to_its_commit(self):
        result, commands, adapter = self.select("codec", version="v9.0.0-alpha.2",
                                               codec_module=PROTO_CODEC)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(adapter, (ROOT / "go" / "api_substraitproto.go").read_text())
        self.assertIn(["get", PROTO_CODEC + "@c1c73027eea80000000000000000000000000000"],
                      commands)

    def test_codec_download_failure_stops_selection(self):
        result, _, adapter = self.select("codec", get_status=23)
        self.assertEqual(result.returncode, 23)
        self.assertIsNone(adapter)


class GoBuildVersionTest(unittest.TestCase):
    def modules(self, info):
        with tempfile.TemporaryDirectory() as tmp:
            build = Path(tmp)
            go = build / "go"
            go.write_text(FAKE_GO)
            go.chmod(0o755)
            env = dict(os.environ, PATH=str(build) + os.pathsep + os.environ["PATH"],
                       GO_API_LOG=str(build / "commands.jsonl"), GO_API_BUILD_INFO=info)
            result = subprocess.run(
                ["bash", "-c", '. "$1"; go_modules_of probe', "bash", str(ROOT / "columns.sh")],
                env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            return dict(line.split() for line in result.stdout.splitlines())

    def test_binary_without_replacements(self):
        self.assertEqual(self.modules("dep " + MODULE + " " + PSEUDO_VERSION),
                         {MODULE: PSEUDO_VERSION})

    def test_replacement_reports_the_code_used_and_leaves_other_modules_alone(self):
        info = ("dep " + MODULE + " v9.0.0\n=> " + MODULE + " " + PSEUDO_VERSION +
                "\ndep " + CODEC + " v9.0.0-20261016221056-c1c73027eea8\n" +
                "dep github.com/substrait-io/substrait-protobuf/go v0.85.0")
        modules = self.modules(info)
        self.assertEqual(modules[MODULE], PSEUDO_VERSION)
        self.assertEqual(modules[CODEC], "v9.0.0-20261016221056-c1c73027eea8")
        self.assertEqual(modules["github.com/substrait-io/substrait-protobuf/go"], "v0.85.0")


if __name__ == "__main__":
    unittest.main()
