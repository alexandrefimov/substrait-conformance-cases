"""Function return types, derived from the extension file the call names.

A call in a plan carries both the answer and the question: `output_type` states the return type,
and the extension URN plus the compound name say where that type is supposed to come from.
`algebra.proto` is explicit about which is which - "Must be set to the return type of the function,
exactly as derived using the declaration in the extension". This file derives it, and never reads
`output_type`; see deriver/README.md for why that restriction is the whole point.

What it implements, from the spec text at 0.102.0:

  site/docs/extensions/index.md            the compound signature `name:short_arg_types`, the short
                                           name table, `any` and `any[\\d]` binding
  site/docs/expressions/scalar_functions.md  MIRROR / DECLARED_OUTPUT / DISCRETE nullability, the
                                           return type expression language and its operators
  site/docs/expressions/aggregate_functions.md  decomposable functions and the intermediate type
  proto/substrait/algebra.proto            which kind of function each call may name, how value,
                                           type and enumeration arguments are passed, and what an
                                           unset aggregation phase implies

resolve() binds a call by the name its declaration holds, bind() matches the arguments to one
implementation, return_type() derives what it returns. Binding fails in two ways that are kept
apart: Unbound when the rules match nothing, Unsupported when this deriver has no rule to apply.

The files themselves are read out of a Substrait checkout at the release the plans declare, not out
of its working tree, so a checkout sitting on a branch cannot quietly change what a rule says. The
bytes are pinned by content in deriver/spec.pins.
"""
import os, subprocess, sys

from . import type_model as types
from .type_model import Type, Unbound, Unsupported

SPEC_REF = os.environ.get("DERIVER_SPEC_REF", "v0.102.0")
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
PINS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "spec.pins")

# The signature short name of each type class: site/docs/extensions/index.md, "Type Short Names".
# Transcribed, so it can go stale - a type class missing from it stops the run instead of being
# spelled some other way, because a wrong short name would silently pick a different overload.
SHORT_ARG = {
    "i8": "i8", "i16": "i16", "i32": "i32", "i64": "i64", "fp32": "fp32", "fp64": "fp64",
    "string": "str", "binary": "vbin", "boolean": "bool", "date": "date",
    "interval_year": "iyear", "interval_day": "iday", "interval_compound": "icompound",
    "uuid": "uuid", "fixedchar": "fchar", "varchar": "vchar", "fixedbinary": "fbin",
    "decimal": "dec", "precision_time": "pt", "precision_timestamp": "pts",
    "precision_timestamp_tz": "ptstz", "struct": "struct", "list": "list", "map": "map",
    "func": "func",
}


class Impl:
    """One implementation of one function, with the part of the declaration a return type needs."""

    def __init__(self, file, kind, name, body):
        self.file, self.kind, self.name, self.body = file, kind, name, body
        self.args = body.get("args", []) or []
        self.variadic = body.get("variadic")
        # "Optional, defaults to MIRROR" - scalar_functions.md, Nullability Handling.
        self.nullability = body.get("nullability", "MIRROR")
        self.ret = body.get("return")
        self.intermediate = body.get("intermediate")
        self.decomposable = body.get("decomposable", "NONE")

    @property
    def signature(self):
        return "%s:%s" % (self.name, "_".join(self._short(a) for a in self.args))

    def _short(self, arg):
        """One argument's contribution to the signature.

        An enumeration argument is `req`; a value or type argument is the short name of its type.
        Function-level options are not arguments and contribute nothing, which is why only `args`
        is walked here.
        """
        if "options" in arg and "value" not in arg and "type" not in arg:
            return "req"
        written = arg.get("value") or arg.get("type")
        if written is None:
            raise Unsupported("argument of %s with neither value nor type" % self.name)
        parsed = types.parse(written)
        if parsed.name.startswith("any"):
            return "any"
        if parsed.name not in SHORT_ARG:
            raise Unsupported("no signature short name for %r" % parsed.name)
        return SHORT_ARG[parsed.name]


