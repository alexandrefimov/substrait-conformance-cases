/*
 * The Substrait corpus through Gluten: protobuf-JSON plan -> Velox plan -> derived type.
 * It goes into cpp/velox/tests and builds as an ordinary velox test: JsonToProtoConverter lives
 * there too and is only built with --build_tests=ON.
 *
 * The case directory is given by SUBSTRAIT_CORPUS_DIR. The cases must have virtual tables at their
 * leaves: SubstraitToVeloxPlan does not read named_table.
 */
#include "JsonToProtoConverter.h"

#include <algorithm>
#include <cstdlib>
#include <filesystem>
#include <iostream>
#include <vector>

#include "compute/VeloxPlanConverter.h"
#include "substrait/SubstraitToVeloxPlan.h"
#include "velox/exec/tests/utils/HiveConnectorTestBase.h"
#include "velox/type/Type.h"

using namespace facebook::velox;

namespace gluten {

class SubstraitCorpusProbeTest : public exec::test::HiveConnectorTestBase {
 protected:
  std::shared_ptr<facebook::velox::config::ConfigBase> veloxCfg_ =
      std::make_shared<facebook::velox::config::ConfigBase>(
          std::unordered_map<std::string, std::string>());

  std::shared_ptr<VeloxPlanConverter> makeConverter() {
    return std::make_shared<VeloxPlanConverter>(
        pool(),
        veloxCfg_.get(),
        std::vector<std::shared_ptr<ResultIterator>>{},
        VeloxConnectorIds{.hive = facebook::velox::exec::test::kHiveConnectorId});
  }
};

TEST_F(SubstraitCorpusProbeTest, corpus) {
  const char* dir = std::getenv("SUBSTRAIT_CORPUS_DIR");
  ASSERT_NE(dir, nullptr) << "SUBSTRAIT_CORPUS_DIR is not set";

  std::vector<std::filesystem::path> files;
  for (const auto& entry : std::filesystem::directory_iterator(dir)) {
    if (entry.path().extension() == ".json") {
      files.push_back(entry.path());
    }
  }
  std::sort(files.begin(), files.end());

  for (const auto& file : files) {
    const std::string name = file.stem().string();
    std::string out;
    try {
      ::substrait::Plan plan;
      JsonToProtoConverter::readFromFile(file.string(), plan);
      // The splitInfoIdx_ < splitInfos_.size() check comes before the virtual_table branch, so even
      // a virtual table needs a split info entry. Adding a few spare ones.
      std::vector<::substrait::ReadRel_LocalFiles> splits(16);
      auto node = makeConverter()->toVeloxPlan(plan, splits);
      out = node->outputType()->toString();
    } catch (const std::exception& e) {
      out = std::string("ERROR: ") + e.what();
    }
    std::replace(out.begin(), out.end(), '\n', ' ');
    std::cout << "CASE " << name << " | " << out << std::endl;
  }
}

} // namespace gluten
