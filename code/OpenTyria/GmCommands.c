#pragma once

// GM chat commands -- the testing shortcuts.
//
// Why this exists: verifying "does map X load" used to mean editing
// `characters.last_outpost` in the database and logging in again, for every map. That
// is a slow way to answer a question the server can answer from one line of chat. This
// file implements `/tp <map>` on top of the transfer machinery that already exists:
// `GameSrvCtrl_StartPlayerTransferTo` asks the auth server for a game server on the
// target district, which replies with `CompletePlayerTransfer`, which sends the client
// `GAME_SMSG_TRANSFER_GAME_SERVER_INFO` and reconnects it there.
//
// Design notes, because this is a tool and should behave like one:
//
//   - Only maps with a `GmMapConfig` are offered. Teleporting into an unconfigured map
//     would "work" and then silently serve Kamadan (`GameSrv_LoadMap` falls back), which
//     is worse than refusing: the tester would believe they tested a different map.
//   - The table is explicit rather than derived from `GmMaps.h`. A command that can
//     reach 900 map ids and quietly land on Kamadan is not a testing tool.
//   - The map type travels with the target: game servers switch on `MapType` when a
//     player attaches, and a wrong type reaches `default: abort()`.

typedef struct GmTeleportTarget {
    const char *alias;      // as typed: lower case, spaces allowed
    const char *label;      // what the log calls it
    MapId       map_id;
    MapType     map_type;
} GmTeleportTarget;

//: Every map the server has a config for. Aliases match case-insensitively with runs of
//: spaces collapsed, so "/tp lakeside county" and "/tp LakesideCounty" both work.
static const GmTeleportTarget s_teleport_targets[] = {
    { "ascalon",         "Ascalon City (pre-Searing)",  MapId_AscalonCityPreSearing,      MapType_MainTown },
    { "ascalon city",    "Ascalon City (pre-Searing)",  MapId_AscalonCityPreSearing,      MapType_MainTown },
    { "lakeside",        "Lakeside County",             MapId_LakesideCounty,             MapType_MainExplorable },
    { "lakeside county", "Lakeside County",             MapId_LakesideCounty,             MapType_MainExplorable },
    { "ashford",         "Ashford Abbey",               MapId_AshfordAbbeyOutpost,        MapType_MainTown },
    { "ashford abbey",   "Ashford Abbey",               MapId_AshfordAbbeyOutpost,        MapType_MainTown },
    { "catacombs",       "The Catacombs",               MapId_TheCatacombs,               MapType_MainExplorable },
    { "the catacombs",   "The Catacombs",               MapId_TheCatacombs,               MapType_MainExplorable },
    { "northlands",      "The Northlands",              MapId_TheNorthlands,              MapType_MainExplorable },
    { "the northlands",  "The Northlands",              MapId_TheNorthlands,              MapType_MainExplorable },
    { "green hills",     "Green Hills County",          MapId_GreenHillsCounty,           MapType_MainExplorable },
    { "barradin",        "The Barradin Estate",         MapId_TheBarradinEstateOutpost,   MapType_MainTown },
    { "barradin estate", "The Barradin Estate",         MapId_TheBarradinEstateOutpost,   MapType_MainTown },
    { "wizards folly",   "Wizard's Folly",              MapId_WizardsFolly,               MapType_MainExplorable },
    { "foibles",         "Foibles Fair",                MapId_FoiblesFairOutpost,         MapType_MainTown },
    { "foibles fair",    "Foibles Fair",                MapId_FoiblesFairOutpost,         MapType_MainTown },
    { "regent",          "Regent Valley (pre-Searing)", MapId_RegentValleyPreSearing,     MapType_MainExplorable },
    { "regent valley",   "Regent Valley (pre-Searing)", MapId_RegentValleyPreSearing,     MapType_MainExplorable },
    { "fort ranik",      "Fort Ranik",                  MapId_FortRanikPreSearingOutpost, MapType_MainTown },
    { "kamadan",         "Kamadan, Jewel of Istan",     MapId_KamadanJewelOfIstanOutpost, MapType_MainTown },
};

//: Copy a UTF-16 slice to ASCII: lower-cased, spaces collapsed, edges trimmed.
//: Returns 0 on success, -1 if a codepoint is not printable ASCII (a command in
//: another script is simply not a command this table knows).
static int GmCommand_ToAscii(slice_uint16_t text, char *buffer, size_t capacity)
{
    size_t written = 0;
    bool pending_space = false;

    for (size_t idx = 0; idx < text.len; ++idx) {
        uint16_t code = text.ptr[idx];
        if (code == ' ' || code == '\t') {
            pending_space = (written != 0);
            continue;
        }
        if (code < 0x20 || 0x7E < code) {
            return -1;
        }
        if (pending_space) {
            if (written + 2 > capacity) {
                return -1;
            }
            buffer[written++] = ' ';
            pending_space = false;
        }
        if (written + 2 > capacity) {
            return -1;
        }
        if ('A' <= code && code <= 'Z') {
            code = (uint16_t) (code - 'A' + 'a');
        }
        buffer[written++] = (char) code;
    }

    buffer[written] = '\0';
    return 0;
}