def _git_show(path):
    out = subprocess.run(["git", "-C", _checkout(), "show", "%s:%s" % (SPEC_REF, path)],
                         capture_output=True)
    if out.returncode != 0:
        raise Unsupported("%s at %s: %s" % (path, SPEC_REF, out.stderr.decode().strip()))
    return out.stdout


def _checkout():
    d = os.environ.get("SUBSTRAIT_DIR", "")
    if not d:
        raise Unsupported("set SUBSTRAIT_DIR to a substrait checkout: the extension files are read "
                          "from it at %s" % SPEC_REF)
    return d


def _blob_sha(data):
    """Git's own object id for these bytes, so a pin can be checked with `git ls-tree` by hand."""
    import hashlib
    h = hashlib.sha1()
    h.update(b"blob %d\0" % len(data))
    h.update(data)
    return h.hexdigest()


def pinned():
    """The extension files this deriver has read, by content: `<sha1>  extensions/<file>.yaml`."""
    pins = {}
    if os.path.exists(PINS):
        for line in open(PINS, encoding="utf-8"):
            line = line.split("#", 1)[0].strip()
            if line:
                sha, path = line.split()
                pins[path] = sha
    return pins


class Library:
    """Every function declared in the extension files, indexed by URN and compound signature."""

    def __init__(self, docs=None):
        """The files at SPEC_REF in a checkout, or `docs` ({urn: parsed file}) given directly.

        The second form is for tests: a file written in the test, so that a binding rule can be
        checked on a declaration small enough to read, without a checkout.
        """
        self.by_urn = {}
        self.read = {}
        self._indexed = {}
        if docs is None:
            self._load()
        else:
            for urn, doc in docs.items():
                self.by_urn[urn] = ("given:%s" % urn, doc)

    def _load(self):
        # PyYAML is imported here rather than at the top of the file. Everything above this point -
        # the type model, the relation rules, the return type expression evaluator - is standard
        # library only, and probe/selfcheck.sh runs with no environment beyond it. Reading an
        # extension file already needs a Substrait checkout, so the one step that needs a package
        # is the one that needs a checkout too.
        try:
            import yaml
        except ImportError:
            raise Unsupported("reading the extension files needs PyYAML (pip install pyyaml); "
                              "the relation rules and the expression evaluator do not")
        self._yaml = yaml
        listing = subprocess.run(["git", "-C", _checkout(), "ls-tree", "--name-only",
                                  "%s:extensions" % SPEC_REF], capture_output=True)
        if listing.returncode != 0:
            raise Unsupported("no extensions/ at %s in %s" % (SPEC_REF, _checkout()))
        pins = pinned()
        for name in listing.stdout.decode().split():
            if not name.endswith((".yaml", ".yml")):
                continue
            path = "extensions/" + name
            raw = _git_show(path)
            doc = self._yaml.safe_load(raw)
            urn = (doc or {}).get("urn")
            if not urn:
                continue
            sha = _blob_sha(raw)
            if path in pins and pins[path] != sha:
                raise Unsupported("%s is %s, pinned at %s in deriver/spec.pins" %
                                  (path, sha, pins[path]))
            self.read[path] = sha
            self.by_urn[urn] = (path, doc)

    def _index(self, urn):
        """Signature -> Impl for one file, built when a plan first names that URN.

        An implementation whose signature this file cannot spell - a user-defined type it has no
        short name for, an argument form it does not read - is kept aside under its own name rather
        than dropped. Dropped, it would come back as "the extension declares no such function",
        which is a different and wrong answer to give about a file that declares it.
        """
        path, doc = self.by_urn[urn]
        index, aside, by_name = {}, {}, {}
        for key, kind in (("scalar_functions", "scalar"), ("aggregate_functions", "aggregate"),
                          ("window_functions", "window")):
            for fn in doc.get(key) or []:
                for body in fn.get("impls") or []:
                    impl = Impl(path, kind, fn["name"], body)
                    try:
                        sig = impl.signature
                    except Unsupported as why:
                        aside.setdefault(fn["name"], str(why))
                        continue
                    if sig in index:
                        raise Unsupported("%s declares %s twice" % (path, sig))
                    index[sig] = impl
                    by_name.setdefault(fn["name"], []).append(impl)
        return index, aside, by_name

    def indexed(self, urn):
        """(signature -> Impl, name -> why it is not read, name -> [Impl]) for one file."""
        if urn not in self._indexed:
            self._indexed[urn] = self._index(urn)
        return self._indexed[urn]

    def lookup(self, urn, compound):
        if urn not in self.by_urn:
            raise Unsupported("no extension file declares urn %r at %s" % (urn, SPEC_REF))
        index, aside, _ = self.indexed(urn)
        if compound not in index:
            name = compound.split(":", 1)[0]
            if name in aside:
                raise Unsupported("%s declares %s, and this deriver does not read its signature: %s"
                                  % (urn, name, aside[name]))
            raise Unsupported("%s declares no %s" % (urn, compound))
        return index[compound]


