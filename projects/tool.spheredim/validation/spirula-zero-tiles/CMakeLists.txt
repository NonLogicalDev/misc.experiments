cmake_minimum_required(VERSION 3.20)
project(spirula_zero_tiles LANGUAGES CXX)
set(CMAKE_CXX_STANDARD 17)
set(SPIRULA_SOURCE "" CACHE PATH "Pinned Spirula source")
set(MOLTENVK_ROOT "" CACHE PATH "Pinned MoltenVK package")
set(I18N_LIBRARY "" CACHE FILEPATH "Spirula i18n library")
set(SPIRV_EMBED "" CACHE FILEPATH "Generated single-entry SPIR-V registry")
if(NOT SPIRULA_SOURCE OR NOT MOLTENVK_ROOT OR NOT I18N_LIBRARY OR NOT SPIRV_EMBED)
  message(FATAL_ERROR "Set SPIRULA_SOURCE, MOLTENVK_ROOT, I18N_LIBRARY and SPIRV_EMBED")
endif()
set(SRC "${SPIRULA_SOURCE}/src")
add_executable(spirula_zero_tiles harness.cpp "${SPIRV_EMBED}"
  "${SRC}/backend/vulkan/DispatchBudget.cpp"
  "${SRC}/backend/vulkan/SortScanVulkan.cpp"
  "${SRC}/backend/vulkan/VulkanContext.cpp"
  "${SRC}/backend/vulkan/VulkanPipelines.cpp"
  "${SRC}/backend/vulkan/VulkanRuntime.cpp")
target_include_directories(spirula_zero_tiles PRIVATE "${SRC}" "${MOLTENVK_ROOT}/MoltenVK/include")
target_compile_definitions(spirula_zero_tiles PRIVATE SS_BACKEND_VULKAN)
target_link_libraries(spirula_zero_tiles PRIVATE "${MOLTENVK_ROOT}/MoltenVK/static/MoltenVK.xcframework/macos-arm64_x86_64/libMoltenVK.a" "${I18N_LIBRARY}" "-framework Metal" "-framework Foundation" "-framework QuartzCore" "-framework IOSurface" "-framework IOKit" "-framework CoreGraphics" "-framework AppKit" "-framework CoreFoundation")
