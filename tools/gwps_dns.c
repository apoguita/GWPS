// Minimal DNS responder for GWPS.
//
// WHY
// The client builds and resolves its file-server names itself (P:\Code\Net\FileCli\FcSrv.cpp)
// and some of those lookups ignore the hosts file -- after flushing the DNS cache, entries for
// file2/file6 reappeared although both were in hosts. Answering the lookup instead of the
// connect is therefore the only way to keep it on this machine.
//
// WHAT IT DOES
// Listens on 127.0.0.1:53. Any A record under arenanetworks.com or ncplatform.net is answered
// with 127.0.0.1 after a short TTL; every other query is forwarded unchanged to the upstream
// resolver and its reply relayed, so normal name resolution keeps working while this runs.
//
// WHAT IT DOES NOT DO
// It is not a resolver: no caching, no recursion of its own, no EDNS handling beyond relaying
// bytes. It answers only what it is asked, which is all the client needs.
//
// Usage:
//   gwps_dns [--upstream <ip>] [--port 53] [--bind 127.0.0.1] [--ttl 60]
//
// Binding UDP 53 on loopback needs no administrator rights; pointing an adapter at it does,
// which is what tools/dns-gwps.ps1 handles.

#define WIN32_LEAN_AND_MEAN

#include <WinSock2.h>
#include <WS2tcpip.h>
#include <Windows.h>

#include <stdint.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <ctype.h>

#define DNS_MAX_PACKET   1500
#define DNS_HEADER_SIZE  12

static const char *s_redirect_suffixes[] = {
    "arenanetworks.com",
    "ncplatform.net",
};

static bool name_is_redirected(const char *name)
{
    size_t len = strlen(name);
    for (size_t i = 0; i < sizeof(s_redirect_suffixes) / sizeof(s_redirect_suffixes[0]); ++i) {
        const char *suffix = s_redirect_suffixes[i];
        size_t slen = strlen(suffix);
        if (len < slen) continue;

        if (strcmp(name + (len - slen), suffix) == 0) {
            return true;
        }
    }
    return false;
}

// Decode a question name at `offset` into lowercase dotted text. Returns the offset just past
// the name (and, separately, the caller adds 4 for QTYPE/QCLASS).
static bool decode_question_name(const uint8_t *msg, size_t len, size_t offset,
                                 char *out, size_t out_size, size_t *after)
{
    size_t pos = offset;
    size_t written = 0;

    while (pos < len) {
        uint8_t label_len = msg[pos];
        if (label_len == 0) {
            ++pos;
            break;
        }
        // Compression pointers are not valid in a question; refuse rather than loop.
        if ((label_len & 0xC0) != 0) return false;
        if (pos + 1 + label_len > len) return false;
        if (written + label_len + 2 >= out_size) return false;

        if (written != 0) out[written++] = '.';
        for (size_t i = 0; i < label_len; ++i) {
            out[written++] = (char) tolower(msg[pos + 1 + i]);
        }
        pos += 1 + label_len;
    }

    out[written] = '\0';
    *after = pos;
    return written != 0;
}

static void put_u16(uint8_t *p, uint16_t value)
{
    p[0] = (uint8_t) (value >> 8);
    p[1] = (uint8_t) (value & 0xFF);
}

static void put_u32(uint8_t *p, uint32_t value)
{
    p[0] = (uint8_t) (value >> 24);
    p[1] = (uint8_t) (value >> 16);
    p[2] = (uint8_t) (value >> 8);
    p[3] = (uint8_t) (value & 0xFF);
}

// Build the answer for a redirected A query: header, echoed question, one A record.
static size_t build_redirect_answer(const uint8_t *query, size_t query_len,
                                    size_t question_end, uint8_t *out, size_t out_size,
                                    uint32_t ttl)
{
    if (query_len < DNS_HEADER_SIZE || question_end + 4 > query_len) return 0;

    size_t question_len = (question_end + 4) - DNS_HEADER_SIZE;
    size_t total = DNS_HEADER_SIZE + question_len + 16;  // 16 = answer record
    if (total > out_size) return 0;

    memcpy(out, query, DNS_HEADER_SIZE + question_len);

    // Response: QR=1, AA=1, RD copied from the query, RA=1, RCODE=0.
    out[2] = (uint8_t) (0x80 | 0x04 | (query[2] & 0x01));
    out[3] = 0x80;
    put_u16(&out[4], 1);   // QDCOUNT
    put_u16(&out[6], 1);   // ANCOUNT
    put_u16(&out[8], 0);   // NSCOUNT
    put_u16(&out[10], 0);  // ARCOUNT

    uint8_t *rec = &out[DNS_HEADER_SIZE + question_len];
    rec[0] = 0xC0;         // name: pointer to the question name
    rec[1] = 0x0C;         // at offset 12
    put_u16(&rec[2], 1);   // TYPE  A
    put_u16(&rec[4], 1);   // CLASS IN
    put_u32(&rec[6], ttl);
    put_u16(&rec[10], 4);  // RDLENGTH
    rec[12] = 127;
    rec[13] = 0;
    rec[14] = 0;
    rec[15] = 1;

    return total;
}