_LIBRARY = [None]


def library():
    if _LIBRARY[0] is None:
        _LIBRARY[0] = Library()
    return _LIBRARY[0]


class EnumArg:
    """A call's enumeration argument: FunctionArgument.enum, a string naming one option."""

    def __init__(self, value):
        self.value = value

    def __repr__(self):
        return "enum(%s)" % self.value


class TypeArg:
    """A call's type argument: FunctionArgument.type, a type rather than a value of one."""

    def __init__(self, type_):
        self.type = type_

    def __repr__(self):
        return "type(%s)" % types.render_field(self.type)


def _render_arg(a):
    return types.render_field(a) if isinstance(a, Type) else repr(a)


# What each kind of call may bind. algebra.proto on ScalarFunction.function_reference: "which must
# refer to a scalar function in the associated YAML file"; on AggregateFunction: "which must refer
# to an aggregate function"; on WindowFunction: "The function must be: a window function, an
# aggregate function". The last is also window_functions.md: "Aggregate functions can be treated as
# a window functions with Window Type set to STREAMING".
CALLABLE = {"scalar": ("scalar",), "aggregate": ("aggregate",), "window": ("window", "aggregate")}

PHASES = ("AGGREGATION_PHASE_UNSPECIFIED", "AGGREGATION_PHASE_INITIAL_TO_INTERMEDIATE",
          "AGGREGATION_PHASE_INTERMEDIATE_TO_INTERMEDIATE", "AGGREGATION_PHASE_INITIAL_TO_RESULT",
          "AGGREGATION_PHASE_INTERMEDIATE_TO_RESULT")
# The phases whose inputs are intermediate values. UNSPECIFIED is one of them because the enum says
# so in algebra.proto: "AGGREGATION_PHASE_UNSPECIFIED = 0; // Implies `INTERMEDIATE_TO_RESULT`."
FROM_INTERMEDIATE = ("AGGREGATION_PHASE_UNSPECIFIED",
                     "AGGREGATION_PHASE_INTERMEDIATE_TO_INTERMEDIATE",
                     "AGGREGATION_PHASE_INTERMEDIATE_TO_RESULT")


