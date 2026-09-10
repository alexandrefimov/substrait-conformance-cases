// The whole relations corpus through substrait-go, as one answer per case.
//
//	relgo probe/relations/go/... <bundle.pb>...
//
// Prints "<case id><TAB><answer>", which probe/relations/column.py turns into a column. One
// process for the whole corpus: substrait-go panics on some plans rather than returning an error
// (substrait-go#328), and a recover keeps that a case's answer instead of the end of the run.
//
// It reads a serialized substrait.test.RelationTestCase with generated protobuf bindings and knows
// nothing else about this repository: no YAML, no authoring parser, no text format. Its own
// Substrait protos are pinned older than the ones the bundle was compiled against, which is the
// point - the contract carries no version-specific content of its own.
//
// substrait-go derives schemas and does not execute, so it answers with a schema and never with
// rows. The 26 cases that declare rows are unanswered on that half, and two of them -
// join_physical/hash_right_semi and hash_right_anti - differ in nothing else; the head of the
// column says so, and probe/relations/check_column.py counts it.
package main

import (
	"fmt"
	"os"
	"strings"

	"github.com/substrait-io/substrait-go/v9/extensions"
	"github.com/substrait-io/substrait-go/v9/plan"
	spb "github.com/substrait-io/substrait-protobuf/go/substraitpb"
	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/reflect/protoreflect"

	rtpb "relationtest/gen"
)

// NULLABILITY_NULLABLE. Read as a number rather than through the generated enum so that this file
// and probe/relations/corpus.py, which reads the same field the same way, cannot drift apart.
const nullable = 1

// The two type names the corpus spells differently from the protobuf field that carries them.
var short = map[string]string{"fixed_char": "fixedchar", "fixed_binary": "fixedbinary"}

// renderType writes a type the way a case is written: `i64`, `i64?`, `decimal<11,2>`.
//
// Deliberately not substrait-go's own Type.String(), which prints `boolean?` where the corpus says
// `bool?`. A column records the answer in the notation the cases use so that two participants'
// columns can be read side by side; translating is the runner's job. Reading the protobuf oneof
// through the descriptor rather than switching on every known kind keeps this the same procedure
// probe/relations/corpus.py follows, so a type neither of them has met is still named and not
// dropped.
func renderType(t *spb.Type) string {
	if t == nil {
		return "?"
	}
	m := t.ProtoReflect()
	fd := m.WhichOneof(m.Descriptor().Oneofs().ByName("kind"))
	if fd == nil {
		return "?"
	}
	sub := m.Get(fd).Message()
	name := string(fd.Name())
	if s, ok := short[name]; ok {
		name = s
	}
	q := ""
	if field(sub, "nullability") == nullable {
		q = "?"
	}
	switch {
	case name == "decimal":
		return fmt.Sprintf("decimal<%d,%d>%s", field(sub, "precision"), field(sub, "scale"), q)
	case has(sub, "length"):
		return fmt.Sprintf("%s<%d>%s", name, field(sub, "length"), q)
	case has(sub, "precision"):
		return fmt.Sprintf("%s<%d>%s", name, field(sub, "precision"), q)
	}
	return name + q
}

func has(m protoreflect.Message, name string) bool {
	return m.Descriptor().Fields().ByName(protoreflect.Name(name)) != nil
}

// field reads a numeric field by name. `nullability` is an enum and the parameters are integers,
// and protoreflect hands the two back through different accessors, so the kind is asked rather
// than assumed - Value.Int() on an enum panics.
func field(m protoreflect.Message, name string) int64 {
	fd := m.Descriptor().Fields().ByName(protoreflect.Name(name))
	if fd == nil {
		return 0
	}
	v := m.Get(fd)
	if fd.Kind() == protoreflect.EnumKind {
		return int64(v.Enum())
	}
	return v.Int()
}

// renderSchema writes `[a:i64, b:i64?]`.
//
// A name without a type and a type without a name are both kept as `?` rather than dropped: a
// participant may return more types than root names or fewer, and substrait-go refuses several
// cases on exactly that mismatch. An answer that quietly shortened itself to the smaller of the
// two counts would hide the disagreement it is there to record.
func renderSchema(ns *spb.NamedStruct) string {
	names := ns.GetNames()
	types := ns.GetStruct().GetTypes()
	n := len(names)
	if len(types) > n {
		n = len(types)
	}
	cols := make([]string, 0, n)
	for i := 0; i < n; i++ {
		name, ty := "?", "?"
		if i < len(names) {
			name = names[i]
		}
		if i < len(types) {
			ty = renderType(types[i])
		}
		cols = append(cols, name+":"+ty)
	}
	return "[" + strings.Join(cols, ", ") + "]"
}

