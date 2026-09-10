"""Anchor canonicalisation and the fingerprint two encodings are compared by.

Extension anchors are arbitrary: two documents may describe the same program with
different anchor numbers. Canonicalisation renumbers them by first use so a comparison
is about the program. Function and type anchors are separate numbering spaces and are
mapped separately; sharing one map let a type declaration overwrite a function's rewrite
entry, which made two different plans compare equal.
"""

import hashlib

from google.protobuf import descriptor as _d

from . import paths  # noqa: F401  (puts the bindings on sys.path)
from substrait.plan_pb2 import Plan


def _walk(msg, fn):
    fn(msg)
    for f, v in msg.ListFields():
        if f.type == _d.FieldDescriptor.TYPE_MESSAGE:
            for item in v if f.is_repeated else [v]:
                _walk(item, fn)


def canonical(plan):
    """Renumber extension anchors by first use so two encodings are comparable.

    Function and type anchors live in separate numbering spaces and are mapped
    separately: sharing one map let a type declaration overwrite a function's rewrite
    entry, which made two different plans compare equal.
    """
    p = Plan()
    p.CopyFrom(plan)
    order = []

    def collect(m):
        for f, v in m.ListFields():
            if (
                f.name
                in ("function_reference", "type_reference", "type_variation_reference")
                and v not in order
            ):
                order.append(v)

    for rel in p.relations:
        _walk(rel, collect)

    decls = list(p.extensions)

    def key(d):
        inner = getattr(d, d.WhichOneof("mapping_type"))
        anchor = getattr(inner, "function_anchor", None) or getattr(
            inner, "type_anchor", 0
        )
        return (
            order.index(anchor) if anchor in order else len(order),
            d.WhichOneof("mapping_type"),
            inner.name,
        )

    decls.sort(key=key)

    fn_map, type_map, urn_map = {}, {}, {}
    new_decls, new_urns = [], []
    for i, d in enumerate(decls, start=1):
        inner = getattr(d, d.WhichOneof("mapping_type"))
        if hasattr(inner, "function_anchor"):
            fn_map[inner.function_anchor] = i
        elif hasattr(inner, "type_anchor"):
            type_map[inner.type_anchor] = i
        old_urn = inner.extension_urn_reference
        if old_urn not in urn_map:
            urn_map[old_urn] = len(urn_map) + 1
        nd = type(d)()
        nd.CopyFrom(d)
        ninner = getattr(nd, nd.WhichOneof("mapping_type"))
        if hasattr(ninner, "function_anchor"):
            ninner.function_anchor = i
        ninner.extension_urn_reference = urn_map[old_urn]
        new_decls.append(nd)
    for u in sorted(
        p.extension_urns, key=lambda u: urn_map.get(u.extension_urn_anchor, 99)
    ):
        if u.extension_urn_anchor in urn_map:
            nu = type(u)()
            nu.CopyFrom(u)
            nu.extension_urn_anchor = urn_map[u.extension_urn_anchor]
            new_urns.append(nu)

    def rewrite(m):
        for f, v in m.ListFields():
            if f.name == "function_reference" and v in fn_map:
                setattr(m, f.name, fn_map[v])
            elif f.name == "type_reference" and v in type_map:
                setattr(m, f.name, type_map[v])

    for rel in p.relations:
        _walk(rel, rewrite)

    del p.extensions[:]
    p.extensions.extend(new_decls)
    del p.extension_urns[:]
    p.extension_urns.extend(new_urns)
    return p


def fingerprint(plan):
    return hashlib.sha256(
        canonical(plan).SerializeToString(deterministic=True)
    ).hexdigest()[:16]
