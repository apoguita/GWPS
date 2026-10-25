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

// Lakeside County, map id 146 -- configured on a HYPOTHESIS that needs one test.
//
// The live client, standing in Lakeside County (map 146, an explorable), reports the
// same navmesh as Ascalon City (map 148, an outpost): 58 planes, 6120 trapezoids,
// bounds -18432,-24576 .. 21504,24576. Those are the numbers of blob 0x1B97D, the
// blob that loads Ascalon City correctly. Two readings are possible:
//
//   (a) pre-Searing maps share one region-scale navmesh, so 146 legitimately uses the
//       same blob -- this config is then right;
//   (b) Map.Pathing.GetPathingMaps() was serving the previous map's records, so the
//       fingerprint says nothing about 146 and this file id may be wrong.
//
// A blob carries no map identity (checked: no name string, no name_id in map 148's or
// Kamadan's blob), so the blob cannot settle it. The terrain the client draws can:
// if this config is right the character stands in Lakeside's open country, if it is
// wrong the character stands in Ascalon City while the map id says 146.
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