// walk visits every Rel reachable from one, through the descriptor rather than a list of relation
// types. A hand-written switch has to gain an arm for each relation the corpus reaches, and the
// four physical join cases are exactly what it would have missed.
func walk(rel *spb.Rel, visit func(*spb.ReadRel) error) error {
	if rel == nil {
		return nil
	}
	m := rel.ProtoReflect()
	fd := m.WhichOneof(m.Descriptor().Oneofs().ByName("rel_type"))
	if fd == nil {
		return nil
	}
	if read := rel.GetRead(); read != nil {
		if err := visit(read); err != nil {
			return err
		}
	}
	var err error
	m.Get(fd).Message().Range(func(f protoreflect.FieldDescriptor, v protoreflect.Value) bool {
		if f.Kind() != protoreflect.MessageKind || f.Message().FullName() != "substrait.Rel" {
			return true
		}
		visitOne := func(val protoreflect.Value) bool {
			inner, ok := val.Message().Interface().(*spb.Rel)
			if !ok {
				return true
			}
			if e := walk(inner, visit); e != nil {
				err = e
				return false
			}
			return true
		}
		if f.IsList() {
			list := v.List()
			for i := 0; i < list.Len(); i++ {
				if !visitOne(list.Get(i)) {
					return false
				}
			}
			return true
		}
		return visitOne(v)
	})
	return err
}

// bindTables refuses a plan that declares an input schema the case did not bind. An engine
// answering about a different input schema is not answering this case.
func bindTables(tc *rtpb.RelationTestCase) error {
	declared := map[string]*spb.NamedStruct{}
	for _, t := range tc.GetTables() {
		declared[strings.Join(t.GetName(), ".")] = t.GetSchema()
	}
	check := func(read *spb.ReadRel) error {
		nt := read.GetNamedTable()
		if nt == nil {
			return nil
		}
		key := strings.Join(nt.GetNames(), ".")
		want, ok := declared[key]
		if !ok {
			return fmt.Errorf("plan reads table %q, which the case does not bind", key)
		}
		if !proto.Equal(want, read.GetBaseSchema()) {
			return fmt.Errorf("table %q: the fixture schema is not the plan's base_schema", key)
		}
		return nil
	}
	for _, pr := range tc.GetPlan().GetRelations() {
		var err error
		if root := pr.GetRoot(); root != nil {
			err = walk(root.GetInput(), check)
		} else {
			err = walk(pr.GetRel(), check)
		}
		if err != nil {
			return err
		}
	}
	return nil
}

// derive isolates the library call. substrait-go panics on some shapes, and a panic has to be one
// case's answer rather than the end of the run.
func derive(tc *rtpb.RelationTestCase) (pl *plan.Plan, err error) {
	defer func() {
		if r := recover(); r != nil {
			err = fmt.Errorf("CRASH %v", r)
		}
	}()
	return plan.FromProto(tc.GetPlan(), extensions.GetDefaultCollectionWithNoError())
}

// oneLine folds a message onto the single line a column gives it. It is not shortened: the
// substrait-go message that matters most here prints both structs it compared, and a cut at any
// length anyone would pick lands inside the second one - which is the half that says what the
// library wanted. A message carrying machine-local content would be caught by the hygiene check in
// probe/selfcheck.sh, which is the guard a length limit was never going to be.
func oneLine(s string) string {
	return strings.Join(strings.Fields(strings.ReplaceAll(s, "\n", " ")), " ")
}

func answer(tc *rtpb.RelationTestCase) string {
	if err := bindTables(tc); err != nil {
		return "HARNESS-ERROR: " + oneLine(err.Error())
	}
	pl, err := derive(tc)
	if err != nil {
		msg := oneLine(err.Error())
		if strings.HasPrefix(msg, "CRASH ") {
			return "CRASH: " + strings.TrimPrefix(msg, "CRASH ")
		}
		return "ERROR: " + msg
	}
	roots := pl.GetRoots()
	if len(roots) == 0 {
		return "ERROR: the plan has no root relation"
	}
	return renderSchema(roots[0].RecordType().ToProto())
}

func main() {
	for _, path := range os.Args[1:] {
		data, err := os.ReadFile(path)
		if err != nil {
			fmt.Printf("%s\tHARNESS-ERROR: %v\n", path, err)
			continue
		}
		var tc rtpb.RelationTestCase
		if err := proto.Unmarshal(data, &tc); err != nil {
			fmt.Printf("%s\tHARNESS-ERROR: the bundle does not parse: %v\n", path, err)
			continue
		}
		fmt.Printf("%s\t%s\n", tc.GetId(), answer(&tc))
	}
}
