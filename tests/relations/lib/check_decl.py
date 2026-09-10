"""Walk every declared outputType in a plan and compare it with what the deriver derives."""

import json
import os
import sys
from . import deriver as D


def check(plan, ext_dir):
    d = D.Deriver(plan, ext_dir)
    findings = []

    def walk_rel(r):
        ((kind, node),) = r.items()
        # inputs first
        for key in ("input", "left", "right"):
            if key in node:
                walk_rel(node[key])
        for i in node.get("inputs", []):
            walk_rel(i)
        # the input schema this relation's expressions see
        if kind in ("join", "hashJoin", "mergeJoin", "nestedLoopJoin"):
            inp = d.rel(node["left"]) + d.rel(node["right"])
        elif "input" in node:
            inp = d.rel(node["input"])
        else:
            inp = []

        def walk_expr(e):
            if isinstance(e, dict):
                if "scalarFunction" in e:
                    f = e["scalarFunction"]
                    args = [
                        d.expr_type(a["value"], inp)
                        for a in f.get("arguments", [])
                        if "value" in a
                    ]
                    derived = d.ext.resolve(f["functionReference"], args)
                    if "outputType" in f:
                        declared = D.type_from_proto(f["outputType"])
                        if D.render(declared) != D.render(derived):
                            findings.append(
                                ("scalar", D.render(declared), D.render(derived))
                            )
                for v in e.values():
                    walk_expr(v)
            elif isinstance(e, list):
                for v in e:
                    walk_expr(v)

        walk_expr(
            {
                k: v
                for k, v in node.items()
                if k not in ("input", "left", "right", "inputs")
            }
        )
        for m in node.get("measures", []):
            f = m["measure"]
            args = [
                d.expr_type(a["value"], inp)
                for a in f.get("arguments", [])
                if "value" in a
            ]
            derived = d.ext.resolve(f["functionReference"], args, phase=f.get("phase"))
            if "outputType" in f and D.render(
                D.type_from_proto(f["outputType"])
            ) != D.render(derived):
                findings.append(
                    (
                        "measure",
                        D.render(D.type_from_proto(f["outputType"])),
                        D.render(derived),
                    )
                )
        for w in node.get("windowFunctions", []):
            args = [
                d.expr_type(a["value"], inp)
                for a in w.get("arguments", [])
                if "value" in a
            ]
            derived = d.ext.resolve(
                w["functionReference"], args, phase=w.get("phase"), window=True
            )
            if "outputType" in w and D.render(
                D.type_from_proto(w["outputType"])
            ) != D.render(derived):
                findings.append(
                    (
                        "window",
                        D.render(D.type_from_proto(w["outputType"])),
                        D.render(derived),
                    )
                )

    walk_rel(plan["relations"][0]["root"]["input"])
    return findings
