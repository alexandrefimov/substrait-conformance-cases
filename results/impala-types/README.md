# Isthmus with Impala's type factory

This is a paired schema measurement over the 78 canonical plans, taken on
2026-09-08 with `probe/impala_types.py`. It is separate from the main matrix:
Impala's optimizer, catalog and executor are not participants in this probe.

| provider | matched | differed | unsupported | unscored |
| --- | ---: | ---: | ---: | ---: |
| Isthmus default | 49 | 5 | 19 | 5 |
| Isthmus with Impala types | 51 | 5 | 17 | 5 |

The full answers are [the default column](ISTHMUS-DEFAULT.txt) and
[the Impala-types column](ISTHMUS-IMPALA-TYPES.txt). Both use substrait-java
`fff639064df794840db36fffcd881c09100e23df`, Calcite 1.42.0, JDK 17.0.20.1 and the
same ordered classpath. The default side also reproduces every answer in the
main Isthmus column at that revision, including refusals.

The Impala artifacts came from a development build with source revision label
`453eeeccaa6f0a6852083fc70da34a8044fad011`. The six supplied type-source files were
byte-identical to those in Impala `b948bb56d934660f7edceeec89a924dfd3d4d54f`.
These labels identify the supplied build context; the Impala side has not been
rebuilt from scratch by this harness. The local run record fingerprints the
actual classpath and corpus inputs. Built artifacts and machine-specific logs
are not distributed here.

## What changed

| case | default | Impala types |
| --- | --- | --- |
| `precision_timestamp_p07` | rejects precision above 6 | required `TIMESTAMP(7)` |
| `precision_timestamp_p09` | rejects precision above 6 | required `TIMESTAMP(9)` |
| `precision_timestamp_p12` | rejects precision above 6 | rejects literal precision above 9 |

Only these three answers moved: two previously refused plans now produce the
expected schema, and one refusal has a different cause. The other 75 answers
are identical. The five existing divergences remain: `read_projection_mask`
and four intersection/difference nullability cases. Decimal and string cases
show no change on this corpus.

The timestamp difference follows the two conversion checks. Isthmus's
`TypeConverter` and `ExpressionRexConverter` check precision against the supplied
type system. `ImpalaTypeSystemImpl.getMaxPrecision(TIMESTAMP)` returns 15,
which lets precisions 7, 9 and 12 pass that check. The literal converter's
`unitsPerSecond` accepts only 0 through 9, so the precision-12 plan still fails.

The loaded provider factory is `ImpalaTypeFactoryImpl`, but the `RelBuilder`
factory is `JavaTypeFactoryImpl` with `ImpalaTypeSystemImpl`. Passing the
provider's type system does not install its factory instance in the builder.
This measurement therefore does not cover every use of Impala's
`leastRestrictive` override. Matching decimal answers also do not prove native
Impala return-type derivation; the probe retains Isthmus's converters.

These are schema results. Values, fractional-second preservation and Impala
execution have not been checked.

## Checking or retaking the pair

```sh
python3 probe/check_expected.py results/impala-types/ISTHMUS-DEFAULT.txt calcite
python3 probe/check_expected.py results/impala-types/ISTHMUS-IMPALA-TYPES.txt calcite
python3 probe/column_diff.py results/impala-types/ISTHMUS-DEFAULT.txt \
  results/impala-types/ISTHMUS-IMPALA-TYPES.txt
```

Each command returns 1 here because it reports the measured differences.
[Probe setup and output contracts](../../probe/README.md#impala-type-factory-comparison)
describe how to retake the pair. Both type factories must use the same dependency
versions and classpath; comparing separately resolved environments would mix
type-system effects with dependency changes.
