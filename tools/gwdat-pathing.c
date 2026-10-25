// gwdat-pathing -- fingerprint every map blob in Gw.dat by its navmesh.
//
// Why: `GmMapConfig` needs a `map_file_id` per map, and nothing in the client
// volunteers it (`AreaInfo.file_id` reads 0 for every Pre-Searing map, verified
// twice — see docs/06-client-tooling.md, finding F5). But the stage-2 `Path` chunk
// of a map blob *is* the navmesh, and the client holds the same navmesh in memory
// for the map it is standing in. A fingerprint computed from the same blob on both
// sides therefore identifies the blob without hooking anything.
//
// The fingerprint is (plane count, trapezoid count, bounding box) — three numbers
// that must agree exactly when both sides parsed the same file:
//
//   file_id,size,planes,trapezoids,min_x,min_y,max_x,max_y
//
// This reuses the server's own importer (`GmImportMap`), so it exercises exactly
// the path `GameSrv_LoadMap` uses — the same property `gwdat-scan` was built for.
//
// Build: CMake target `gwdat_pathing`.
//
// Usage:
//   gwdat_pathing <Gw.dat>                    every RIFF map blob
//   gwdat_pathing <Gw.dat> --dump 0x345CC     one file id, as a CSV row
//
#define COMPILE_TOOLS 1
#include "../code/OpenTyria/build_open_tyria.c"

typedef struct {
    size_t planes;
    size_t trapezoids;
    float  min_x, min_y, max_x, max_y;
} PathingFingerprint;

static void fingerprint_map(GmMapContext *context, PathingFingerprint *out)
{
    PathStaticData *static_data = &context->path.static_data;
    out->planes = static_data->planes.len;
    out->trapezoids = 0;
    out->min_x = out->min_y = +INFINITY;
    out->max_x = out->max_y = -INFINITY;

    for (size_t idx = 0; idx < static_data->planes.len; ++idx) {
        PathPlane *plane = &static_data->planes.ptr[idx];
        for (size_t t = 0; t < plane->trapezoids.len; ++t) {
            const PathTrapezoid *trap = &plane->trapezoids.ptr[t];
            float xs[4] = { trap->xtl, trap->xtr, trap->xbl, trap->xbr };
            float ys[2] = { trap->yt, trap->yb };
            for (int k = 0; k < 4; ++k) {
                if (xs[k] < out->min_x) out->min_x = xs[k];
                if (out->max_x < xs[k]) out->max_x = xs[k];
            }
            for (int k = 0; k < 2; ++k) {
                if (ys[k] < out->min_y) out->min_y = ys[k];
                if (out->max_y < ys[k]) out->max_y = ys[k];
            }
            ++out->trapezoids;
        }
    }
}

static bool fingerprint_file(FileArchive *archive, uint32_t file_id, size_t *out_size,
                             PathingFingerprint *out)
{
    array_uint8_t content = {0};
    if (FaGetFile(archive, file_id, &content) != 0) {
        array_free(&content);
        return false;
    }

    // A map blob decompresses to 400 KB - 4.5 MB. The MFT entry size is the
    // *compressed* size (Kamadan: 4980 bytes for 1.7 MB), so the filter has to
    // happen here, after decompression, not on the entry.
    if (content.len < 300000 || 4600000 < content.len) {
        array_free(&content);
        return false;
    }

    bool ok = false;
    RiffType type = RiffParseAndGetType(content.ptr, content.len);
    if (type == RIFF_MAP2 || type == RIFF_MAP1) {
        GmMapContext context = {0};
        if (GmImportMap(&context, (slice_uint8_t) { .ptr = content.ptr, .len = content.len }) == 0) {
            fingerprint_map(&context, out);
            *out_size = content.len;
            ok = true;
        }
        GmMapContext_Free(&context);
    }

    array_free(&content);
    return ok;
}

static void print_row(uint32_t file_id, size_t size, const PathingFingerprint *fp)
{
    printf("0x%08X,%zu,%zu,%zu,%.3f,%.3f,%.3f,%.3f\n",
           file_id, size, fp->planes, fp->trapezoids,
           fp->min_x, fp->min_y, fp->max_x, fp->max_y);
}

int main(int argc, char **argv)
{
    if (argc < 2) {
        printf("usage: %s <Gw.dat> [--dump <hex id>] [--min-size N] [--max-size N]\n", argv[0]);
        return 2;
    }

    const char *path = argv[1];
    uint32_t dump_id = 0;
    bool do_dump = false;
    size_t min_size = 4096;
    size_t max_size = 8u * 1024u * 1024u;

    for (int idx = 2; idx < argc; ++idx) {
        if (strcmp(argv[idx], "--dump") == 0 && idx + 1 < argc) {
            dump_id = (uint32_t) strtoul(argv[++idx], NULL, 0);
            do_dump = true;
        } else if (strcmp(argv[idx], "--min-size") == 0 && idx + 1 < argc) {
            min_size = (size_t) strtoul(argv[++idx], NULL, 0);
        } else if (strcmp(argv[idx], "--max-size") == 0 && idx + 1 < argc) {
            max_size = (size_t) strtoul(argv[++idx], NULL, 0);
        }
    }

    FileArchive archive = {0};
    if (FaOpen(&archive, path) != 0) {
        fprintf(stderr, "failed to open '%s'\n", path);
        return 1;
    }

    if (do_dump) {
        PathingFingerprint fp = {0};
        size_t size = 0;
        if (fingerprint_file(&archive, dump_id, &size, &fp)) {
            print_row(dump_id, size, &fp);
        } else {
            fprintf(stderr, "0x%08X: not a parseable map\n", dump_id);
            FaClose(&archive);
            return 1;
        }
        FaClose(&archive);
        return 0;
    }

    size_t n_entries = stbds_hmlen(archive.file_hash_table);
    size_t candidates = 0;
    size_t maps = 0;

    printf("file_id,size,planes,trapezoids,min_x,min_y,max_x,max_y\n");

    for (size_t idx = 0; idx < n_entries; ++idx) {
        uint32_t file_id = archive.file_hash_table[idx].key;
        if (file_id == 0) {
            continue;
        }

        MFTEntry entry;
        if (FaGetEntry(&archive, file_id, &entry) != 0) {
            continue;
        }
        if (entry.size < min_size || max_size < entry.size) {
            continue;
        }
        ++candidates;

        PathingFingerprint fp = {0};
        size_t size = 0;
        if (fingerprint_file(&archive, file_id, &size, &fp)) {
            print_row(file_id, size, &fp);
            ++maps;
        }
    }

    fprintf(stderr, "done: %zu ids, %zu in size range, %zu fingerprinted map blobs\n",
            n_entries, candidates, maps);
    FaClose(&archive);
    return 0;
}
