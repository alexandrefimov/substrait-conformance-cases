"""Writes the committed producer plans as the consumers' corpus, with table names in their catalog.

    <python with protobuf> producers/catalog_names.py <substrait.desc> <producers/plans> <out>

Writes <out>/<producer>__<query>.json and .bin. A NamedTable names a table in the consumer's catalog,
and each producer spells the shared tables its own way: Spark as spark_catalog.default.t_rn, Isthmus
upper-cased as T_RN with columns A and B. Which catalog a name resolves in is the deployment's
business, not a rule of the specification, so here every named table becomes the bare lower-case
name the engine probes register, and its base_schema names are lower-cased with it. Nothing else in
the plan is touched, and the committed plans keep the producer's own spelling.
"""
import json
import os
import sys

from google.protobuf import descriptor_pb2, descriptor_pool, message_factory

desc, plans, out = sys.argv[1:4]
fds = descriptor_pb2.FileDescriptorSet()
fds.ParseFromString(open(desc, "rb").read())
pool = descriptor_pool.DescriptorPool()
for f in fds.file:
    pool.Add(f)
Plan = message_factory.GetMessageClass(pool.FindMessageTypeByName("substrait.Plan"))


def rename(x):
    if isinstance(x, dict):
        read = x.get("read")
        if isinstance(read, dict) and "namedTable" in read:
            read["namedTable"]["names"] = [read["namedTable"]["names"][-1].lower()]
            if "baseSchema" in read:
                read["baseSchema"]["names"] = [n.lower() for n in read["baseSchema"].get("names", [])]
        for v in x.values():
            rename(v)
    elif isinstance(x, list):
        for v in x:
            rename(v)


def rename_message(m):
    if m.DESCRIPTOR.name == "ReadRel" and m.HasField("named_table"):
        names = list(m.named_table.names)
        del m.named_table.names[:]
        m.named_table.names.append(names[-1].lower())
        if m.HasField("base_schema"):
            lowered = [n.lower() for n in m.base_schema.names]
            del m.base_schema.names[:]
            m.base_schema.names.extend(lowered)
    for fd, v in m.ListFields():
        if fd.type == fd.TYPE_MESSAGE:
            for x in (v if fd.is_repeated else [v]):
                rename_message(x)


os.makedirs(out, exist_ok=True)
for producer in sorted(os.listdir(plans)):
    d = os.path.join(plans, producer)
    if not os.path.isdir(d):
        continue
    for f in sorted(os.listdir(d)):
        if not f.endswith(".json"):
            continue
        doc = json.load(open(os.path.join(d, f)))
        rename(doc)
        base = os.path.join(out, "%s__%s" % (producer, f[:-5]))
        open(base + ".json", "w").write(json.dumps(doc, indent=2) + "\n")
        # The binary is the producer's own bytes with the same names changed in place, so fields the
        # JSON rendering drops (removed from the release) still reach the consumers that read it.
        plan = Plan()
        plan.ParseFromString(open(os.path.join(d, f[:-5] + ".pb"), "rb").read())
        rename_message(plan)
        open(base + ".bin", "wb").write(plan.SerializeToString())