def resolve(urn, name, kind, args, phase=None):
    """Bind one call and derive its return type: (type, how it was bound).

    `name` is what the plan's extension declaration says, `args` the call's arguments (a Type for a
    value, TypeArg, EnumArg), `phase` the call's AggregationPhase or None for a scalar call. How is
    "signature" or "name". Raises Unbound when the rules bind the call to nothing, Unsupported when
    this deriver cannot tell.

    extensions.proto calls ExtensionFunction.name "A function signature", and extensions/index.md
    says "Extension declarations in plans identify functions by signature only". So a name with a
    colon is looked up as a signature and nothing else: its implementation either accepts the
    arguments or the call is unbound, even when another implementation of the same function would
    accept them.
    """
    lib = library()
    if urn not in lib.by_urn:
        raise Unbound("no extension file declares urn %r at %s" % (urn, SPEC_REF))
    index, aside, by_name = lib.indexed(urn)
    if ":" in name:
        # A signature with nothing after the colon, `count:`, is what the prose gives a function
        # with no arguments: "the short type names of each argument joined with underscores" over
        # none is the empty string. The ABNF beside it requires at least one short-arg-type, so the
        # two disagree here; the prose is followed, since the grammar leaves a niladic
        # implementation, which the same page allows ("defaults to niladic"), with no signature.
        how, impl = "signature", index.get(name)
        if impl is None:
            if name.split(":", 1)[0] in aside:
                raise Unsupported("%s declares %s, and this deriver does not read its signature: "
                                  "%s" % (urn, name.split(":", 1)[0],
                                          aside[name.split(":", 1)[0]]))
            raise Unbound("%s declares no function signature %s" % (urn, name))
        candidates = [impl]
    else:
        # A name with no colon is not a function signature, which is what the declaration must
        # hold, and the spec does not say what a consumer does with one. Chosen here: bind it by
        # the argument types, among the implementations of the function with that name in that
        # file - algebra.proto asks of a value argument that it "yield a value of a type that a
        # function overload is defined for". The record says so (binding "name"), so a reader can
        # keep these apart from calls bound by signature.
        how, candidates = "name", list(by_name.get(name, []))
        if not candidates and name not in aside:
            raise Unbound("%s declares no function named %r" % (urn, name))
    fitting = [c for c in candidates if c.kind in CALLABLE[kind]]
    if candidates and not fitting:
        raise Unbound("%s is %s %s function, called as %s %s function" %
                      (name, _a(candidates[0].kind), candidates[0].kind, _a(kind), kind))
    accepted, refused, unknown = [], [], []
    if how == "name" and name in aside:
        unknown.append("%s declares %s, and this deriver does not read every signature of it: %s"
                       % (urn, name, aside[name]))
    for impl in fitting:
        try:
            accepted.append((impl, bind(impl, args, phase)))
        except Unbound as why:
            refused.append(str(why))
        except Unsupported as why:
            unknown.append(str(why))
    if unknown:
        # One implementation this deriver cannot read may be the one that binds, or a second one
        # that makes the call ambiguous, so no answer is given for the others either.
        raise Unsupported(unknown[0])
    if not accepted:
        if len(refused) == 1:
            raise Unbound(refused[0])
        raise Unbound("no implementation of %s in %s accepts (%s)" %
                      (name, urn, ", ".join(_render_arg(a) for a in args)))
    derived = [return_type(impl, args, phase, bound) for impl, bound in accepted]
    if any(d != derived[0] for d in derived):
        # Only reachable by a bare name: a signature names one implementation. When several accept
        # the arguments and agree on the return type, which one was meant does not change the
        # answer; when they disagree, nothing in the plan says which.
        raise Unsupported("%d implementations of %s accept (%s) and return different types" %
                          (len(accepted), name, ", ".join(_render_arg(a) for a in args)))
    return derived[0], how


def _a(word):
    return "an" if word[0] in "aeiou" else "a"


def bind(impl, args, phase=None):
    """Bind a call's arguments to one implementation and return the bound parameters.

    Raises Unbound when the arguments do not fit the declaration, Unsupported when this deriver
    cannot read what the declaration says.
    """
    if phase is not None and phase not in PHASES:
        raise Unsupported("aggregation phase %r" % (phase,))
    if phase not in (None, "AGGREGATION_PHASE_INITIAL_TO_RESULT") and impl.decomposable == "NONE":
        # "For functions that are NOT decomposable, the only valid option will be
        # INITIAL_TO_RESULT." - aggregate_functions.md, Aggregate Binding. An unset phase is no
        # exception: it implies INTERMEDIATE_TO_RESULT.
        raise Unbound("%s is not decomposable, and phase %s is valid only for one that is" %
                      (impl.signature, phase))
    if phase in FROM_INTERMEDIATE:
        return _bind_intermediate(impl, args, phase)
    return _bind_arguments(impl, args)


