cmake_minimum_required(VERSION 3.20)

project(GWPS
    VERSION 0.1.0
    DESCRIPTION "A private Pre-Searing Ascalon server for Guild Wars"
    LANGUAGES C)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_C_EXTENSIONS ON)

if(NOT CMAKE_BUILD_TYPE AND NOT CMAKE_CONFIGURATION_TYPES)
    set(CMAKE_BUILD_TYPE RelWithDebInfo CACHE STRING "" FORCE)
endif()

set(GWPS_ROOT "${CMAKE_CURRENT_SOURCE_DIR}")
set(OT_SRC_DIR     "${GWPS_ROOT}/code/OpenTyria")

# ---------------------------------------------------------------------------
# Vendored dependencies
# ---------------------------------------------------------------------------

# SQLite amalgamation -- compiled as its own translation unit, exactly like the
# upstream MSVC project does.
add_library(gwps_sqlite STATIC "${OT_SRC_DIR}/sqlite3.c")
target_include_directories(gwps_sqlite PUBLIC "${OT_SRC_DIR}")
target_compile_definitions(gwps_sqlite PRIVATE
    SQLITE_THREADSAFE=1
    SQLITE_DEFAULT_MEMSTATUS=0
    SQLITE_OMIT_DEPRECATED
    SQLITE_OMIT_LOAD_EXTENSION)
if(MSVC)
    target_compile_options(gwps_sqlite PRIVATE /w)
else()
    target_compile_options(gwps_sqlite PRIVATE -w)
endif()

# Mbed TLS (big-number DH + ChaCha20). Use its own CMake build, but strip
# everything we do not need.
set(ENABLE_TESTING           OFF CACHE BOOL "" FORCE)
set(ENABLE_PROGRAMS          OFF CACHE BOOL "" FORCE)
set(MBEDTLS_FATAL_WARNINGS   OFF CACHE BOOL "" FORCE)
set(USE_SHARED_MBEDTLS_LIBRARY OFF CACHE BOOL "" FORCE)
set(USE_STATIC_MBEDTLS_LIBRARY ON  CACHE BOOL "" FORCE)
add_subdirectory("${GWPS_ROOT}/deps/mbedtls-3.6.0" "${CMAKE_BINARY_DIR}/mbedtls" EXCLUDE_FROM_ALL)

# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------
#
# NOTE: OpenTyria is built as a single translation unit -- build_open_tyria.c
# #includes every other .c file in the project. Adding a new source file to the
# project therefore means adding an #include there, NOT adding it here.
# See docs/adr/0002-cmake-build.md and docs/02-scaling-limitations.md section 10.
#
add_executable(gwps_server "${OT_SRC_DIR}/build_open_tyria.c")

target_include_directories(gwps_server PRIVATE
    "${OT_SRC_DIR}"
    "${GWPS_ROOT}/deps/mbedtls-3.6.0/include")

target_link_libraries(gwps_server PRIVATE
    gwps_sqlite
    mbedtls)

if(WIN32)
    # ntdll is required by win32/iocp_win32.c, which calls NtSetInformationFile
    # and RtlNtStatusToDosError directly to cancel pending overlapped I/O.
    target_link_libraries(gwps_server PRIVATE Ws2_32 bcrypt ntdll)
else()
    target_link_libraries(gwps_server PRIVATE pthread m)
endif()

if(MSVC)
    # build_open_tyria.c already sets the important ones; these keep the noise
    # from hiding real problems.
    target_compile_options(gwps_server PRIVATE
        /W3
        /wd4201 /wd4214 /wd4204   # nonstandard struct/union/bitfield extensions
        /wd4996                    # deprecated POSIX names
        /wd4267 /wd4244            # size_t / narrowing conversions (vendored code)
        $<$<CONFIG:Release>:/O2>)
else()
    target_compile_options(gwps_server PRIVATE
        -Wall -Wextra -Wno-unused-parameter -Wno-sign-compare
        -Wno-missing-field-initializers)
endif()

# ---------------------------------------------------------------------------
# Tests target (upstream's COMPILE_TESTS path, tools/tests.c)
# ---------------------------------------------------------------------------
add_executable(gwps_tests EXCLUDE_FROM_ALL "${OT_SRC_DIR}/build_open_tyria.c")
set_target_properties(gwps_tests PROPERTIES OUTPUT_NAME "gwps_tests")
target_compile_definitions(gwps_tests PRIVATE COMPILE_TESTS=1)
target_include_directories(gwps_tests PRIVATE
    "${OT_SRC_DIR}"
    "${GWPS_ROOT}/deps/mbedtls-3.6.0/include")
