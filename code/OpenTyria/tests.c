#pragma once

void expect_parse_u16_equals(const char *input, uint16_t expected)
{
    uint16_t result;
    assert(parse_u16(&result, input, strlen(input), 0));
    assert(result == expected);
}

void test_parse_u16()
{
    uint16_t result;
    expect_parse_u16_equals("0", 0);
    expect_parse_u16_equals("-0", 0);
    expect_parse_u16_equals("+0", 0);
    expect_parse_u16_equals("001", 1);
    expect_parse_u16_equals("0b011", 3);
    expect_parse_u16_equals("0o11", 9);
    expect_parse_u16_equals("0x11", 17);
    expect_parse_u16_equals("00000", 0);
    assert(parse_u16(&result, "0x10000", strlen("0x10000"), 0) == false);
    assert(parse_u16(&result, "0x1", strlen("0x1"), 10) == false);
    assert(parse_u16(&result, "0b0", strlen("0b0"), 10) == false);
}

bool parse_ipv4_cstr(SocketAddr *result, const char *input)
{
    return parse_ipv4(&result->v4, input, strlen(input));
}

bool parse_ipv6_cstr(SocketAddr *result, const char *input)
{
    return parse_ipv6(&result->v6, input, strlen(input));
}

void test_parse_ipv4()
{
    SocketAddr result;
    assert(parse_ipv4_cstr(&result, "1.2.3.4:80") == true);
    assert(parse_ipv4_cstr(&result, "1.2.3.4:65535") == true);
    assert(parse_ipv4_cstr(&result, "1.2.3.4:65536") == false);
    assert(parse_ipv4_cstr(&result, ":65536") == false);
    assert(parse_ipv4_cstr(&result, "1.2.3.4") == false);
}

void test_parse_ipv6()
{
    SocketAddr result;
    assert(parse_ipv6_cstr(&result, "[e9c2:e2e3:ea8b:9f36:e151:9b65:b631:c87d]:80") == true);
    assert(parse_ipv6_cstr(&result, "[e9c2:e2e3:ea8b:9f36:e151:9b65:b631:c87d]:65535") == true);
    assert(parse_ipv6_cstr(&result, "[e9c2:e2e3:ea8b:9f36:e151:9b65:b631:c87d]:65536") == false);
    assert(parse_ipv6_cstr(&result, ":65536") == false);
    assert(parse_ipv6_cstr(&result, "e9c2:e2e3:ea8b:9f36:e151:9b65:b631:c87d:80") == false);
    assert(parse_ipv6_cstr(&result, "e9c2:e2e3:ea8b:9f36:e151:9b65:b631:c87d") == false);
}

// The client does not read a length off the wire: it looks up how many bytes each header
// carries and waits for exactly that many. A message one byte short therefore does not
// fail, it stalls the loading screen until some later message's bytes are swallowed into
// it. That is what "travel works by luck" turned out to be, so the size is pinned here.
//
// Written with explicit checks rather than assert(), because the shipping configuration is
// RelWithDebInfo and defines NDEBUG: assert() compiles out and a test built from it passes
// no matter what the code does.
static int s_test_failures;

static void expect_int(const char *what, long long got, long long expected)
{
    if (got != expected) {
        log_error("FAILED %s: got %lld, expected %lld", what, got, expected);
        ++s_test_failures;
    }
}

static uint32_t read_u32_le(const uint8_t *p)
{
    return (uint32_t) p[0] | ((uint32_t) p[1] << 8) | ((uint32_t) p[2] << 16) |
           ((uint32_t) p[3] << 24);
}

void test_pack_transfer_game_server_info()
{
    MsgFormat format = GAME_SMSG_FORMATS[GAME_SMSG_TRANSFER_GAME_SERVER_INFO];
    expect_int("0422 format header", format.header, GAME_SMSG_TRANSFER_GAME_SERVER_INFO);
    expect_int("0422 format field count", (long long) format.count,
               (long long) ARRAY_SIZE(GAME_SMSG_0422));
    expect_int("0422 format size", (long long) format.unpack_size,
               (long long) sizeof(GameSrv_TransferGameServerInfo));
    expect_int("0422 size is the captured 52", (long long) format.unpack_size, 52);

    static GameSrvMsg msg;
    memset(&msg, 0, sizeof(msg));
    msg.header = GAME_SMSG_TRANSFER_GAME_SERVER_INFO;
    msg.transfer_game_server_info.map_token = 0x11111111;
    msg.transfer_game_server_info.region = 0x22222222;
    msg.transfer_game_server_info.map_id = 0x00000094;  // 148, Ascalon City (pre)
    msg.transfer_game_server_info.is_explorable = 0x44444444;
    msg.transfer_game_server_info.player_token = 0x55555555;

    static uint8_t out[MSG_MAX_BUFFER_SIZE];
    size_t written = 0;
    int err = pack_msg(format, &written, msg.buffer, sizeof(msg.transfer_game_server_info),
                       out, sizeof(out));
    expect_int("0422 pack err", err, 0);
    expect_int("0422 bytes on the wire", (long long) written, 52);

    // The captured layout, byte for byte:
    //   a6 01 | 00 00 | host[24] | map_token | region | map_id | is_explorable
    //   | player_token | 0
    expect_int("0422 header lo", out[0], 0xA6);
    expect_int("0422 header hi", out[1], 0x01);
    expect_int("0422 word after header", (long long) (out[2] | (out[3] << 8)), 0);
    // host is a zeroed sockaddr_in here, so the five dwords start right after it.
    expect_int("0422 map_token", read_u32_le(&out[28]), 0x11111111);
    expect_int("0422 region", read_u32_le(&out[32]), 0x22222222);
    expect_int("0422 map_id", read_u32_le(&out[36]), 148);
    expect_int("0422 is_explorable", read_u32_le(&out[40]), 0x44444444);
    expect_int("0422 player_token", read_u32_le(&out[44]), 0x55555555);
    expect_int("0422 trailing dword", read_u32_le(&out[48]), 0);
}

int main()
{
    test_parse_u16();
    test_parse_ipv4();
    test_parse_ipv6();

    test_pack_transfer_game_server_info();

    if (s_test_failures != 0) {
        log_error("%d test expectation(s) failed", s_test_failures);
        return 1;
    }
    log_info("All tests passed");
    return 0;
}
