"""Compare join/grouping nullability with explicit Substrait expectations.

Run with a substrait-python environment; PYTHONPATH may select a source checkout.
This uses only named reads and field references, with no function return oracle.
"""

import argparse
import importlib.metadata
import json
from pathlib import Path

from google.protobuf.json_format import MessageToJson
from substrait import algebra_pb2 as alg
from substrait import plan_pb2 as plan_pb
from substrait import type_pb2 as typ
from substrait.type_inference import infer_rel_schema

R = typ.Type.NULLABILITY_REQUIRED
N = typ.Type.NULLABILITY_NULLABLE


def read(name, nullabilities):
    return alg.Rel(read=alg.ReadRel(
        named_table=alg.ReadRel.NamedTable(names=[name]),
        base_schema=typ.NamedStruct(
            names=[f"{name}{i}" for i in range(len(nullabilities))],
            struct=typ.Type.Struct(
                types=[typ.Type(i64=typ.Type.I64(nullability=n)) for n in nullabilities],
                nullability=R,
            ),
        ),
    ))


def field(index):
    return alg.Expression(selection=alg.Expression.FieldReference(
        root_reference=alg.Expression.FieldReference.RootReference(),
        direct_reference=alg.Expression.ReferenceSegment(
            struct_field=alg.Expression.ReferenceSegment.StructField(field=index)
        ),
    ))


def joins():
    # Each pair says which side can receive null padding, as specified for JoinRel.
    kinds = {
        "INNER": (False, False), "LEFT": (False, True),
        "RIGHT": (True, False), "OUTER": (True, True),
        "LEFT_SINGLE": (False, True), "RIGHT_SINGLE": (True, False),
    }
    for kind, (widen_left, widen_right) in kinds.items():
        for left_n, right_n in ((R, R), (R, N), (N, R), (N, N)):
            left, right = read("l", [left_n]), read("r", [right_n])
            rel = alg.Rel(join=alg.JoinRel(
                left=left, right=right,
                type=alg.JoinRel.JoinType.Value("JOIN_TYPE_" + kind),
                expression=alg.Expression(literal=alg.Expression.Literal(boolean=True)),
            ))
            expected = [N if widen_left else left_n, N if widen_right else right_n]
            yield f"join_{kind.lower()}_{left_n}_{right_n}", rel, expected


def groupings():
    cases = [
        ("one_set", [[0, 1]], [R, R]),
        ("disjoint", [[0], [1]], [N, N, R]),
        ("shared_key", [[0, 1], [0]], [R, N, R]),
        ("grand_total", [[0, 1], []], [N, N, R]),
        ("reversed_sets", [[1], [0]], [N, N, R]),
    ]
    for name, refs, expected in cases:
        rel = alg.Rel(aggregate=alg.AggregateRel(
            input=read("t", [R, R]),
            grouping_expressions=[field(0), field(1)],
            groupings=[alg.AggregateRel.Grouping(expression_references=r) for r in refs],
        ))
        yield "grouping_" + name, rel, expected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--area", choices=["join", "grouping", "all"], default="all")
    parser.add_argument("--write-plans", type=Path)
    args = parser.parse_args()
    print(json.dumps({"packages": {
        p: importlib.metadata.version(p)
        for p in ("substrait", "substrait-protobuf", "protobuf")
    }}))
    if args.write_plans:
        args.write_plans.mkdir(parents=True, exist_ok=True)
    cases = []
    if args.area in ("join", "all"):
        cases.extend(joins())
    if args.area in ("grouping", "all"):
        cases.extend(groupings())
    mismatches = 0
    for name, rel, expected in cases:
        before = rel.SerializeToString()
        schema = infer_rel_schema(rel)
        actual = [getattr(t, t.WhichOneof("kind")).nullability for t in schema.types]
        if rel.SerializeToString() != before:
            raise RuntimeError(f"inference mutated input: {name}")
        matches = actual == expected
        mismatches += not matches
        print(json.dumps({"case": name, "expected": expected, "actual": actual,
                          "matches": matches}))
        if args.write_plans:
            plan = plan_pb.Plan(
                version=plan_pb.Version(major_number=0, minor_number=99, patch_number=0),
                relations=[plan_pb.PlanRel(root=alg.RelRoot(
                    input=rel, names=[f"c{i}" for i in range(len(expected))]
                ))],
            )
            (args.write_plans / f"{name}.json").write_text(MessageToJson(plan) + "\n")
    print(json.dumps({"cases": len(cases), "mismatches": mismatches,
                      "nullability": {"required": R, "nullable": N}}))


if __name__ == "__main__":
    main()
