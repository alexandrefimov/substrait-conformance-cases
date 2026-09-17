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

The files themselves are read out of a Substrait checkout at the release the plans declare, not out
of its working tree, so a checkout sitting on a branch cannot quietly change what a rule says. The
bytes are pinned by content in deriver/spec.pins.
"""
import os, subprocess, sys

import yaml

from . import types
from .types import Type, Unsupported

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

    def __init__(self):
        self.by_urn = {}
        self.read = {}
        self._indexed = {}
        self._load()

    def _load(self):
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
            doc = yaml.safe_load(raw)
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
        index, aside = {}, {}
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
        return index, aside

    def lookup(self, urn, compound):
        if urn not in self.by_urn:
            raise Unsupported("no extension file declares urn %r at %s" % (urn, SPEC_REF))
        if urn not in self._indexed:
            self._indexed[urn] = self._index(urn)
        index, aside = self._indexed[urn]
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


def bind(impl, args):
    """Bind concrete argument types to a declaration and return the bound parameters.

    The three nullability modes differ here exactly as scalar_functions.md describes: MIRROR and
    DECLARED_OUTPUT strip the outermost nullability of each argument before matching, DISCRETE
    requires it to match what the signature declares. Nested nullability is never stripped.
    """
    declared = [a for a in impl.args if "value" in a or "type" in a]
    if impl.variadic is not None:
        # The variadic argument is written once in the signature and may repeat in the call. Only
        # the "consistent" form is implemented: each repeat must bind the same way as the first.
        if not declared:
            raise Unsupported("variadic %s with no declared argument" % impl.name)
        declared = declared + [declared[-1]] * max(0, len(args) - len(declared))
    if len(declared) != len(args):
        raise Unsupported("%s takes %d arguments, called with %d" %
                          (impl.signature, len(declared), len(args)))
    bound = {}
    for arg, actual in zip(declared, args):
        want = types.parse(arg.get("value") or arg.get("type"))
        if impl.nullability == "DISCRETE":
            if want.nullable != actual.nullable:
                raise Unsupported("%s wants %s at this position, called with %s" %
                                  (impl.signature, types.render_field(want),
                                   types.render_field(actual)))
            _match(want, actual, bound, outermost=False)
        else:
            _match(want, actual.with_nullable(False), bound, outermost=True)
    return bound


def _match(want, actual, bound, outermost):
    """Structural match of a declared type against a concrete one, filling `bound` as it goes."""
    if want.name.startswith("any"):
        # `any` accepts anything; `any1`..`any9` must bind to one type per invocation.
        if want.name != "any":
            previous = bound.get(want.name)
            if previous is not None and previous != actual:
                raise Unsupported("%s is both %s and %s in one call" %
                                  (want.name, types.render_field(previous),
                                   types.render_field(actual)))
            bound[want.name] = actual
        return
    if want.name != actual.name:
        raise Unsupported("declared %s, called with %s" % (want.name, actual.name))
    if not outermost and want.nullable != actual.nullable:
        raise Unsupported("declared %s, called with %s" %
                          (types.render_field(want), types.render_field(actual)))
    if len(want.params) != len(actual.params):
        raise Unsupported("%s takes %d parameters, got %d" %
                          (want.name, len(want.params), len(actual.params)))
    for w, a in zip(want.params, actual.params):
        if isinstance(w, Type):
            _match(w, a, bound, outermost=False)
        elif isinstance(w, str):
            if bound.get(w, a) != a:
                raise Unsupported("%s is both %s and %s in one call" % (w, bound[w], a))
            bound[w] = a
        elif w != a:
            raise Unsupported("declared %s=%s, called with %s" % (want.name, w, a))


def return_type(impl, args, phase="AGGREGATION_PHASE_INITIAL_TO_RESULT"):
    """The type a call of this implementation returns, over these concrete argument types.

    For an aggregate or window function the phase selects which declaration is read. The spec names
    the intermediate type as "the intermediate output type that is used" for a decomposable
    function and lists the phases as "what portion of the operation is required"; it does not state
    in one sentence that a call ending at the intermediate step outputs that type. Reading the two
    together is the only way the phases have a type at all, so that reading is applied here and
    recorded in deriver/README.md as a reading rather than as a quotation.
    """
    bound = bind(impl, args)
    written = impl.ret
    if phase in ("AGGREGATION_PHASE_INITIAL_TO_INTERMEDIATE",
                 "AGGREGATION_PHASE_INTERMEDIATE_TO_INTERMEDIATE"):
        if impl.decomposable == "NONE":
            raise Unsupported("%s is not decomposable, called with phase %s" %
                              (impl.signature, phase))
        written = impl.intermediate
        if written is None:
            raise Unsupported("%s is %s decomposable and declares no intermediate type" %
                              (impl.signature, impl.decomposable))
    if written is None:
        raise Unsupported("%s declares no return type" % impl.signature)
    derived = _resolve(written, bound)
    if impl.nullability == "MIRROR":
        # "if at least one of the input arguments are nullable, the return type is also nullable."
        return derived.with_nullable(any(a.nullable for a in args))
    return derived


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
    return _substitute_env(final, env)


def _substitute_env(t, env):
    params = []
    for p in t.params:
        if isinstance(p, Type):
            params.append(_substitute_env(p, env))
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
