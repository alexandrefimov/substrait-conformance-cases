"""Compares a producer run with the committed plans, and with --write replaces what moved.

    <python with protobuf> producers/sync_plans.py <substrait.desc> <run> <plans> [--write]

<run> is what producers/run.sh wrote: <run>/<producer>/<query>.pb or .err, and PRODUCER.txt with the
version line the producer printed. Each .pb is read with the Substrait protos at the release the
corpus targets, from a descriptor set rather than generated code, so no protobuf gencode has to
match the runtime.

A plan counts as moved only when it differs after function and URN anchors are renumbered: DataFusion
numbers them in hash-map order, and a rerun at the same pin would otherwise rewrite its plans. What
is written is still the producer's own bytes, so a consumer that depends on an anchor's value is
measured on the value the producer chose. Fields a newer release removed are reported by number,
because the JSON rendering drops them; they go to <plans>/<producer>/UNKNOWN.txt.

Exit status 1 when anything moved and --write was not given.
"""
import json
import os
import sys

from google.protobuf import descriptor_pb2, descriptor_pool, json_format, message_factory
from google.protobuf.unknown_fields import UnknownFieldSet

desc, run, plans = sys.argv[1:4]
write = "--write" in sys.argv[4:]
HERE = os.path.dirname(os.path.abspath(__file__))

fds = descriptor_pb2.FileDescriptorSet()
fds.ParseFromString(open(desc, "rb").read())
pool = descriptor_pool.DescriptorPool()
for f in fds.file:
    pool.Add(f)
Plan = message_factory.GetMessageClass(pool.FindMessageTypeByName("substrait.Plan"))

QUERIES = [l.split("\t")[0] for l in open(os.path.join(HERE, "queries.tsv"))
           if l.strip() and not l.startswith("#")]


def unknown(msg, where=""):
    out = ["%s%s.%d" % (where, msg.DESCRIPTOR.name, u.field_number) for u in UnknownFieldSet(msg)]
    for fd, v in msg.ListFields():
        if fd.type == fd.TYPE_MESSAGE:
            for x in (v if fd.is_repeated else [v]):
                if hasattr(x, "DESCRIPTOR"):
                    out += unknown(x)
    return sorted(set(out))


def canon(d):
    """The plan with every anchor replaced by what it names, and declarations in a fixed order."""
    urns = {u.get("extensionUrnAnchor", 0): u.get("urn") for u in d.get("extensionUrns", [])}
    fns = {}
    for e in d.get("extensions", []):
        f = e.get("extensionFunction")
        if f:
            fns[f.get("functionAnchor", 0)] = "%s#%s" % (urns.get(f.get("extensionUrnReference", 0)), f["name"])

    def walk(x):
        if isinstance(x, dict):
            y = {}
            for k, v in x.items():
                if k == "functionReference":
                    y[k] = fns.get(v, v)
                elif k in ("functionAnchor", "extensionUrnAnchor", "extensionUrnReference"):
                    continue
                else:
                    y[k] = walk(v)
            return y
        if isinstance(x, list):
            return [walk(v) for v in x]
        return x

    c = walk(d)
    for k in ("extensions", "extensionUrns"):
        if k in c:
            c[k] = sorted(c[k], key=lambda v: json.dumps(v, sort_keys=True))
    return c


def render(blob):
    p = Plan()
    p.ParseFromString(blob)
    return json_format.MessageToJson(p, indent=2) + "\n", unknown(p)


moved = 0
for producer in sorted(os.listdir(run)):
    src, dst = os.path.join(run, producer), os.path.join(plans, producer)
    if not os.path.isdir(src):
        continue
    os.makedirs(dst, exist_ok=True) if write else None
    unknown_lines = []
    for q in QUERIES:
        new_pb, new_err = os.path.join(src, q + ".pb"), os.path.join(src, q + ".err")
        old_json, old_err = os.path.join(dst, q + ".json"), os.path.join(dst, q + ".err")
        if os.path.exists(new_pb):
            blob = open(new_pb, "rb").read()
            text, unk = render(blob)
            unknown_lines += ["%s: %s" % (q, u) for u in unk]
            same = os.path.exists(old_json) and canon(json.loads(text)) == canon(json.load(open(old_json)))
            state = "same" if same else ("changed" if os.path.exists(old_json) or os.path.exists(old_err) else "new")
            if write and not same:
                open(os.path.join(dst, q + ".pb"), "wb").write(blob)
                open(old_json, "w").write(text)
                os.path.exists(old_err) and os.remove(old_err)
        elif os.path.exists(new_err):
            text = open(new_err).read()
            same = os.path.exists(old_err) and open(old_err).read() == text
            state = "same" if same else ("changed" if os.path.exists(old_json) or os.path.exists(old_err) else "new")
            if write and not same:
                open(old_err, "w").write(text)
                for ext in (".pb", ".json"):
                    f = os.path.join(dst, q + ext)
                    os.path.exists(f) and os.remove(f)
        else:
            state = "missing from the run"
        if state != "same":
            moved += 1
            print("%-11s %-22s %s" % (producer, q, state))
    for name, lines in (("PRODUCER.txt", open(os.path.join(src, "PRODUCER.txt")).read().splitlines()
                         if os.path.exists(os.path.join(src, "PRODUCER.txt")) else []),
                        ("UNKNOWN.txt", unknown_lines)):
        path, text = os.path.join(dst, name), "".join(l + "\n" for l in lines)
        old = open(path).read() if os.path.exists(path) else ""
        if old != text:
            moved += 1
            print("%-11s %-22s %s" % (producer, name, "changed"))
            if write:
                if text:
                    open(path, "w").write(text)
                elif os.path.exists(path):
                    os.remove(path)
print("%d moved%s" % (moved, ", written" if write and moved else ""))
sys.exit(1 if moved and not write else 0)
