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

// The Northlands, map id 147 -- 2026-10-25, spawn point read from the live client.
//
// A NEAR match, not an exact one, and the difference is worth recording. The client
// standing in the map reports 48 planes, 6889 trapezoids, bounds
// (-20640,-21504)..(24279,24331). Two blobs agree on the planes and the bounds exactly
// -- 0x8005EA96 and 0x8001C539, 3 657 363 bytes each -- but GmImportMap reads 6890
// trapezoids from them, one more than the client holds.
//
// So the importer and the client can disagree by a trapezoid. That is a real (small)
// divergence in our parse, not a reason to distrust the match: planes, bounds and 6889
// of 6890 trapezoids agree, and no other blob is anywhere near. It still has to be
// confirmed by terrain -- this config is written on a near match, so the login is the
// evidence, not this comment.
GmMapConfig s_TheNorthlands = {
    .map_id = MapId_TheNorthlands,
    .map_file_id = 0x8005EA96,     // twin 0x8001C539; the 0x8 prefix is part of the id
    .n_spawnpoints = 1,
    .spawnpoints = {
        { -11679.181f, -16305.796f, 0 },
    },
};
// ---------------------------------------------------------------------------
// Pre-Searing, 2026-10-25: every map below was read from a live client standing in
// it (tools/probe-pathing.py), and its navmesh fingerprint matches the blob's own
// parse exactly unless noted.
//
// The shape that came out of it: pre-Searing ships **five region blobs**, and each is
// shared by an outpost and the explorable it opens onto --
//
//   0x1B97D    Ascalon City (148), Lakeside County (146), Ashford Abbey (164)
//   0x5CEE6    The Catacombs (145)                  -- alone
//   0x5CF29    Green Hills County (160), The Barradin Estate (163)
//   0x5CEE7    Wizard's Folly (161), Foibles Fair (165)
//   0x5CF2A    Regent Valley (162), Fort Ranik (166)
//   0x8005EA96 The Northlands (147)                 -- alone, and a near match
//
// So map_file_id identifies the *region*, and the map id plus spawn point choose the
// place inside it. Two maps sharing a blob is the normal case, not a bug.
// ---------------------------------------------------------------------------

// Green Hills County (160) and The Barradin Estate (163) share this blob; the
// fingerprint matches it exactly (45 planes, 4772 trapezoids).
GmMapConfig s_GreenHillsCounty = {
    .map_id = MapId_GreenHillsCounty,
    .map_file_id = 0x5CF29,        // twin 0x1BA26
    .n_spawnpoints = 1,
    .spawnpoints = {
        { -7492.531f, 1454.671f, 0 },
    },
};

GmMapConfig s_TheBarradinEstateOutpost = {
    .map_id = MapId_TheBarradinEstateOutpost,
    .map_file_id = 0x5CF29,        // twin 0x1BA26
    .n_spawnpoints = 1,
    .spawnpoints = {
        { -6479.301f, 1795.212f, 0 },
    },
};

// Wizard's Folly (161) and Foibles Fair (165): 18 planes, 5241 trapezoids, exact.
GmMapConfig s_WizardsFolly = {
    .map_id = MapId_WizardsFolly,
    .map_file_id = 0x5CEE7,        // twin 0x1BACB
    .n_spawnpoints = 1,
    .spawnpoints = {
        { 633.f, 7270.f, 0 },
    },
};

GmMapConfig s_FoiblesFairOutpost = {
    .map_id = MapId_FoiblesFairOutpost,
    .map_file_id = 0x5CEE7,        // twin 0x1BACB
    .n_spawnpoints = 1,
    .spawnpoints = {
        { 12.172f, 9910.412f, 0 },
    },
};

// Regent Valley (162) and Fort Ranik (166): 24 planes, 5267 trapezoids, exact.
GmMapConfig s_RegentValleyPreSearing = {
    .map_id = MapId_RegentValleyPreSearing,
    .map_file_id = 0x5CF2A,        // twin 0x1BB1D
    .n_spawnpoints = 1,
    .spawnpoints = {
        { 22614.f, 6849.f, 0 },
    },
};

GmMapConfig s_FortRanikPreSearingOutpost = {
    .map_id = MapId_FortRanikPreSearingOutpost,
    .map_file_id = 0x5CF2A,        // twin 0x1BB1D
    .n_spawnpoints = 1,
    .spawnpoints = {
        { 22697.885f, 10275.67f, 0 },
    },
};

// Ashford Abbey (164) is on the Ascalon City / Lakeside blob -- same 58 planes and
// 6120 trapezoids -- which makes 0x1B97D a three-map region.
GmMapConfig s_AshfordAbbeyOutpost = {
    .map_id = MapId_AshfordAbbeyOutpost,
    .map_file_id = 0x1B97D,        // twin 0x5E9E4
    .n_spawnpoints = 1,
    .spawnpoints = {
        { -12078.813f, -8452.183f, 0 },
    },
};
// The Catacombs, map id 145 -- 2026-10-25, spawn point read from the live client.
//
// Unlike Ascalon City and Lakeside County, this map does NOT share blob 0x1B97D: the
// client standing in it reports 51 planes / 5246 trapezoids / bounds
// (-21504,-27648)..(21504,20736), which match two archive entries -- 0x5CEE6 and
// 0x1C530 (3 320 363 bytes each, the two stored copies). So the sharing is per region,
// not global to the tutorial: some Pre-Searing maps agree, some do not, and each has to
// be read (see docs/test-log.md).
GmMapConfig s_Catacombs = {
    .map_id = MapId_TheCatacombs,
    .map_file_id = 0x5CEE6,
    .n_spawnpoints = 1,
    .spawnpoints = {
        { 14442.f, 2135.f, 0 },
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
    case MapId_TheCatacombs:
        return &s_Catacombs;
    case MapId_TheNorthlands:
        return &s_TheNorthlands;
    case MapId_GreenHillsCounty:
        return &s_GreenHillsCounty;
    case MapId_TheBarradinEstateOutpost:
        return &s_TheBarradinEstateOutpost;
    case MapId_WizardsFolly:
        return &s_WizardsFolly;
    case MapId_FoiblesFairOutpost:
        return &s_FoiblesFairOutpost;
    case MapId_RegentValleyPreSearing:
        return &s_RegentValleyPreSearing;
    case MapId_FortRanikPreSearingOutpost:
        return &s_FortRanikPreSearingOutpost;
    case MapId_AshfordAbbeyOutpost:
        return &s_AshfordAbbeyOutpost;
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