target_link_libraries(gwps_tests PRIVATE gwps_sqlite mbedtls)
if(WIN32)
    target_link_libraries(gwps_tests PRIVATE Ws2_32 bcrypt ntdll)
else()
    target_link_libraries(gwps_tests PRIVATE pthread m)
endif()
if(MSVC)
    target_compile_options(gwps_tests PRIVATE /w)
else()
    target_compile_options(gwps_tests PRIVATE -w)
endif()

# ---------------------------------------------------------------------------
# Host tool: fingerprint each map blob's navmesh inside Gw.dat
# (tools/gwdat-pathing.c). Same single-translation-unit trick as gwdat_scan.
# ---------------------------------------------------------------------------
add_executable(gwdat_pathing "${GWPS_ROOT}/tools/gwdat-pathing.c")
target_include_directories(gwdat_pathing PRIVATE
    "${OT_SRC_DIR}"
    "${GWPS_ROOT}/deps/mbedtls-3.6.0/include")
target_link_libraries(gwdat_pathing PRIVATE gwps_sqlite mbedtls)
if(WIN32)
    target_link_libraries(gwdat_pathing PRIVATE Ws2_32 bcrypt ntdll)
else()
    target_link_libraries(gwdat_pathing PRIVATE pthread m)
endif()
if(MSVC)
    target_compile_options(gwdat_pathing PRIVATE /W0)
else()
    target_compile_options(gwdat_pathing PRIVATE -w)
endif()

# ---------------------------------------------------------------------------
# gwps_dns -- loopback DNS responder used by the "closed" network mode
# (docs/09-client-connections.md, tools/dns-gwps.ps1).
#
# The client builds its file-server names itself and resolves some of them through a path that
# ignores the hosts file, so answering the lookup is the only way to keep it on this machine.
# Standalone: no part of the server depends on it, and the default install does not run it.
# ---------------------------------------------------------------------------
if(WIN32)
    add_executable(gwps_dns "${GWPS_ROOT}/tools/gwps_dns.c")
    target_link_libraries(gwps_dns PRIVATE Ws2_32)
    if(MSVC)
        target_compile_options(gwps_dns PRIVATE /W3)
    endif()
endif()

# ---------------------------------------------------------------------------
# Host tool: enumerate the map blobs inside Gw.dat (tools/gwdat-scan.c).
# Compiles the whole library with COMPILE_TOOLS so build_open_tyria.c skips
# main.c and the tool supplies its own.
# ---------------------------------------------------------------------------
add_executable(gwdat_scan "${GWPS_ROOT}/tools/gwdat-scan.c")
target_include_directories(gwdat_scan PRIVATE
    "${OT_SRC_DIR}"
    "${GWPS_ROOT}/deps/mbedtls-3.6.0/include")
target_link_libraries(gwdat_scan PRIVATE gwps_sqlite mbedtls)
if(WIN32)
    target_link_libraries(gwdat_scan PRIVATE Ws2_32 bcrypt ntdll)
else()
    target_link_libraries(gwdat_scan PRIVATE pthread m)
endif()
if(MSVC)
    target_compile_options(gwdat_scan PRIVATE /W0)
else()
    target_compile_options(gwdat_scan PRIVATE -w)
endif()

# ---------------------------------------------------------------------------
# portal.dll -- injected into the Guild Wars client to stand in for the real
# ArenaNet portal. Self-contained Windows DLL; required before any client test
# can run (see docs/04-scope.md, prerequisite P4).
# ---------------------------------------------------------------------------
if(WIN32)
    add_library(portal SHARED portal/portal.c)
    set_target_properties(portal PROPERTIES
        OUTPUT_NAME "portal"
        PREFIX "")
    # portal.c defines _CRT_SECURE_NO_WARNINGS itself.
    if(MSVC)
        target_compile_options(portal PRIVATE /W3 /wd4996)
    endif()
    # The resolver hook redirects getaddrinfo, so it needs the socket library and its headers.
    target_link_libraries(portal PRIVATE Ws2_32)
endif()

# ---------------------------------------------------------------------------
# Convenience: run from the source tree so relative paths ("db/database.db",
# "Gw.dat") resolve the way upstream expects.
# ---------------------------------------------------------------------------
add_custom_target(run_server
    COMMAND gwps_server
    WORKING_DIRECTORY "${GWPS_ROOT}"
    DEPENDS gwps_server
    USES_TERMINAL)
