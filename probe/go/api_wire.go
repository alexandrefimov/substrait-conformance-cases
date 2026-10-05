// Copied into the probe module when protobuf conversions live in wire.
package main

import (
	"github.com/substrait-io/substrait-go/v9/extensions"
	"github.com/substrait-io/substrait-go/v9/plan"
	"github.com/substrait-io/substrait-go/v9/types"
	"github.com/substrait-io/substrait-go/v9/wire"
	spb "github.com/substrait-io/substrait-protobuf/go/substraitpb"
)

func planFromProto(p *spb.Plan) (*plan.Plan, error) {
	return wire.PlanFromProto(p, extensions.GetDefaultCollectionWithNoError())
}

func namedStructToProto(ns types.NamedStruct) *spb.NamedStruct {
	return wire.NamedStructToProto(ns)
}
