"""Structural rules a plan must satisfy, checked without resolving any extension.

These are the violations a case may claim under `KIND_INVALID_PLAN` besides a declared
`output_type` that disagrees with its extension. Each one is a rule the specification
states and a consumer can check with nothing but the plan in front of it.

What is deliberately absent: anything that needs the extension files, which is
`check_decl`'s job, and anything the specification leaves open. A rule that cannot be
pointed at is not a violation, it is an opinion.
"""

from . import deriver


def _field_indices(msg, out):
    """Every struct-field index reached from a root reference, at the top level."""
    for f, v in msg.ListFields():
        for item in v if f.is_repeated else [v]:
            if not hasattr(item, "ListFields"):
                continue
            full = f.message_type.full_name if f.message_type else ""
            if full == "substrait.Expression.FieldReference" and item.HasField(
                "root_reference"
            ):
                seg = item.direct_reference
                if seg.HasField("struct_field"):
                    out.append(seg.struct_field.field)
            if full == "substrait.Rel":
                continue  # a nested relation has its own input, walked separately
            _field_indices(item, out)
    return out


def violations(plan, ext_dir):
    """Every structural rule this plan breaks, as sentences."""
    found = []
    d = deriver.Deriver(_as_dict(plan), ext_dir)

    def walk(rel_dict):
        ((kind, node),) = rel_dict.items()
        for key in ("input", "left", "right"):
            if key in node:
                walk(node[key])
        for i in node.get("inputs", []):
            walk(i)

        if kind == "set":
            widths = {len(d.rel(i)) for i in node.get("inputs", [])}
            if len(widths) > 1:
                found.append(
                    f"set inputs have {sorted(widths)} columns; Set Operation requires "
                    "identical field types across inputs, so identical arity"
                )
        if kind == "project":
            width = len(d.rel(node["input"]))
            for e in node.get("expressions", []):
                for i in _refs(e):
                    if i >= width:
                        found.append(
                            f"project expression references field {i} of an input with "
                            f"{width} columns"
                        )
        if "common" in node and "emit" in node.get("common", {}):
            direct = len(getattr(d, "rel_" + kind)(node))
            for i in node["common"]["emit"].get("outputMapping", []):
                if i >= direct:
                    found.append(
                        f"{kind} emit maps output {i} of a relation with {direct} "
                        "direct output columns"
                    )
        return found

    for pr in _as_dict(plan).get("relations", []):
        walk(pr["root"]["input"] if "root" in pr else pr["rel"])
    return found


def _refs(expr):
    """Top-level struct-field indices a proto-JSON expression reads from its input."""
    out = []
    if isinstance(expr, dict):
        sel = expr.get("selection")
        if isinstance(sel, dict) and "rootReference" in sel:
            sf = sel.get("directReference", {}).get("structField")
            if isinstance(sf, dict):
                out.append(sf.get("field", 0))
        for v in expr.values():
            out += _refs(v)
    elif isinstance(expr, list):
        for v in expr:
            out += _refs(v)
    return out


def _as_dict(plan):
    from google.protobuf import json_format

    return plan if isinstance(plan, dict) else json_format.MessageToDict(plan)
