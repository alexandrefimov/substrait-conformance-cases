# SPDX-License-Identifier: Apache-2.0

if(NOT CMAKE_CURRENT_SOURCE_DIR STREQUAL CMAKE_SOURCE_DIR)
  return()
endif()

# CMake 3.19+: defer until Gluten has declared its native and test targets.
function(add_gluten_relations_probe)
  include("${CMAKE_CURRENT_FUNCTION_LIST_DIR}/CMakeLists.txt")
endfunction()
cmake_language(DEFER CALL add_gluten_relations_probe)