def _bind_intermediate(impl, args, phase):
    """A call whose inputs are intermediate values, matched against the intermediate type.

    algebra.proto: INTERMEDIATE_TO_RESULT "Specifies that the inputs of the aggregate or window
    function are the intermediate values of the function". An intermediate type is one type,
    "a struct in many cases", so the one case read here is a call passing exactly one value. The
    spec does not say how a call passes intermediate values otherwise - AggregateFunction.arguments
    "must have exactly the number of arguments specified in the function definition", which for a
    function of two arguments and one intermediate struct cannot both hold - and any other shape is
    declined.
    """
    if impl.intermediate is None:
        raise Unsupported("%s is %s decomposable and declares no intermediate type" %
                          (impl.signature, impl.decomposable))
    if len(args) != 1 or not isinstance(args[0], Type):
        raise Unsupported("phase %s takes intermediate values as input, and the spec does not say "
                          "how a call with %d argument(s) passes them" % (phase, len(args)))
    bound = {}
    _match_one(impl, {"value": impl.intermediate}, args[0], bound, "the intermediate input")
    return bound


# Stands for a parameter an INCONSISTENT variadic argument bound to different values in one call.
VARYING = object()


def _bind_arguments(impl, args):
    positions, fixed = _positions(impl, len(args))
    consistency = (impl.variadic or {}).get("parameterConsistency")
    try:
        return _match_all(impl, positions, args, fixed, consistency != "INCONSISTENT")
    except Unbound as refused:
        if impl.variadic is None or consistency is not None:
            raise
        first = refused
    # scalar_functions.md: a variadic argument "can be marked as either consistent or
    # inconsistent", and it gives no default; none of the files read here marks one. Where the two
    # readings agree, which is always unless the variadic argument carries a parameter, the answer
    # above stands. Where only INCONSISTENT would bind, the call is declined: under one reading it
    # is unbound, under the other it binds.
    try:
        _match_all(impl, positions, args, fixed, False)
    except Unbound:
        raise first
    raise Unsupported("%s binds these arguments only if its variadic argument is INCONSISTENT, "
                      "which the file does not say and the spec gives no default for"
                      % impl.signature)


def _positions(impl, count):
    """The declared argument at each position of a call with `count` arguments."""
    declared = impl.args
    if impl.variadic is None:
        # "Every defined argument must be specified in every invocation of the function."
        if count != len(declared):
            raise Unbound("%s takes %d arguments, called with %d" %
                          (impl.signature, len(declared), count))
        return list(declared), len(declared)
    if not declared:
        raise Unsupported("variadic %s with no declared argument" % impl.name)
    fixed = len(declared) - 1
    repeats = count - fixed
    low, high = impl.variadic.get("min"), impl.variadic.get("max")
    if repeats < 0 or (low is not None and repeats < low) or (high is not None and repeats > high):
        raise Unbound("%s takes %d fixed arguments and %s to %s variadic ones, called with %d"
                      % (impl.signature, fixed, low, "any number" if high is None else high,
                         count))
    if low is None and repeats < 1:
        # "the argument can optionally have a lower bound": without one the file does not say
        # whether no instance at all is allowed, and the spec gives no default.
        raise Unsupported("%s gives its variadic argument no lower bound, called with none of it"
                          % impl.signature)
    return list(declared[:fixed]) + [declared[-1]] * repeats, fixed


def _match_all(impl, positions, args, fixed, consistent):
    """Match every argument. With `consistent` false, each repeat of the variadic argument binds its
    own parameters: "each unique C can be bound to a different type". `any1`..`any9` stay one type
    per call either way - extensions/index.md says so of every invocation, without exception."""
    bound = {}
    for i in range(fixed):
        _match_one(impl, positions[i], args[i], bound, "argument %d" % i)
    base, seen = dict(bound), {}
    for i in range(fixed, len(args)):
        scope = bound if consistent else dict(base)
        _match_one(impl, positions[i], args[i], scope, "argument %d" % i)
        if consistent:
            continue
        for k, v in scope.items():
            if k in base:
                continue
            if k.startswith("any"):
                if bound.get(k, v) != v:
                    raise Unbound("%s is both %s and %s in one call" %
                                  (k, types.render_field(bound[k]), types.render_field(v)))
                bound[k] = v
            else:
                seen.setdefault(k, []).append(v)
    for k, values in seen.items():
        bound[k] = values[0] if all(v == values[0] for v in values) else VARYING
    return bound


