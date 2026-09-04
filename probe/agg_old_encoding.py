"""A control: the same aggregate in the retired encoding (Grouping.grouping_expressions, field 1).

    python3 probe/agg_old_encoding.py <case.json> <output.json>

The validator at spec 0.87 parses the result without errors while calling the same case in the
current encoding invalid, which is what shows the problem is in the parsing branch, not in the plan.
"""
import json, sys

d = json.load(open(sys.argv[1]))
agg = d["relations"][0]["root"]["input"]["aggregate"]
exprs = agg.pop("groupingExpressions")
agg["groupings"] = [{"groupingExpressions": [exprs[i] for i in g.get("expressionReferences", [])]}
                    for g in agg["groupings"]]
json.dump(d, open(sys.argv[2], "w"))