static void GmCommand_ListTargets(GameSrv *srv, uint16_t player_id)
{
    // Chat first: a command whose answer is only in the server log is a command the
    // tester cannot use from inside the game. The log still gets the full table.
    char line[100];   // stays inside one chat fragment
    size_t used = 0;
    used += (size_t) snprintf(line + used, sizeof(line) - used, "Maps:");

    const char *previous = NULL;
    for (size_t idx = 0; idx < ARRAY_SIZE(s_teleport_targets); ++idx) {
        const GmTeleportTarget *target = &s_teleport_targets[idx];
        // One entry per map, not per alias: the first alias is the one to type.
        if (previous != NULL && strcmp(previous, target->label) == 0) {
            continue;
        }
        previous = target->label;

        size_t needed = strlen(target->alias) + 3;
        if (sizeof(line) <= used + needed) {
            GameSrv_SendSystemChatMessage(srv, player_id, line);
            used = (size_t) snprintf(line, sizeof(line), "      ");
        }
        used += (size_t) snprintf(line + used, sizeof(line) - used, " %s,", target->alias);
    }
    if (0 < used) {
        GameSrv_SendSystemChatMessage(srv, player_id, line);
    }
    GameSrv_SendSystemChatMessage(srv, player_id,
                                 "Use: /tp <name>, e.g. /tp lakeside county");

    log_info("Teleport targets (%zu aliases, every one with a map config):",
             ARRAY_SIZE(s_teleport_targets));
    for (size_t idx = 0; idx < ARRAY_SIZE(s_teleport_targets); ++idx) {
        const GmTeleportTarget *target = &s_teleport_targets[idx];
        log_info("  /tp %-15s -> map %3d  %s", target->alias, (int) target->map_id,
                 target->label);
    }
}

// `/tp <alias>` -- move the player to another map by asking the auth server for a game
// server on that district. A refused command is still ERR_OK: bad input is not a
// protocol error.
static int GameSrv_HandleTeleportCommand(GameSrv *srv, uint16_t player_id, slice_uint16_t arg)
{
    char alias[48];
    if (GmCommand_ToAscii(arg, alias, sizeof(alias)) != 0 || alias[0] == '\0') {
        log_warn("Player id %u sent /tp without a usable map name", player_id);
        GameSrv_SendInvalidCommand(srv, player_id);
        return ERR_OK;
    }

    const GmTeleportTarget *target = NULL;
    for (size_t idx = 0; idx < ARRAY_SIZE(s_teleport_targets); ++idx) {
        if (strcmp(s_teleport_targets[idx].alias, alias) == 0) {
            target = &s_teleport_targets[idx];
            break;
        }
    }

    if (target == NULL) {
        log_warn("Player id %u asked to teleport to '%s', which is not in the table "
                 "(try /maps)", player_id, alias);
        GameSrv_SendSystemChatMessage(srv, player_id, "Unknown map name. Type /maps.");
        GameSrv_SendInvalidCommand(srv, player_id);
        return ERR_OK;
    }

    // Refuse rather than fall back: GameSrv_LoadMap serves Kamadan for a map with no
    // config, and a tester teleported into Kamadan would not know why.
    if (GetMapConfigForMapId(target->map_id) == NULL) {
        log_error("/tp %s refused: map %d has no GmMapConfig, so the server would fall "
                  "back to Kamadan", alias, (int) target->map_id);
        GameSrv_SendSystemChatMessage(srv, player_id,
                                      "That map has no config; the server would fall back "
                                      "to Kamadan, so the teleport is refused.");
        GameSrv_SendInvalidCommand(srv, player_id);
        return ERR_OK;
    }

    GmPlayer *player;
    if ((player = GameSrv_GetPlayer(srv, player_id)) == NULL) {
        log_error("Player id %u tried to teleport but has no player", player_id);
        return ERR_OK;
    }

    if ((int) srv->district.map_id == (int) target->map_id) {
        log_info("Player id %u is already in '%s' (map %d)", player_id, target->label,
                 (int) target->map_id);
        GameSrv_SendSystemChatMessage(srv, player_id, "You are already here.");
        return ERR_OK;
    }

    GmDistrict district = srv->district;
    district.map_id = (uint16_t) target->map_id;
    district.map_type = target->map_type;
    district.district_number = 1;

    log_info("Player id %u teleporting: map %d -> map %d '%s'",
             player_id, (int) srv->district.map_id, (int) target->map_id, target->label);

    GameSrv_SendSystemChatMessage(srv, player_id, "Teleporting, please wait...");
    GameSrvCtrl_StartPlayerTransferTo(srv, player, district);
    return ERR_OK;
}

//: Handle one chat command. Returns true when the command was one of ours.
static bool GameSrv_TryHandleGmCommand(GameSrv *srv, uint16_t player_id, slice_uint16_t msg)
{
    char command[48];
    if (GmCommand_ToAscii(msg, command, sizeof(command)) != 0 || command[0] == '\0') {
        return false;
    }

    // Split "name rest" on the first space.
    char *rest = strchr(command, ' ');
    if (rest != NULL) {
        *rest = '\0';
        ++rest;
        while (*rest == ' ') {
            ++rest;
        }
    }

    if (strcmp(command, "tp") == 0 || strcmp(command, "teleport") == 0) {
        size_t len = (rest != NULL) ? strlen(rest) : 0;
        slice_uint16_t arg = { .ptr = NULL, .len = 0 };
        // Rebuild the argument as a UTF-16 view over the already-normalised ASCII: the
        // alias grammar is ASCII by construction, so this is exact rather than lossy.
        static uint16_t scratch[48];
        for (size_t idx = 0; idx < len && idx < ARRAY_SIZE(scratch); ++idx) {
            scratch[idx] = (uint16_t) rest[idx];
        }
        arg.ptr = scratch;
        arg.len = len;
        GameSrv_HandleTeleportCommand(srv, player_id, arg);
        return true;
    }

    if (strcmp(command, "maps") == 0) {
        GmCommand_ListTargets(srv, player_id);
        return true;
    }

    return false;
}