def _match_one(impl, declared, actual, bound, where):
    """One argument against its declared position.

    The three nullability modes differ here exactly as scalar_functions.md describes: MIRROR and
    DECLARED_OUTPUT strip "the outermost nullability of each argument ... before binding", DISCRETE
    requires it to "match the nullability declared at the corresponding position". Nested
    nullability is never stripped.
    """
    if "value" not in declared and "type" not in declared:
        if "options" not in declared:
            raise Unsupported("%s of %s declares neither a value, a type nor options" %
                              (where, impl.signature))
        # "Enum arguments must be bound using FunctionArgument.enum ... with a string that
        # case-insensitively matches one of the allowed options." - algebra.proto
        if not isinstance(actual, EnumArg):
            raise Unbound("%s of %s is an enumeration, called with %s" %
                          (where, impl.signature, _render_arg(actual)))
        if str(actual.value).lower() not in [str(o).lower() for o in declared["options"]]:
            raise Unbound("%s of %s takes one of %s, called with %r" %
                          (where, impl.signature, declared["options"], actual.value))
        return
    if isinstance(actual, EnumArg):
        raise Unbound("%s of %s takes a %s, called with an enumeration" %
                      (where, impl.signature, "value" if "value" in declared else "type"))
    if "value" in declared:
        # "Value arguments must be bound using FunctionArgument.value"
        if isinstance(actual, TypeArg):
            raise Unbound("%s of %s is a value argument, called with a type" %
                          (where, impl.signature))
        written = declared["value"]
    else:
        # "Type arguments must be bound using FunctionArgument.type"
        if not isinstance(actual, TypeArg):
            raise Unbound("%s of %s is a type argument, called with a value" %
                          (where, impl.signature))
        written, actual = declared["type"], actual.type
    if not isinstance(written, str):
        raise Unsupported("%s of %s is declared as %r, not in the type syntax" %
                          (where, impl.signature, written))
    want = types.parse(written)
    if impl.nullability == "DISCRETE" and want.nullable != actual.nullable:
        raise Unbound("%s of %s is declared %s, called with %s" %
                      (where, impl.signature, types.render_field(want),
                       types.render_field(actual)))
    try:
        _match(want.with_nullable(False), actual.with_nullable(False), bound, outermost=True)
    except Unbound as why:
        raise Unbound("%s of %s: %s" % (where, impl.signature, why))


def _match(want, actual, bound, outermost):
    """Structural match of a declared type against a concrete one, filling `bound` as it goes."""
    if want.name.startswith("any"):
        # `any` accepts anything; `any1`..`any9` must bind to one type per invocation. Inside a
        # compound type `any1?` accepts only a nullable type and binds `any1` to it without the
        # marker: the table in scalar_functions.md, "second arg element type `i32?` matches
        # `any1?`" with `any1` bound to `i32`, and `list<i32>` not matching `list<any1?>`.
        if not outermost and want.nullable and not actual.nullable:
            raise Unbound("declared %s, called with %s" %
                          (types.render_field(want), types.render_field(actual)))
        value = actual.with_nullable(False) if want.nullable else actual
        if want.name != "any":
            previous = bound.get(want.name)
            if previous is not None and previous != value:
                raise Unbound("%s is both %s and %s in one call" %
                              (want.name, types.render_field(previous),
                               types.render_field(value)))
            bound[want.name] = value
        return
    if want.name != actual.name:
        raise Unbound("declared %s, called with %s" % (want.name, actual.name))
    if not outermost and want.nullable != actual.nullable:
        raise Unbound("declared %s, called with %s" %
                      (types.render_field(want), types.render_field(actual)))
    if len(want.params) != len(actual.params):
        raise Unbound("%s takes %d parameters, got %d" %
                      (want.name, len(want.params), len(actual.params)))
    for w, a in zip(want.params, actual.params):
        if isinstance(w, Type):
            _match(w, a, bound, outermost=False)
        elif isinstance(w, str):
            # "the function can only bind if the exact same value is used for all parameters of
            # that name" - scalar_functions.md, Parameterized Types.
            if bound.get(w, a) != a:
                raise Unbound("%s is both %s and %s in one call" % (w, bound[w], a))
            bound[w] = a
        elif w != a:
            raise Unbound("declared %s=%s, called with %s" % (want.name, w, a))


