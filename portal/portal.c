#define _CRT_SECURE_NO_WARNINGS

#include <stdint.h>
#include <stdbool.h>
#include <stdio.h>
#include <inttypes.h>
#include <stdarg.h>
#include <string.h>
#include <ctype.h>

// winsock2.h must precede windows.h, otherwise Windows.h pulls in the old winsock.h and the
// socket types are defined twice.
#include <WinSock2.h>
#include <WS2tcpip.h>
#include <Windows.h>

#define UUID_NODE_LEN   6

#define DllExport __declspec(dllexport)

// ---------------------------------------------------------------------------
// Redirect the client's own resolution of ArenaNet hostnames to loopback.
//
// WHY THIS EXISTS
// The client reaches several file servers over raw TCP 6112 and builds those hostnames itself
// (P:\Code\Net\FileCli\FcSrv.cpp), resolving them through DNS. That is why every other
// approach failed, all measured rather than guessed:
//   - rewriting the hostname strings in the exe changed no connection at all;
//   - a hosts entry caught one file check but not the ones resolved through DNS;
//   - the domain suffix cannot be redirected (the names stop resolving) and Windows does not
//     resolve invented names such as File1.localhost.
//
// This DLL is loaded into the client process -- proof: the portal user id it returns is the
// hardcoded UUID that appears in the auth flow -- so it can answer the lookup at the source.
// No hosts file, no DNS service, nothing machine-wide, and a retail client is unaffected.
//
// The hook delegates to the real getaddrinfo with "127.0.0.1" instead of hand-building the
// result, so what the client later frees is the structure the runtime allocated.

#define HOOK_LOG_ENV "GWPS_PORTAL_HOOK_LOG"

typedef int (WSAAPI * getaddrinfo_fn)(PCSTR, PCSTR, const ADDRINFOA *, PADDRINFOA *);

static getaddrinfo_fn s_real_getaddrinfo;

static void HookLog(const char *fmt, ...)
{
    char path[MAX_PATH + 32];
    const char *env = getenv(HOOK_LOG_ENV);
    if (env != NULL && env[0] != '\0') {
        snprintf(path, sizeof(path), "%s", env);
    } else {
        char tmp[MAX_PATH];
        DWORD n = GetTempPathA(sizeof(tmp), tmp);
        if (n == 0 || n >= sizeof(tmp)) return;
        snprintf(path, sizeof(path), "%sgwps-portal-hook.log", tmp);
    }

    FILE *f = fopen(path, "a");
    if (f == NULL) return;

    va_list args;
    va_start(args, fmt);
    SYSTEMTIME st;
    GetLocalTime(&st);
    fprintf(f, "%02u:%02u:%02u.%03u ", st.wHour, st.wMinute, st.wSecond, st.wMilliseconds);
    vfprintf(f, fmt, args);
    fputc('\n', f);
    va_end(args);
    fclose(f);
}

//: Does this hostname belong to ArenaNet's infrastructure?
static bool HostIsRedirected(const char *node)
{
    static const char *suffixes[] = {
        "arenanetworks.com",
        "ncplatform.net",
    };

    if (node == NULL || node[0] == '\0') return false;

    size_t len = strlen(node);
    for (size_t s = 0; s < sizeof(suffixes) / sizeof(suffixes[0]); ++s) {
        size_t slen = strlen(suffixes[s]);
        if (len < slen) continue;

        bool match = true;
        for (size_t i = 0; i < slen; ++i) {
            if (tolower((unsigned char) node[len - slen + i]) != suffixes[s][i]) {
                match = false;
                break;
            }
        }
        if (match) return true;
    }

    return false;
}

static int WSAAPI Hook_getaddrinfo(PCSTR node, PCSTR service, const ADDRINFOA *hints, PADDRINFOA *res)
{
    if (HostIsRedirected(node)) {
        HookLog("getaddrinfo(\"%s\") -> 127.0.0.1", node);
        // The real function, pointed at loopback: it allocates, so freeaddrinfo stays correct.
        return s_real_getaddrinfo("127.0.0.1", service, hints, res);
    }
    return s_real_getaddrinfo(node, service, hints, res);
}