int main(int argc, char **argv)
{
    const char *bind_addr = "127.0.0.1";
    const char *upstream = NULL;
    unsigned short port = 53;
    uint32_t ttl = 60;

    for (int i = 1; i < argc; ++i) {
        if (strcmp(argv[i], "--bind") == 0 && i + 1 < argc) {
            bind_addr = argv[++i];
        } else if (strcmp(argv[i], "--upstream") == 0 && i + 1 < argc) {
            upstream = argv[++i];
        } else if (strcmp(argv[i], "--port") == 0 && i + 1 < argc) {
            port = (unsigned short) atoi(argv[++i]);
        } else if (strcmp(argv[i], "--ttl") == 0 && i + 1 < argc) {
            ttl = (uint32_t) atoi(argv[++i]);
        } else {
            fprintf(stderr, "unknown argument: %s\n", argv[i]);
            return 2;
        }
    }

    WSADATA wsa;
    if (WSAStartup(MAKEWORD(2, 2), &wsa) != 0) {
        fprintf(stderr, "WSAStartup failed\n");
        return 1;
    }

    SOCKET sock = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
    if (sock == INVALID_SOCKET) {
        fprintf(stderr, "socket failed: %d\n", WSAGetLastError());
        return 1;
    }

    struct sockaddr_in local;
    memset(&local, 0, sizeof(local));
    local.sin_family = AF_INET;
    local.sin_port = htons(port);
    inet_pton(AF_INET, bind_addr, &local.sin_addr);

    if (bind(sock, (struct sockaddr *) &local, sizeof(local)) != 0) {
        fprintf(stderr, "bind %s:%u failed: %d\n", bind_addr, port, WSAGetLastError());
        return 1;
    }

    struct sockaddr_in upstream_addr;
    bool have_upstream = false;
    if (upstream != NULL) {
        memset(&upstream_addr, 0, sizeof(upstream_addr));
        upstream_addr.sin_family = AF_INET;
        upstream_addr.sin_port = htons(53);
        if (inet_pton(AF_INET, upstream, &upstream_addr.sin_addr) == 1) {
            have_upstream = true;
        }
    }

    printf("gwps_dns listening on %s:%u", bind_addr, port);
    if (have_upstream) {
        printf(", forwarding everything else to %s\n", upstream);
    } else {
        printf(", forwarding disabled (only redirected names are answered)\n");
    }
    fflush(stdout);

    static uint8_t query[DNS_MAX_PACKET];
    static uint8_t answer[DNS_MAX_PACKET];
    static uint8_t reply[DNS_MAX_PACKET];

    for (;;) {
        struct sockaddr_in from;
        int from_len = sizeof(from);
        int received = recvfrom(sock, (char *) query, sizeof(query), 0,
                                (struct sockaddr *) &from, &from_len);
        if (received <= 0) continue;
        if ((size_t) received < DNS_HEADER_SIZE + 5) continue;

        // Only plain single-question queries.
        if ((query[2] & 0x80) != 0) continue;          // not a query
        if (((query[4] << 8) | query[5]) != 1) continue;

        char name[256];
        size_t question_end = 0;
        if (!decode_question_name(query, (size_t) received, DNS_HEADER_SIZE,
                                  name, sizeof(name), &question_end)) {
            continue;
        }

        uint16_t qtype = (uint16_t) ((query[question_end] << 8) | query[question_end + 1]);
        bool redirect = qtype == 1 && name_is_redirected(name);

        if (redirect) {
            size_t size = build_redirect_answer(query, (size_t) received, question_end,
                                                answer, sizeof(answer), ttl);
            if (size == 0) continue;
            sendto(sock, (const char *) answer, (int) size, 0,
                   (struct sockaddr *) &from, from_len);
            printf("A %s -> 127.0.0.1\n", name);
            fflush(stdout);
            continue;
        }

        if (!have_upstream) {
            continue;
        }

        // Relay everything else so the machine's normal resolution keeps working. Each query
        // gets its own socket: reusing the listener's would let a slow answer be handed to the
        // wrong client, and waiting on it would stall every other lookup meanwhile.
        SOCKET relay_sock = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
        if (relay_sock == INVALID_SOCKET) {
            continue;
        }

        DWORD timeout = 1500;
        setsockopt(relay_sock, SOL_SOCKET, SO_RCVTIMEO, (const char *) &timeout, sizeof(timeout));

        if (sendto(relay_sock, (const char *) query, received, 0,
                   (struct sockaddr *) &upstream_addr, sizeof(upstream_addr)) != SOCKET_ERROR) {
            struct sockaddr_in relayed_from;
            int relayed_len = sizeof(relayed_from);
            int relayed = recvfrom(relay_sock, (char *) reply, sizeof(reply), 0,
                                   (struct sockaddr *) &relayed_from, &relayed_len);
            if (relayed > 0) {
                sendto(sock, (const char *) reply, relayed, 0, (struct sockaddr *) &from, from_len);
            }
        }

        closesocket(relay_sock);
    }

    return 0;
}