def return_type(impl, args, phase="AGGREGATION_PHASE_INITIAL_TO_RESULT", bound=None):
    """The type a call of this implementation returns, over these concrete argument types.

    For an aggregate or window function the phase selects which declaration is read. The spec names
    the intermediate type as "the intermediate output type that is used" for a decomposable
    function and lists the phases as "what portion of the operation is required"; it does not state
    in one sentence that a call ending at the intermediate step outputs that type. Reading the two
    together is the only way the phases have a type at all, so that reading is applied here and
    recorded in deriver/README.md as a reading rather than as a quotation.

    `bound` is what bind() returned for these arguments, when the caller has it already.
    """
    if bound is None:
        bound = bind(impl, args, phase)
    # MIRROR reads the nullability of the values a call passes. An enumeration argument has none,
    # and a type argument names a type rather than passing a value of it.
    args = [a for a in args if isinstance(a, Type)]
    written = impl.ret
    if phase in ("AGGREGATION_PHASE_INITIAL_TO_INTERMEDIATE",
                 "AGGREGATION_PHASE_INTERMEDIATE_TO_INTERMEDIATE"):
        written = impl.intermediate
        if written is None:
            raise Unsupported("%s is %s decomposable and declares no intermediate type" %
                              (impl.signature, impl.decomposable))
    if written is None:
        raise Unsupported("%s declares no return type" % impl.signature)
    derived = _resolve(written, bound)
    _concrete(derived, impl)
    if impl.nullability == "MIRROR":
        # "if at least one of the input arguments are nullable, the return type is also nullable."
        return derived.with_nullable(any(a.nullable for a in args))
    return derived


def _concrete(t, impl):
    """A derived type must name no wildcard: `LIST?<any>` has no `any` for a call to fill in."""
    if t.name.startswith("any"):
        raise Unsupported("%s returns %s, which no argument binds" % (impl.signature, t.name))
    for p in t.params:
        if isinstance(p, Type):
            _concrete(p, impl)


def _resolve(written, bound):
    """A declared return type: either a type to substitute parameters into, or an expression."""
    text = str(written).strip()
    if "\n" in text or "=" in text or "?" in text and "<" in text:
        return _expression(text, bound)
    return _substitute(types.parse(text), bound)


def _substitute(t, bound):
    """Replace each named parameter of a declared type with what binding gave it."""
    if t.name.startswith("any") and t.name != "any":
        if t.name not in bound:
            raise Unsupported("%s is not bound by any argument" % t.name)
        return bound[t.name].with_nullable(t.nullable or bound[t.name].nullable)
    params = []
    for p in t.params:
        if isinstance(p, Type):
            params.append(_substitute(p, bound))
        elif isinstance(p, str):
            if p not in bound:
                raise Unsupported("parameter %s is not bound by any argument" % p)
            if bound[p] is VARYING:
                raise Unsupported("parameter %s takes different values across an inconsistent "
                                  "variadic argument" % p)
            params.append(bound[p])
        else:
            params.append(p)
    return Type(t.name, params, t.nullable)


def _expression(text, bound):
    """Evaluate a return type expression.

    The language is the one scalar_functions.md lists: integers, booleans and types, with
    `+ - * / min max`, `&& || !`, `< > ==` and an if/then/else written as `a ? b : c`. Lines before
    the last assign names; the last line is the type. Only integer parameters can appear in the
    arithmetic, which is what every derivation in the files this corpus reaches uses.
    """
    env = {k: v for k, v in bound.items() if isinstance(v, int)}
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    for line in lines[:-1]:
        name, _, rhs = line.partition("=")
        if not _:
            raise Unsupported("return expression line %r is neither an assignment nor the type"
                              % line)
        env[name.strip()] = _Eval(rhs, env).value()
    final = types.parse(lines[-1])
    return _substitute_env(final, env, bound)


