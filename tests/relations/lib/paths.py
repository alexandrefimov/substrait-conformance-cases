"""Where the pieces are, resolved the same way in either repository.

This directory is laid out as it would sit in substrait-io/substrait, so the code must
not care which repository it is running in. Three things differ, and all three are
resolved here rather than sprinkled through the modules:

  extensions   upstream the specification's own `extensions/` at the repository root;
               here a vendored copy of the same files at the release the cases target
  protos       upstream `proto/substrait/*.proto`; here a vendored copy of the same
  bindings     upstream `gen/proto/python`, produced by `pixi run generate-protobuf`
               and already on pytest's path; here `.bindings/`, written by bootstrap.sh

Deleting `vendor/` and pointing nothing at `.bindings/` is what porting this directory
upstream amounts to; every fallback below then resolves to the repository's own copy.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RELATIONS = os.path.dirname(HERE)
REPO = os.path.dirname(os.path.dirname(RELATIONS))

# The release the checked-in cases were authored against. A case pins the text it
# tests through its own spec_ref; this pins the extension definitions the derived
# schemas were computed from, which is the other half of the same claim.
TARGET_RELEASE = "0.102.0"


def _own(path, marker):
    full = os.path.join(REPO, path)
    return full if os.path.exists(os.path.join(full, marker)) else None


def extensions_dir():
    return _own("extensions", "functions_arithmetic_decimal.yaml") or os.path.join(
        RELATIONS, "vendor", "extensions"
    )


def proto_dir():
    return _own("proto", os.path.join("substrait", "algebra.proto")) or os.path.join(
        RELATIONS, "vendor", "proto"
    )


def cases_dir():
    return os.path.join(RELATIONS, "cases")


def bundles_dir():
    return os.path.join(RELATIONS, "bundles")


def baseline_path():
    return os.path.join(RELATIONS, "coverage.json")


# Importing this module is what puts the locally generated bindings within reach, so
# every other module in the package imports it before it imports anything protobuf.
_LOCAL_BINDINGS = os.path.join(RELATIONS, ".bindings")
if os.path.isdir(_LOCAL_BINDINGS) and _LOCAL_BINDINGS not in sys.path:
    sys.path.insert(0, _LOCAL_BINDINGS)


def bindings_available():
    """Are the protobuf bindings importable? The tests skip rather than fail if not.

    Upstream they always are: `pixi run generate-protobuf` writes them and
    `pyproject.toml` puts `gen/proto/python` on pytest's path. Here they have to be
    generated deliberately, and a repository whose own self-check needs nothing but
    python3 should not start failing because of that.
    """
    try:
        import substrait.plan_pb2  # noqa: F401
        import substrait.test.relation_test_pb2  # noqa: F401

        return True
    except Exception:
        return False