static void PatchImportSlot(uintptr_t *slot, void *replacement)
{
    DWORD old = 0;
    if (VirtualProtect(slot, sizeof(*slot), PAGE_READWRITE, &old)) {
        *slot = (uintptr_t) replacement;
        VirtualProtect(slot, sizeof(*slot), old, &old);
    }
}

//: Hook getaddrinfo in the main module's import table, and report what else resolves names.
static void InstallResolverHook(void)
{
    HMODULE base = GetModuleHandleA(NULL);
    if (base == NULL) return;

    IMAGE_DOS_HEADER *dos = (IMAGE_DOS_HEADER *) base;
    if (dos->e_magic != IMAGE_DOS_SIGNATURE) return;
    IMAGE_NT_HEADERS *nt = (IMAGE_NT_HEADERS *) ((BYTE *) base + dos->e_lfanew);
    if (nt->Signature != IMAGE_NT_SIGNATURE) return;

    IMAGE_DATA_DIRECTORY dir = nt->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_IMPORT];
    if (dir.VirtualAddress == 0 || dir.Size == 0) return;

    unsigned hooked = 0;
    IMAGE_IMPORT_DESCRIPTOR *imp = (IMAGE_IMPORT_DESCRIPTOR *) ((BYTE *) base + dir.VirtualAddress);
    for (; imp->Name != 0; ++imp) {
        const char *dll = (const char *) ((BYTE *) base + imp->Name);
        IMAGE_THUNK_DATA *orig = (IMAGE_THUNK_DATA *) ((BYTE *) base +
            (imp->OriginalFirstThunk != 0 ? imp->OriginalFirstThunk : imp->FirstThunk));
        IMAGE_THUNK_DATA *iat = (IMAGE_THUNK_DATA *) ((BYTE *) base + imp->FirstThunk);

        for (size_t i = 0; orig[i].u1.AddressOfData != 0; ++i) {
            if (IMAGE_SNAP_BY_ORDINAL(orig[i].u1.Ordinal)) continue;
            IMAGE_IMPORT_BY_NAME *name = (IMAGE_IMPORT_BY_NAME *) ((BYTE *) base + orig[i].u1.AddressOfData);
            const char *fname = (const char *) name->Name;

            // Report every name-related import once: if the client uses a resolver other than
            // getaddrinfo (GetAddrInfoW, DnsQuery_A/W), this log says so instead of leaving us
            // to wonder why the hook never fired.
            if (strstr(fname, "addr") != NULL || strstr(fname, "Addr") != NULL ||
                strstr(fname, "DnsQuery") != NULL || strstr(fname, "gethostbyname") != NULL) {
                HookLog("import %s!%s", dll, fname);
            }

            if (strcmp(fname, "getaddrinfo") == 0) {
                s_real_getaddrinfo = (getaddrinfo_fn) (uintptr_t) iat[i].u1.Function;
                PatchImportSlot((uintptr_t *) &iat[i].u1.Function, (void *) Hook_getaddrinfo);
                ++hooked;
            }
        }
    }

    HookLog("resolver hook installed: %u getaddrinfo slot(s) patched", hooked);
}

struct uuid {
    uint32_t time_low;
    uint16_t time_mid;
    uint16_t time_hi_and_version;
    uint8_t  clock_seq_hi_and_reserved;
    uint8_t  clock_seq_low;
    uint8_t  node[UUID_NODE_LEN];
};

typedef void (*OnPortalNotify_t)(uint32_t msgid, uint32_t size, void *data, void *param);
OnPortalNotify_t g_NotifyCb;
void* g_Param;

struct uuid g_UserId;
struct uuid g_SessionId;

static bool s_parse_uuid(struct uuid *result, const char *ptr)
{
    size_t len = strlen(ptr);
    // This check means that the `sscanf` is safe.
    if (len != sizeof("AABBCCDD-AABB-AABB-AABB-AABBCCDDEEFF") - 1) {
        return false;
    }

    int ret = sscanf(
        ptr,
        "%08" SCNx32 "-%04" SCNx16 "-%04" SCNx16 "-%02hhx%02hhx-%02hhx%02hhx%02hhx%02hhx%02hhx%02hhx",
        &result->time_low, &result->time_mid, &result->time_hi_and_version,
        &result->clock_seq_hi_and_reserved, &result->clock_seq_low, &result->node[0],
        &result->node[1], &result->node[2], &result->node[3], &result->node[4], &result->node[5]);

    if (ret != 11)
        return false;

    return true;
}

