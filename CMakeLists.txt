cmake_minimum_required(VERSION 3.20)

project(PreSearing
    VERSION 0.1.0
    DESCRIPTION "A private Pre-Searing Ascalon server for Guild Wars"
    LANGUAGES C)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_C_EXTENSIONS ON)

if(NOT CMAKE_BUILD_TYPE AND NOT CMAKE_CONFIGURATION_TYPES)
    set(CMAKE_BUILD_TYPE RelWithDebInfo CACHE STRING "" FORCE)
endif()

set(PRESEARING_ROOT "${CMAKE_CURRENT_SOURCE_DIR}")
set(OT_SRC_DIR     "${PRESEARING_ROOT}/code/OpenTyria")

# ---------------------------------------------------------------------------
# Vendored dependencies
# ---------------------------------------------------------------------------

# SQLite amalgamation -- compiled as its own translation unit, exactly like the
# upstream MSVC project does.
add_library(presearing_sqlite STATIC "${OT_SRC_DIR}/sqlite3.c")
target_include_directories(presearing_sqlite PUBLIC "${OT_SRC_DIR}")
target_compile_definitions(presearing_sqlite PRIVATE
    SQLITE_THREADSAFE=1
    SQLITE_DEFAULT_MEMSTATUS=0
    SQLITE_OMIT_DEPRECATED
    SQLITE_OMIT_LOAD_EXTENSION)
if(MSVC)
    target_compile_options(presearing_sqlite PRIVATE /w)
else()
    target_compile_options(presearing_sqlite PRIVATE -w)
endif()

# Mbed TLS (big-number DH + ChaCha20). Use its own CMake build, but strip
# everything we do not need.
set(ENABLE_TESTING           OFF CACHE BOOL "" FORCE)
set(ENABLE_PROGRAMS          OFF CACHE BOOL "" FORCE)
set(MBEDTLS_FATAL_WARNINGS   OFF CACHE BOOL "" FORCE)
set(USE_SHARED_MBEDTLS_LIBRARY OFF CACHE BOOL "" FORCE)
set(USE_STATIC_MBEDTLS_LIBRARY ON  CACHE BOOL "" FORCE)
add_subdirectory("${PRESEARING_ROOT}/deps/mbedtls-3.6.0" "${CMAKE_BINARY_DIR}/mbedtls" EXCLUDE_FROM_ALL)

# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------
#
# NOTE: OpenTyria is built as a single translation unit -- build_open_tyria.c
# #includes every other .c file in the project. Adding a new source file to the
# project therefore means adding an #include there, NOT adding it here.
# See docs/adr/0002-cmake-build.md and docs/02-scaling-limitations.md section 10.
#
add_executable(presearing_server "${OT_SRC_DIR}/build_open_tyria.c")

target_include_directories(presearing_server PRIVATE
    "${OT_SRC_DIR}"
    "${PRESEARING_ROOT}/deps/mbedtls-3.6.0/include")

target_link_libraries(presearing_server PRIVATE
    presearing_sqlite
    mbedtls)

if(WIN32)
    # ntdll is required by win32/iocp_win32.c, which calls NtSetInformationFile
    # and RtlNtStatusToDosError directly to cancel pending overlapped I/O.
    target_link_libraries(presearing_server PRIVATE Ws2_32 bcrypt ntdll)
else()
    target_link_libraries(presearing_server PRIVATE pthread m)
endif()

if(MSVC)
    # build_open_tyria.c already sets the important ones; these keep the noise
    # from hiding real problems.
    target_compile_options(presearing_server PRIVATE
        /W3
        /wd4201 /wd4214 /wd4204   # nonstandard struct/union/bitfield extensions
        /wd4996                    # deprecated POSIX names
        /wd4267 /wd4244            # size_t / narrowing conversions (vendored code)
        $<$<CONFIG:Release>:/O2>)
else()
    target_compile_options(presearing_server PRIVATE
        -Wall -Wextra -Wno-unused-parameter -Wno-sign-compare
        -Wno-missing-field-initializers)
endif()

# ---------------------------------------------------------------------------
# Tests target (upstream's COMPILE_TESTS path, tools/tests.c)
# ---------------------------------------------------------------------------
add_executable(presearing_tests EXCLUDE_FROM_ALL "${OT_SRC_DIR}/build_open_tyria.c")
set_target_properties(presearing_tests PROPERTIES OUTPUT_NAME "presearing_tests")
target_compile_definitions(presearing_tests PRIVATE COMPILE_TESTS=1)
target_include_directories(presearing_tests PRIVATE
    "${OT_SRC_DIR}"
    "${PRESEARING_ROOT}/deps/mbedtls-3.6.0/include")
target_link_libraries(presearing_tests PRIVATE presearing_sqlite mbedtls)
if(WIN32)
    target_link_libraries(presearing_tests PRIVATE Ws2_32 bcrypt ntdll)
else()
    target_link_libraries(presearing_tests PRIVATE pthread m)
endif()
if(MSVC)
    target_compile_options(presearing_tests PRIVATE /w)
else()
    target_compile_options(presearing_tests PRIVATE -w)
endif()

# ---------------------------------------------------------------------------
# Convenience: run from the source tree so relative paths ("db/database.db",
# "Gw.dat") resolve the way upstream expects.
# ---------------------------------------------------------------------------
add_custom_target(run_server
    COMMAND presearing_server
    WORKING_DIRECTORY "${PRESEARING_ROOT}"
    DEPENDS presearing_server
    USES_TERMINAL)
