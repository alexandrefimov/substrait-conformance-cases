// SPDX-License-Identifier: Apache-2.0
// One compiled bundle, independent input vectors, actual Velox execution.
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <map>
#include <stdexcept>
#include <utility>

#include <folly/init/Init.h>
#include <folly/json.h>
#include <glog/logging.h>
#include "compute/ResultIterator.h"
#include "compute/VeloxBackend.h"
#include "config/VeloxConfig.h"
#include "memory/VeloxColumnarBatch.h"
#include "operators/functions/RegistrationAllFunctions.h"
#include "substrait/SubstraitToVeloxPlan.h"
#include "substrait/test/relation_test.pb.h"
#include "velox/exec/tests/utils/AssertQueryBuilder.h"
#include "velox/exec/tests/utils/HiveConnectorTestBase.h"
#include "velox/vector/FlatVector.h"

using namespace facebook::velox;

namespace gluten {
namespace {
using Case = ::substrait::test::RelationTestCase;
using SType = ::substrait::Type;

class HarnessError : public std::runtime_error {
 public:
  using std::runtime_error::runtime_error;
};

void require(bool condition, const std::string& message) {
  if (!condition) {
    throw HarnessError(message);
  }
}

// Deliberately not SubstraitParser: fixture loading must not test Gluten's
// literal or type parser. Start with the three fixture kinds of the row gaps.
TypePtr fixtureType(const SType& type) {
  switch (type.kind_case()) {
    case SType::kI64:
      return BIGINT();
    case SType::kString:
      return VARCHAR();
    case SType::kBool:
      return BOOLEAN();
    default:
      throw HarnessError("fixture type outside i64/string/bool");
  }
}

RowVectorPtr fixture(const Case::InputTable& table, memory::MemoryPool* pool, size_t stream) {
  const auto& schema = table.schema();
  require(schema.names_size() == schema.struct_().types_size(), "fixture name/type arity");
  std::vector<std::string> names;
  for (int c = 0; c < schema.names_size(); ++c) {
    names.push_back("input" + std::to_string(stream) + "_" + std::to_string(c));
  }
  std::vector<TypePtr> types;
  std::vector<VectorPtr> children;
  for (const auto& type : schema.struct_().types()) {
    types.push_back(fixtureType(type));
    children.push_back(BaseVector::create(types.back(), table.rows_size(), pool));
  }
  for (int r = 0; r < table.rows_size(); ++r) {
    require(table.rows(r).fields_size() == children.size(), "fixture row arity");
    for (int c = 0; c < children.size(); ++c) {
      const auto& value = table.rows(r).fields(c);
      const auto& type = schema.struct_().types(c);
      if (value.has_null()) {
        require(value.null().SerializeAsString() == type.SerializeAsString(), "fixture typed null");
        children[c]->setNull(r, true);
      } else if (type.has_i64()) {
        require(value.has_i64(), "fixture i64 literal");
        children[c]->as<FlatVector<int64_t>>()->set(r, value.i64());
      } else if (type.has_string()) {
        require(value.has_string(), "fixture string literal");
        children[c]->as<FlatVector<StringView>>()->set(r, StringView(value.string()));
      } else {
        require(value.has_boolean(), "fixture bool literal");
        children[c]->as<FlatVector<bool>>()->set(r, value.boolean());
      }
    }
  }
  // Even an empty table supplies one zero-row batch with its schema.
  return std::make_shared<RowVector>(
      pool, ROW(std::move(names), std::move(types)), nullptr, table.rows_size(), std::move(children));
}

class FixtureIterator : public ColumnarBatchIterator {
 public:
  explicit FixtureIterator(RowVectorPtr vector) : vector_(std::move(vector)) {}
  std::shared_ptr<ColumnarBatch> next() override {
    if (!vector_) {
      return nullptr;
    }
    return std::make_shared<VeloxColumnarBatch>(std::exchange(vector_, nullptr));
  }

