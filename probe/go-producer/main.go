// What substrait-go COMPUTES as a function's return type: it resolves the variant from the
// extension declaration and works the output type out itself (NewScalarFunc -> resolveVariant).
package main

import (
	"fmt"

	"github.com/substrait-io/substrait-go/v9/expr"
	"github.com/substrait-io/substrait-go/v9/extensions"
	"github.com/substrait-io/substrait-go/v9/types"
)

func dec(p, s int32) types.Type {
	return &types.DecimalType{Precision: p, Scale: s, Nullability: types.NullabilityRequired}
}

func main() {
	c := extensions.GetDefaultCollectionWithNoError()
	reg := expr.NewExtensionRegistry(extensions.NewSet(), c)
	urn := "extension:io.substrait:functions_arithmetic_decimal"
	cases := []struct {
		name string
		fn   string
		a, b types.Type
	}{
		{"dec(10,2) + dec(5,1)", "add:dec_dec", dec(10, 2), dec(5, 1)},
		{"dec(38,10) + dec(38,10)", "add:dec_dec", dec(38, 10), dec(38, 10)},
		{"dec(38,10) * dec(38,10)", "multiply:dec_dec", dec(38, 10), dec(38, 10)},
		{"dec(10,2) / dec(5,1)", "divide:dec_dec", dec(10, 2), dec(5, 1)},
		{"dec(20,5) + dec(10,8)", "add:dec_dec", dec(20, 5), dec(10, 8)},
		{"dec(30,20) * dec(30,20)", "multiply:dec_dec", dec(30, 20), dec(30, 20)},
	}
	for _, tc := range cases {
		id := extensions.FunctionID{URN: urn, Name: tc.fn}
		r0, e0 := expr.NewRootFieldRefFromType(expr.NewStructFieldRef(0), tc.a)
		r1, e1 := expr.NewRootFieldRefFromType(expr.NewStructFieldRef(1), tc.b)
		if e0 != nil || e1 != nil {
			fmt.Printf("%-26s field references: %v %v\n", tc.name, e0, e1)
			continue
		}
		f2, err2 := expr.NewScalarFunc(reg, id, nil, r0, r1)
		if err2 != nil {
			fmt.Printf("%-26s ERROR: %v\n", tc.name, err2)
			continue
		}
		fmt.Printf("%-26s %s -> %s\n", tc.name, tc.fn, f2.GetType().String())
	}
}
