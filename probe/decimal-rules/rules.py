#!/usr/bin/env python3
"""Compare decimal return-type derivation across the implementations that share
Substrait's formula, over every operand type pair the specification allows.

Each rule set below is transcribed from its own source, including the clamp
above precision 38. They could share one helper — the three that agree do agree
line for line — but then "0 / 606841 differ" would be true by construction, and
an error in the shared helper would move every row together and stay invisible.
Written out separately, the agreement is computed.

  substrait  extensions/functions_arithmetic_decimal.yaml @ e708362
  gandiva    apache/arrow-java gandiva DecimalTypeUtil.java (identical in
             apache/arrow apache-arrow-6.0.0 and 7.0.0, Java and C++), the
             reference named in substrait-io/substrait#151
  hive       apache/hive rel/release-4.0.1 GenericUDFOPNumeric{Plus,Minus},
             GenericUDFOPMultiply, GenericUDFOPDivide and GenericUDFOPMod, each
             through GenericUDFBaseNumeric.adjustPrecScale
  spark      apache/spark v4.0.1 catalyst arithmetic.scala + DecimalType.scala,
             with spark.sql.decimalOperations.allowPrecisionLoss true (default)
             and false
  arrow_rs   arrow-arith 59.3.0 numeric.rs decimal_op, what DataFusion evaluates

Domain: type_classes.md gives DECIMAL<P,S> as P <= 38 and 0 <= S <= P and does
not bound P below; reading that as P >= 1 gives 779 types and 606841 pairs.

Usage: rules.py [--op add|subtract|multiply|divide|modulus] [--examples N]
"""

import argparse
import itertools

MAX_PRECISION = 38
MIN_ADJUSTED_SCALE = 6
OPS = ("add", "subtract", "multiply", "divide", "modulus")


def types():
    return [(p, s) for p in range(1, MAX_PRECISION + 1) for s in range(0, p + 1)]


def substrait(op, p1, s1, p2, s2):
    """The return expression of each function, line for line."""
    if op in ("add", "subtract"):
        init_scale = max(s1, s2)
        init_prec = init_scale + max(p1 - s1, p2 - s2) + 1
    elif op == "multiply":
        init_scale = s1 + s2
        init_prec = p1 + p2 + 1
    elif op == "divide":
        init_scale = max(6, s1 + p2 + 1)
        init_prec = p1 - s1 + p2 + init_scale      # P2, where the others use S2
    else:
        init_scale = max(s1, s2)
        init_prec = min(p1 - s1, p2 - s2) + init_scale
    min_scale = min(init_scale, 6)
    delta = init_prec - 38
    prec = min(init_prec, 38)
    scale_after_borrow = max(init_scale - delta, min_scale)
    scale = scale_after_borrow if init_prec > 38 else init_scale
    return prec, scale


def gandiva(op, p1, s1, p2, s2):
    """getResultTypeForOperation, then adjustScaleIfNeeded."""
    if op in ("add", "subtract"):
        result_scale = max(s1, s2)
        result_precision = result_scale + max(p1 - s1, p2 - s2) + 1
    elif op == "multiply":
        result_scale = s1 + s2
        result_precision = p1 + p2 + 1
    elif op == "divide":
        result_scale = max(MIN_ADJUSTED_SCALE, s1 + p2 + 1)
        result_precision = p1 - s1 + s2 + result_scale
    else:
        result_scale = max(s1, s2)
        result_precision = min(p1 - s1, p2 - s2) + result_scale
    precision, scale = result_precision, result_scale
    if precision > MAX_PRECISION:
        min_scale = min(scale, MIN_ADJUSTED_SCALE)
        delta = precision - MAX_PRECISION
        precision = MAX_PRECISION
        scale = max(scale - delta, min_scale)
    return precision, scale


def hive(op, p1, s1, p2, s2):
    """deriveResultDecimalTypeInfo per operator, then adjustPrecScale."""
    if op in ("add", "subtract"):
        int_part = max(p1 - s1, p2 - s2)
        scale = max(s1, s2)
        prec = int_part + scale + 1
    elif op == "multiply":
        scale = s1 + s2
        prec = p1 + p2 + 1
    elif op == "divide":
        int_dig = p1 - s1 + s2
        scale = max(6, s1 + p2 + 1)
        prec = int_dig + scale
    else:
        prec = min(p1 - s1, p2 - s2) + max(s1, s2)
        scale = max(s1, s2)
    if prec <= MAX_PRECISION:
        return prec, scale
    int_digits = prec - scale
    min_scale_value = min(scale, MIN_ADJUSTED_SCALE)
    adjusted_scale = max(MAX_PRECISION - int_digits, min_scale_value)
    return MAX_PRECISION, adjusted_scale