def _substitute_env(t, env, bound):
    """The last line of a return expression: integer names from the lines above, and `any1`..`any9`
    from binding, as _substitute() fills them in a plain return type."""
    if t.name.startswith("any") and t.name != "any":
        return _substitute(t, bound)
    params = []
    for p in t.params:
        if isinstance(p, Type):
            params.append(_substitute_env(p, env, bound))
        elif isinstance(p, str):
            if p not in env:
                raise Unsupported("%s is not computed by the return expression" % p)
            params.append(env[p])
        else:
            params.append(p)
    return Type(t.name, params, t.nullable)


class _Eval:
    """A recursive-descent reader for one return expression.

    Written out rather than handed to Python's own evaluator: `/` is integer division here and
    `&&`, `||` and `!` are not Python at all, so an expression that happened to parse as Python
    would be evaluated under different rules than the ones the spec lists.
    """
    import re as _re
    TOKEN = _re.compile(r"\s*(\d+|[A-Za-z_][A-Za-z0-9_]*|&&|\|\||==|<=|>=|!=|[-+*/(),?:<>!])")

    def __init__(self, text, env):
        self.text, self.env = text.strip(), env
        self.tokens = self.TOKEN.findall(self.text)
        if "".join(self.tokens) != self._re.sub(r"\s+", "", self.text):
            raise Unsupported("return expression %r" % text)
        self.pos = 0

    def value(self):
        v = self._ternary()
        if self.pos != len(self.tokens):
            raise Unsupported("trailing text in return expression %r" % self.text)
        return v

    def _peek(self):
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def _take(self, expected=None):
        tok = self._peek()
        if tok is None or (expected is not None and tok != expected):
            raise Unsupported("expected %r in return expression %r" % (expected, self.text))
        self.pos += 1
        return tok

    def _ternary(self):
        cond = self._or()
        if self._peek() != "?":
            return cond
        self._take("?")
        yes = self._ternary()
        self._take(":")
        no = self._ternary()
        return yes if cond else no

    def _or(self):
        v = self._and()
        while self._peek() == "||":
            self._take()
            v = self._and() or v
        return v

    def _and(self):
        v = self._compare()
        while self._peek() == "&&":
            self._take()
            v = self._compare() and v
        return v

    def _compare(self):
        v = self._additive()
        while self._peek() in ("<", ">", "==", "<=", ">=", "!="):
            op = self._take()
            r = self._additive()
            v = {"<": v < r, ">": v > r, "==": v == r, "<=": v <= r, ">=": v >= r, "!=": v != r}[op]
        return v

    def _additive(self):
        v = self._multiplicative()
        while self._peek() in ("+", "-"):
            op = self._take()
            r = self._multiplicative()
            v = v + r if op == "+" else v - r
        return v

    def _multiplicative(self):
        v = self._unary()
        while self._peek() in ("*", "/"):
            op = self._take()
            r = self._unary()
            if op == "*":
                v = v * r
            else:
                # The spec declares `divide(integer, integer) => integer` and does not say how a
                # remainder is handled. No derivation this corpus reaches divides, so the choice is
                # unexercised; truncation toward zero is what C-family integer division does.
                if r == 0:
                    raise Unsupported("division by zero in %r" % self.text)
                v = int(v / r)
        return v

    def _unary(self):
        if self._peek() == "!":
            self._take()
            return not self._unary()
        if self._peek() == "-":
            self._take()
            return -self._unary()
        return self._primary()

    def _primary(self):
        tok = self._take()
        if tok == "(":
            v = self._ternary()
            self._take(")")
            return v
        if tok in ("min", "max"):
            self._take("(")
            a = self._ternary()
            self._take(",")
            b = self._ternary()
            self._take(")")
            return min(a, b) if tok == "min" else max(a, b)
        if tok.isdigit():
            return int(tok)
        if tok in ("true", "false"):
            return tok == "true"
        if tok not in self.env:
            raise Unsupported("%s is not a bound parameter in %r" % (tok, self.text))
        return self.env[tok]
