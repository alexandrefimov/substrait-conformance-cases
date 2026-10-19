// Copied into the probe module when protobuf conversions live in the separate codec module.
package main

import (
	"github.com/substrait-io/substrait-go/codec/v9"
	"github.com/substrait-io/substrait-go/v9/extensions"
	"github.com/substrait-io/substrait-go/v9/plan"
	"github.com/substrait-io/substrait-go/v9/types"
	spb "github.com/substrait-io/substrait-protobuf/go/substraitpb"
)

func planFromProto(p *spb.Plan) (*plan.Plan, error) {
	return codec.PlanFromProto(p, extensions.GetDefaultCollectionWithNoError())
}

func namedStructToProto(ns types.NamedStruct) *spb.NamedStruct {
	return codec.NamedStructToProto(ns)
}