def spark_precision_loss(op, p1, s1, p2, s2):
    """resultDecimalType, then DecimalType.adjustPrecisionScale."""
    if op in ("add", "subtract"):
        result_scale = max(s1, s2)
        result_precision = max(p1 - s1, p2 - s2) + result_scale + 1
    elif op == "multiply":
        result_scale = s1 + s2
        result_precision = p1 + p2 + 1
    elif op == "divide":
        int_dig = p1 - s1 + s2
        result_scale = max(MIN_ADJUSTED_SCALE, s1 + p2 + 1)
        result_precision = int_dig + result_scale
    else:
        result_scale = max(s1, s2)
        result_precision = min(p1 - s1, p2 - s2) + result_scale
    precision, scale = result_precision, result_scale
    if precision <= MAX_PRECISION:
        return precision, scale
    int_digits = precision - scale
    min_scale_value = min(scale, MIN_ADJUSTED_SCALE)
    adjusted_scale = max(MAX_PRECISION - int_digits, min_scale_value)
    return MAX_PRECISION, adjusted_scale


def spark_no_precision_loss(op, p1, s1, p2, s2):
    """The other branch of resultDecimalType: DecimalType.bounded, which caps
    precision and scale independently, and a divide that slides the scale down
    by half the excess rather than borrowing what is needed."""
    if op == "divide":
        int_dig = min(MAX_PRECISION, p1 - s1 + s2)
        dec_dig = min(MAX_PRECISION, max(MIN_ADJUSTED_SCALE, s1 + p2 + 1))
        diff = int_dig + dec_dig - MAX_PRECISION
        if diff > 0:
            dec_dig -= diff // 2 + 1
            int_dig = MAX_PRECISION - dec_dig
        return min(int_dig + dec_dig, MAX_PRECISION), min(dec_dig, MAX_PRECISION)
    if op in ("add", "subtract"):
        scale = max(s1, s2)
        prec = max(p1 - s1, p2 - s2) + scale + 1
    elif op == "multiply":
        scale = s1 + s2
        prec = p1 + p2 + 1
    else:
        scale = max(s1, s2)
        prec = min(p1 - s1, p2 - s2) + scale
    return min(prec, MAX_PRECISION), min(scale, MAX_PRECISION)


def arrow_rs(op, p1, s1, p2, s2):
    """decimal_op. Add, subtract and modulus cap the precision and keep the
    scale; multiply raises rather than return a type when the scale would pass
    38; divide follows postgres and MySQL with a fixed scale increment of 4,
    which is a different rule and not a different clamp."""
    if op in ("add", "subtract"):
        result_scale = max(s1, s2)
        result_precision = min(result_scale + max(p1 - s1, p2 - s2) + 1, MAX_PRECISION)
    elif op == "multiply":
        result_precision = min(p1 + p2 + 1, MAX_PRECISION)
        result_scale = s1 + s2
        if result_scale > MAX_PRECISION:
            return None
    elif op == "divide":
        result_scale = min(s1 + 4, MAX_PRECISION)
        mul_pow = result_scale - s1 + s2
        result_precision = min(p1 + mul_pow, MAX_PRECISION)
    else:
        result_scale = max(s1, s2)
        result_precision = min(result_scale + min(p1 - s1, p2 - s2), MAX_PRECISION)
    return result_precision, result_scale


# The three that implement the reference. Whether they agree with each other is
# a different question from whether the YAML agrees with them, and it is the one
# that decides whether a disagreement is the formula's or the function's.
IMPLEMENTATIONS = ("gandiva", "hive", "spark(allowPrecisionLoss=true)")

RULES = {
    "gandiva": gandiva,
    "hive": hive,
    "spark(allowPrecisionLoss=true)": spark_precision_loss,
    "spark(allowPrecisionLoss=false)": spark_no_precision_loss,
    "arrow_rs/datafusion": arrow_rs,
}


def fmt(t):
    return "error" if t is None else "dec(%d,%d)" % t


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--op", choices=OPS, action="append")
    ap.add_argument("--examples", type=int, default=3,
                    help="smallest disagreeing operand pairs to print per rule")
    args = ap.parse_args()
    ops = args.op or list(OPS)

    pairs = list(itertools.product(types(), types()))
    print("operand type pairs: %d" % len(pairs))
    print("a count of pairs that disagree below precision 38 separates a different"
          " rule from a different clamp")
    for op in ops:
        print("\n== %s" % op)
        for name, rule in RULES.items():
            diff, below = [], 0
            for (p1, s1), (p2, s2) in pairs:
                a = substrait(op, p1, s1, p2, s2)
                b = rule(op, p1, s1, p2, s2)
                if a != b:
                    diff.append((p1, s1, p2, s2, a, b))
                    if a[0] < MAX_PRECISION:
                        below += 1
            tail = "" if not diff else ", %d below 38" % below
            print("  vs %-32s %7d / %d differ%s" % (name, len(diff), len(pairs), tail))
            for p1, s1, p2, s2, a, b in diff[:args.examples]:
                print("      %s(dec(%d,%d), dec(%d,%d)): substrait %s, %s %s"
                      % (op, p1, s1, p2, s2, fmt(a), name, fmt(b)))
        among = 0
        for (p1, s1), (p2, s2) in pairs:
            answers = {RULES[n](op, p1, s1, p2, s2) for n in IMPLEMENTATIONS}
            if len(answers) != 1:
                among += 1
        print("  %-35s %7d / %d differ" % ("among " + ", ".join(IMPLEMENTATIONS),
                                           among, len(pairs)))


if __name__ == "__main__":
    main()