DllExport void PortalInitialize(uint32_t port)
{
    (void)port;
    s_parse_uuid(&g_UserId, "fa520ee2-4419-4eb4-ae49-6e9abe6ef24f");
    s_parse_uuid(&g_SessionId, "d8b9bf5d-90b1-4cbd-9b76-88da7be763b6");
}

DllExport void PortalInitializeWithParams(uint32_t one, uint32_t maybe_version, uint32_t zero, uint32_t port, const wchar_t *client_name)
{
}

DllExport void PortalStartCleanup()
{
}

DllExport void PortalLoginSecondaryAuth(const wchar_t* code)
{
    (void)code;
}

DllExport void PortalDestroy(void)
{
}

DllExport void PortalRegisterNotify(OnPortalNotify_t cb, void *param)
{
    g_NotifyCb = cb;
    g_Param = param;
}

DllExport void PortalLogin(const wchar_t *email, const wchar_t *password, const wchar_t *region)
{
    typedef struct Message {
        uint32_t error;
        uint32_t h0004;
    } Message;

    if (wcscmp(email, L"user1@example.com") == 0) {
        s_parse_uuid(&g_UserId, "fa520ee2-4419-4eb4-ae49-6e9abe6ef24f");
        s_parse_uuid(&g_SessionId, "d8b9bf5d-90b1-4cbd-9b76-88da7be763b6");
    } else if (wcscmp(email, L"user2@example.com") == 0) {
        s_parse_uuid(&g_UserId, "5fb222bc-9d19-4308-ac3e-3c62685bc6ae");
        s_parse_uuid(&g_SessionId, "224aee30-d8a5-4f18-ad8e-b5fcbf121c4e");
    } else if (wcscmp(email, L"user3@example.com") == 0) {
        s_parse_uuid(&g_UserId, "9957c79c-b93c-4b60-9d84-9f38a1f62be3");
        s_parse_uuid(&g_SessionId, "ccdb4b8d-1c88-48c0-bda0-0a5e8d87f4da");
    }

    Message msg = {
        .error = 0,
        .h0004 = 0,
    };

    g_NotifyCb(0, sizeof(msg), &msg, g_Param);
}

DllExport void PortalCancelLogin()
{
    
}

DllExport void PortalGetGameAccountList()
{
}

DllExport void PortalListGameAccounts(const wchar_t *game)
{
    typedef struct Message {
        uint32_t error;
        uint16_t h0004; // 1
        uint16_t h0006; // 1082 (0x043A)
        const wchar_t **game; 
        uint32_t numberOfAccounts; // Should be 1 for it to work.
    } Message;

    static const wchar_t *Gw1Name = L"Gw1";

    Message msg = {
        .error = 0,
        .h0004 = 1,
        .h0006 = 0x043A,
        .game = &Gw1Name,
        .numberOfAccounts = 1,
    };

    g_NotifyCb(4, sizeof(msg), &msg, g_Param);
}

DllExport void PortalRequestGameToken(const wchar_t *game1, const wchar_t *game2)
{
    typedef struct Message {
        uint32_t error;
        uint16_t h0004; // 1
        uint16_t h0006; // 1023 (0x03FF)
        uint8_t  session_id[16];
    } Message;

    Message msg = {
        .error = 0,
        .h0004 = 1,
        .h0006 = 1023,
    };

    memcpy(msg.session_id, &g_SessionId, sizeof(g_SessionId));
    g_NotifyCb(2, sizeof(msg), &msg, g_Param);
}

DllExport uint8_t* PortalGetUserId(void)
{
    return (uint8_t *)&g_UserId;
}

BOOL WINAPI DllMain(HINSTANCE hModule, DWORD dwReason, LPVOID lpReserved)
{
    if (dwReason == DLL_PROCESS_ATTACH) {
        // The client's file client dials during startup, so the hook has to be in place as soon
        // as this DLL is loaded. The import table is already resolved by then: the loader fixes
        // it up before any DllMain runs, so patching the slots here takes effect for every
        // later call.
        DisableThreadLibraryCalls(hModule);
        InstallResolverHook();
    }
    return TRUE;
}
