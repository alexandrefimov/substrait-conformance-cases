# SPDX-License-Identifier: Apache-2.0

set(CORPUS_ROOT "${CMAKE_CURRENT_LIST_DIR}/../../..")
set(PROTO_ROOT "${GLUTEN_HOME}/gluten-substrait/src/main/resources/substrait/proto")
set(PROBE_PROTO "${CMAKE_BINARY_DIR}/relations-probe/proto")
file(MAKE_DIRECTORY "${PROBE_PROTO}/substrait/test")
add_custom_command(
  OUTPUT "${PROBE_PROTO}/substrait/test/relation_test.pb.cc"
         "${PROBE_PROTO}/substrait/test/relation_test.pb.h"
  COMMAND "${Protobuf_PROTOC_EXECUTABLE}"
          "--proto_path=${CORPUS_ROOT}/proto" "--proto_path=${PROTO_ROOT}"
          "--cpp_out=${PROBE_PROTO}"
          "${CORPUS_ROOT}/proto/substrait/test/relation_test.proto"
  DEPENDS "${CORPUS_ROOT}/proto/substrait/test/relation_test.proto"
  VERBATIM)
add_executable(gluten_relations_probe
  "${CMAKE_CURRENT_LIST_DIR}/RelationsProbeTest.cc"
  "${PROBE_PROTO}/substrait/test/relation_test.pb.cc")
target_include_directories(gluten_relations_probe PRIVATE
  "${PROBE_PROTO}" "${GLUTEN_HOME}/cpp/core" "${GLUTEN_HOME}/cpp/velox")
target_link_libraries(gluten_relations_probe PRIVATE
  velox ${GLUTEN_ROARING_LINK_LIBRARY} GTest::gtest)

set_target_properties(gluten_relations_probe PROPERTIES
  RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/relations-probe")