 private:
  RowVectorPtr vector_;
};

using Key = std::vector<std::string>;

void bindReads(
    google::protobuf::Message* message,
    const std::map<Key, const Case::InputTable*>& tables,
    std::vector<std::shared_ptr<ResultIterator>>& inputs,
    memory::MemoryPool* pool,
    folly::dynamic& relations) {
  if (message->GetDescriptor()->full_name() == "substrait.Rel") {
    auto* oneof = message->GetDescriptor()->FindOneofByName("rel_type");
    auto* field = message->GetReflection()->GetOneofFieldDescriptor(*message, oneof);
    relations.push_back(field ? field->name() : "<unset>");
  }
  if (message->GetDescriptor()->full_name() == "substrait.ReadRel") {
    auto* read = static_cast<::substrait::ReadRel*>(message);
    require(read->has_named_table(), "read source outside named_table");
    // Query-trace ValuesNode bypasses ReadRel filters/projections. Refuse them
    // rather than report a result from a program we did not execute.
    std::vector<const google::protobuf::FieldDescriptor*> fields;
    read->GetReflection()->ListFields(*read, &fields);
    for (auto* field : fields) {
      require(
          field->name() == "named_table" || field->name() == "base_schema" || field->name() == "common",
          "read field cannot survive fixture binding: " + field->name());
    }
    if (read->has_common()) {
      fields.clear();
      read->common().GetReflection()->ListFields(read->common(), &fields);
      for (auto* field : fields) {
        require(field->name() == "direct", "read common outside direct");
      }
    }
    Key name(read->named_table().names().begin(), read->named_table().names().end());
    auto found = tables.find(name);
    require(found != tables.end(), "read has no fixture");
    require(
        read->base_schema().SerializeAsString() == found->second->schema().SerializeAsString(),
        "read and fixture schemas differ");
    const auto index = inputs.size();
    auto vector = fixture(*found->second, pool, index);
    inputs.push_back(std::make_shared<ResultIterator>(std::make_unique<FixtureIterator>(vector)));
    read->clear_named_table();
    read->mutable_local_files()->add_items()->set_uri_file("iterator:" + std::to_string(index));
    return;
  }
  auto* reflection = message->GetReflection();
  std::vector<const google::protobuf::FieldDescriptor*> fields;
  reflection->ListFields(*message, &fields);
  for (auto* field : fields) {
    if (field->cpp_type() != google::protobuf::FieldDescriptor::CPPTYPE_MESSAGE) {
      continue;
    }
    if (field->is_repeated()) {
      for (int i = 0; i < reflection->FieldSize(*message, field); ++i) {
        bindReads(reflection->MutableRepeatedMessage(message, field, i), tables, inputs, pool, relations);
      }
    } else {
      bindReads(reflection->MutableMessage(message, field), tables, inputs, pool, relations);
    }
  }
}
} // namespace

class RelationsProbeTest : public exec::test::HiveConnectorTestBase {
 protected:
  static void SetUpTestCase() {
    VeloxBackend::create(AllocationListener::noop(), {});
    exec::test::HiveConnectorTestBase::SetUpTestCase();
    // The base registers Presto functions. Restore Gluten's Spark semantics.
    registerAllFunctions();
  }

  static void TearDownTestCase() {
    exec::test::HiveConnectorTestBase::TearDownTestCase();
    VeloxBackend::get()->tearDown();
  }
};

TEST_F(RelationsProbeTest, bundle) {
  const char* path = std::getenv("GLUTEN_RELATION_BUNDLE");
  if (path == nullptr) {
    GTEST_SKIP() << "GLUTEN_RELATION_BUNDLE not set";
  }
  folly::dynamic output = folly::dynamic::object("status", "HARNESS-ERROR");
  try {
    Case test;
    std::ifstream input(path, std::ios::binary);
    require(input.good(), "cannot open request bundle");
    const bool parsed = test.ParseFromIstream(&input);
    output["id"] = test.id();
    if (!parsed) {
      output["status"] = "ERROR";
      throw std::runtime_error("cannot decode bundle with consumer Substrait bindings");
    }
    require(!test.id().empty() && test.has_plan(), "bundle identity/plan missing");
    require(!test.has_expect(), "consumer request must contain no expectation");
    std::map<Key, const Case::InputTable*> tables;
    for (const auto& table : test.tables()) {
      require(!table.name().empty(), "fixture name missing");
      Key key(table.name().begin(), table.name().end());
      require(tables.emplace(key, &table).second, "duplicate fixture name");
    }
    auto plan = test.plan();
    std::vector<std::shared_ptr<ResultIterator>> inputs;
    output["native_relations"] = folly::dynamic::array();
    bindReads(&plan, tables, inputs, pool(), output["native_relations"]);
    output["input_streams"] = inputs.size();
    const auto config = std::make_shared<config::ConfigBase>(
        std::unordered_map<std::string, std::string>{{kQueryTraceEnabled, "true"}});
    // A private temporary write directory is supplied by the driver.
    const char* writeDir = std::getenv("GLUTEN_RELATION_WRITE_DIR");
    require(writeDir != nullptr, "private write directory missing");
    SubstraitToVeloxPlanConverter converter(
        pool(), config.get(), inputs,
        VeloxConnectorIds{.hive = exec::test::kHiveConnectorId},
        std::string(writeDir), std::string("part.parquet"));
    output["status"] = "ERROR";
    auto node = converter.toVeloxPlan(plan);
    output["schema"] = node->outputType()->toString();
    output["arity"] = node->outputType()->size();
    auto rows = exec::test::AssertQueryBuilder(node).maxDrivers(1).copyResults(pool());
    output["rows"] = folly::dynamic::array();
    if (rows) {
      require(rows->childrenSize() == node->outputType()->size(), "executed result arity");
      for (vector_size_t r = 0; r < rows->size(); ++r) {
        folly::dynamic values = folly::dynamic::array();
        for (int c = 0; c < rows->childrenSize(); ++c) {
          auto child = rows->childAt(c);
          values.push_back(child->isNullAt(r) ? folly::dynamic(nullptr) : folly::dynamic(child->toString(r)));
        }
        output["rows"].push_back(std::move(values));
      }
    }
    output["status"] = "OK";
  } catch (const HarnessError& error) {
    output["status"] = "HARNESS-ERROR";
    output["message"] = error.what();
  } catch (const VeloxException& error) {
    output["message"] = error.message();
  } catch (const std::exception& error) {
    std::string message(error.what());
    auto stack = message.find("Retriable:");
    if (stack != std::string::npos) {
      message.resize(stack);
    }
    output["message"] = message;
  }
  std::cout << "RELATION_RESULT " << folly::toJson(output) << std::endl;
}
} // namespace gluten

int main(int argc, char** argv) {
  ::testing::InitGoogleTest(&argc, argv);
  folly::Init init(&argc, &argv, false);
  // VeloxBackend initializes glog itself. Folly singletons remain initialized.
  google::ShutdownGoogleLogging();
  return RUN_ALL_TESTS();
}
