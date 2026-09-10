#!/bin/bash
# Generate the protobuf bindings the tests import, into tests/relations/.bindings/.
#
# Upstream this script does not exist: `pixi run generate-protobuf` already writes
# `gen/proto/python` and `pyproject.toml` puts it on pytest's path. Here nothing
# generates Python bindings, and the repository's own self-check is contracted to
# need python3 and nothing else, so this stays opt-in and its output stays ignored.
#
#     bash tests/relations/bootstrap.sh && python3 -m pytest tests/relations
#
# Needs protoc and a python3 with protobuf and pyyaml.
set -euo pipefail
cd "$(dirname "$0")"

OUT=.bindings
P="$(python3 -c 'import lib.paths as p; print(p.proto_dir())')"
rm -rf "$OUT"
mkdir -p "$OUT"
protoc -I "$P" -I ../../proto --python_out="$OUT" \
  "$P"/substrait/*.proto "$P"/substrait/extensions/*.proto \
  ../../proto/substrait/test/relation_test.proto
# protoc writes no package markers, and substrait/ has to be a package for the
# nested substrait.test to be importable alongside it
find "$OUT" -type d -exec touch {}/__init__.py \;
python3 -c "
import sys; sys.path.insert(0, '$OUT')
import substrait.plan_pb2, substrait.test.relation_test_pb2 as rt
print('bindings ok:', rt.RelationTestCase.DESCRIPTOR.full_name)
"
