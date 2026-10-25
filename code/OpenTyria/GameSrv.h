#pragma once

typedef struct GameConnection {
    uintptr_t     token;
    IoSource      source;
    array_uint8_t incoming;
    array_uint8_t outgoing;
    bool          writable;
    arc4_context  cipher_enc;
    arc4_context  cipher_dec;
    uint16_t      player_id;
} GameConnection;

typedef struct GameConnMap {
    uintptr_t      key;
    GameConnection value;
} GameConnMap;

typedef struct GamePlayerMsg {
    uint16_t   player_id;
    GameCliMsg msg;
} GamePlayerMsg;
typedef array(GamePlayerMsg) GamePlayerMsgArray;

bool GmDistrict_Equal(GmDistrict left, GmDistrict right)
{
    assert(left.district_number != 0 && right.district_number != 0);
    return left.map_id == right.map_id &&
           left.region == right.region &&
           left.language == right.language &&
           left.map_type == right.map_type &&
           left.district_number == right.district_number;
}

bool GmDistrict_IsCompatible(GmDistrict left, GmDistrict right)
{
    return left.map_id == right.map_id &&
           left.region == right.region &&
           left.language == right.language &&
           left.map_type == right.map_type &&
           (right.district_number == 0 || left.district_number == right.district_number);
}

typedef struct GameSrvSetupParams {
    uint32_t   server_id;
    GmDistrict district;
    SocketAddr ctrl_srv_addr;
} GameSrvSetupParams;

typedef struct GameSrv {
    Thread                   thread;
    uint32_t                 server_id;
    GmDistrict               district;
    // The connection a transfer was started for, remembered because the client can
    // disconnect (leaving the map) *before* the auth server's completion arrives. Without
    // this the old server could no longer find the player and never sent
    // TRANSFER_GAME_SERVER_INFO -- the client hung on the loading screen.
    uintptr_t                transfer_conn_token;
    uint32_t                 transfer_player_id;
    GmUuid                   transfer_char_id;
    // The destination, recorded for the same reason as the connection: the completion
    // handler has to fill in the client's is_explorable flag, and srv->district describes
    // where the player is leaving, which is the wrong map on any outpost/explorable hop.
    GmDistrict               transfer_district;
    bool                     transfer_pending;
    GmMapConfig             *map_static_config;
    Iocp                     iocp;
    Database                 database;
    FileArchive              archive;
    CtrlConnection           ctrl_conn;
    bool                     quit_signaled;
    GameConnMap             *connections;
    array_uintptr_t          connections_with_event;
    array_uintptr_t          connections_to_remove;
    ArrayEvent               events;
    Mutex                    mtx;
    GmPlayerArray            players;
    GamePlayerMsgArray       messages;
    int32_t                  current_instance_time;
    int64_t                  creation_instance_time;
    int64_t                  current_frame_time;
    int64_t                  last_ping_request;
    int16_t                  next_bag_id;
    GmItemArray              items;
    GmAgentArray             agents;
    GmPartyArray             parties;
    mbedtls_chacha20_context random;
    GameSrvMsg               srv_msg;
    int64_t                  last_world_tick;
    array_uint16_t           text_builder;
    GmMapContext             map_context;
} GameSrv;
typedef array(GameSrv *) GameSrvArray;

int  GameSrv_Setup(GameSrv *srv, GameSrvSetupParams params);
void GameSrv_Free(GameSrv *srv);
int  GameSrv_Start(GameSrv *srv);
