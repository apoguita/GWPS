#pragma once

GmMapConfig s_KamadanJewelOfIstanOutpost = {
    .map_id = MapId_KamadanJewelOfIstanOutpost,
    .map_file_id = 0x345CC,
    .n_spawnpoints = 1,
    .spawnpoints = {
        { -9067.f, 13218.f, 0 },
    },
};

// Ascalon City (pre-Searing), map id 148 -- the first Pre-Searing map.
//
// `map_file_id` came from `tools/gwdat-pathing.c --find-floats`, 2026-10-24: the
// client standing in the map was asked for its trapezoids (58 planes, 6120
// trapezoids, bounds -18432,-24576 .. 21504,24576), and those exact numbers were
// found in two archive entries -- 0x1B97D and 0x5E9E4, the two stored copies of one
// map. Loading either through `GmImportMap` reproduces the client's fingerprint
// exactly, which is the check that this id is the right one.
//
// The spawn point is where the live client stood at the time (9541.873, 4796.456),
// read from `Player.GetXY()`. The plane is 0, **verified** 2026-10-25 by reading it
// back from the standing character (`Agent.GetZPlane`, agent id 1) with
// `tools/probe-pathing.py`; the tester confirmed the character lands in exactly the
// right place.
GmMapConfig s_AscalonCityPreSearing = {
    .map_id = MapId_AscalonCityPreSearing,
    .map_file_id = 0x1B97D,
    .n_spawnpoints = 1,
    .spawnpoints = {
        { 9541.873f, 4796.456f, 0 },
    },
};

// Lakeside County, map id 146 -- **verified** 2026-10-25.
//
// This map uses the SAME blob as Ascalon City (0x1B97D), and the tester confirmed the
// character spawns exactly where it should in Lakeside County. That is an answer, not
// an accident: pre-Searing maps share region-scale geometry, and what selects the place
// inside it is the map id plus the spawn coordinate.
//
// Consequences worth keeping in mind:
//   - `map_file_id` is *not* one per map. Several map ids can share one blob, so an
//     identical navmesh fingerprint across two maps is expected, not suspicious.
//   - Because a blob is shared, the fingerprint identifies the *region file*, so it
//     cannot by itself prove which map inside that region is meant. The map id and the
//     spawn point carry that; the client's own terrain is the check.
GmMapConfig s_LakesideCounty = {
    .map_id = MapId_LakesideCounty,
    .map_file_id = 0x1B97D,
    .n_spawnpoints = 1,
    .spawnpoints = {
        { 6602.f, 4485.f, 0 },
    },
};

GmMapConfig s_KainengCenterOutpost = {
    .map_id = MapId_KainengCenterOutpost,
    .map_file_id = 0x265F7,
};

GmMapConfig s_LionsArchOutpost = {
    .map_id = MapId_LionsArchOutpost,
    .map_file_id = 352808,
};

GmMapConfig s_DomainOfAnguish = {
    .map_id = MapId_DomainOfAnguish,
    .map_file_id = 219215,
};

GmMapConfig s_SparkflySwamp = {
    .map_id = MapId_SparkflySwamp,
    .map_file_id = 287493,
};

GmMapConfig s_LornarsPass = {
    .map_id = MapId_LornarsPass,
    .map_file_id = 46594,
};

GmMapConfig* GetMapConfigForMapId(MapId map_id)
{
    switch (map_id) {
    case MapId_KamadanJewelOfIstanOutpost:
        return &s_KamadanJewelOfIstanOutpost;
    case MapId_AscalonCityPreSearing:
        return &s_AscalonCityPreSearing;
    case MapId_LakesideCounty:
        return &s_LakesideCounty;
    case MapId_KainengCenterOutpost:
        return &s_KainengCenterOutpost;
    case MapId_LionsArchOutpost:
        return &s_LionsArchOutpost;
    case MapId_DomainOfAnguish:
        return &s_DomainOfAnguish;
    case MapId_SparkflySwamp:
        return &s_SparkflySwamp;
    case MapId_LornarsPass:
        return &s_LornarsPass;
    default:
        return NULL;
    }
}

