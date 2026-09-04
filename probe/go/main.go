// The substrait-go probe: parses a binary plan and prints the schema derived for its root.
package main

import (
	"fmt"
	"os"
	"strings"

	"github.com/substrait-io/substrait-go/v9/extensions"
	"github.com/substrait-io/substrait-go/v9/plan"
	spb "github.com/substrait-io/substrait-protobuf/go/substraitpb"
	"github.com/substrait-io/substrait-go/v9/types"
	"google.golang.org/protobuf/proto"
)

func render(ns types.NamedStruct) string {
	parts := make([]string, 0, len(ns.Struct.Types))
	for i, t := range ns.Struct.Types {
		name := "?"
		if i < len(ns.Names) {
			name = ns.Names[i]
		}
		// t.String() prints both the type parameters and the "?" of a nullable type, so adding our
		// own marker produced "??". ShortString() will not do here: it drops precision, scale and
		// length, and then every parameterized type looked like a divergence caused by the probe.
		parts = append(parts, fmt.Sprintf("%s:%s", name, t.String()))
	}
	return strings.Join(parts, ", ")
}

func main() {
	data, err := os.ReadFile(os.Args[1])
	if err != nil {
		fmt.Printf("SUBSTRAITGO REJECTED  read: %v\n", err)
		return
	}
	var p spb.Plan
	if err := proto.Unmarshal(data, &p); err != nil {
		fmt.Printf("SUBSTRAITGO REJECTED  unmarshal: %v\n", err)
		return
	}
	pl, err := plan.FromProto(&p, extensions.GetDefaultCollectionWithNoError())
	if err != nil {
		msg := strings.ReplaceAll(err.Error(), "\n", " ")
		if len(msg) > 150 {
			msg = msg[:150]
		}
		fmt.Printf("SUBSTRAITGO REJECTED  %s\n", msg)
		return
	}
	roots := pl.GetRoots()
	if len(roots) == 0 {
		fmt.Println("SUBSTRAITGO REJECTED  plan without a root")
		return
	}
	fmt.Printf("SUBSTRAITGO ACCEPTED  [%s]\n", render(roots[0].RecordType()))
}
