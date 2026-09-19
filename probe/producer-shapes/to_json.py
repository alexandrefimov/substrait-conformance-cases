"""Writes <plan>.json beside every <plan>.pb under the given directory (protobuf JSON)."""
import os, sys
from google.protobuf import json_format
from substrait import plan_pb2
for d, _, fs in os.walk(sys.argv[1]):
    for f in fs:
        if f.endswith(".pb"):
            p = plan_pb2.Plan(); p.ParseFromString(open(os.path.join(d, f), "rb").read())
            open(os.path.join(d, f[:-3] + ".json"), "w").write(json_format.MessageToJson(p))
