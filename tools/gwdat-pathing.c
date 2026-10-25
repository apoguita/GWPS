// gwdat-pathing -- fingerprint every map blob in Gw.dat by its navmesh.
//
// Why: `GmMapConfig` needs a `map_file_id` per map, and nothing in the client
// volunteers it (`AreaInfo.file_id` reads 0 for every Pre-Searing map, verified
// twice ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â see docs/06-client-tooling.md, finding F5). But the stage-2 `Path` chunk
// of a map blob *is* the navmesh, and the client holds the same navmesh in memory
// for the map it is standing in. A fingerprint computed from the same blob on both
// sides therefore identifies the blob without hooking anything.
//
// The fingerprint is (plane count, trapezoid count, bounding box) ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â three numbers
// that must agree exactly when both sides parsed the same file:
//
//   file_id,size,planes,trapezoids,min_x,min_y,max_x,max_y
//
// This reuses the server's own importer (`GmImportMap`), so it exercises exactly
// the path `GameSrv_LoadMap` uses ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â the same property `gwdat-scan` was built for.
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

// ---------------------------------------------------------------------------
// Parse-independent search: does any decompressed file contain a client
// trapezoid's own numbers?
//
// Why: `GmImportMap` reads the 426 RIFF map blobs, and the map the client has
// loaded is not among them (finding F12). A byte search for the *client's* floats
// does not care what container the data sits in, so it can name the file id Ã¢â‚¬â€ or
// prove the geometry is not in Gw.dat at all.
//
// Patterns are consecutive float32 pairs from the client dump Ã¢â‚¬â€ (yt,yb),
// (xtl,xtr), (xbl,xbr) Ã¢â‚¬â€ which is how a trapezoid record is laid out. A file that
// matches two or more independent patterns is the map data, not a coincidence.
// ---------------------------------------------------------------------------

#define FIND_MAX_PATTERNS 48

typedef struct {
    float a, b;
    char  label[24];
} FindPattern;

static int load_find_patterns(const char *csv_path, FindPattern *out, int max)
{
    FILE *fp = fopen(csv_path, "r");
    if (fp == NULL) {
        return 0;
    }

    // Read the rows first so the chosen trapezoids are spread across the map
    // instead of all coming from plane 0.
    enum { MAX_ROWS = 20000 };
    static float rows[MAX_ROWS][6];
    int n_rows = 0;

    char line[512];
    if (fgets(line, sizeof(line), fp) == NULL) {   // column header
        fclose(fp);
        return 0;
    }
    while (n_rows < MAX_ROWS && fgets(line, sizeof(line), fp) != NULL) {
        float xtl, xtr, yt, xbl, xbr, yb;
        int plane, id;
        if (sscanf(line, "%d,%d,%f,%f,%f,%f,%f,%f",
                   &plane, &id, &xtl, &xtr, &yt, &xbl, &xbr, &yb) != 8) {
            continue;
        }
        rows[n_rows][0] = xtl; rows[n_rows][1] = xtr; rows[n_rows][2] = yt;
        rows[n_rows][3] = xbl; rows[n_rows][4] = xbr; rows[n_rows][5] = yb;
        ++n_rows;
    }
    fclose(fp);

    if (n_rows == 0) {
        return 0;
    }

    int n = 0;
    int want = max / 3;                 // three patterns per chosen trapezoid
    if (want < 1) want = 1;
    for (int k = 0; k < want && n + 3 <= max; ++k) {
        int idx = (int) (((long long) k * n_rows) / want);
        if (idx >= n_rows) idx = n_rows - 1;
        out[n].a = rows[idx][2]; out[n].b = rows[idx][5]; snprintf(out[n].label, sizeof out[n].label, "yt/yb#%d", idx); ++n;
        out[n].a = rows[idx][0]; out[n].b = rows[idx][1]; snprintf(out[n].label, sizeof out[n].label, "xtl/xtr#%d", idx); ++n;
        out[n].a = rows[idx][3]; out[n].b = rows[idx][4]; snprintf(out[n].label, sizeof out[n].label, "xbl/xbr#%d", idx); ++n;
    }
    return n;
}

static const uint8_t *find_pattern(const uint8_t *hay, size_t len,
                                   const uint8_t *pat, size_t pat_len)
{
    if (pat_len == 0 || len < pat_len) {
        return NULL;
    }
    for (size_t idx = 0; idx + pat_len <= len; ++idx) {
        if (hay[idx] == pat[0] && memcmp(&hay[idx], pat, pat_len) == 0) {
            return &hay[idx];
        }
    }
    return NULL;
}


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
                             PathingFingerprint *out, bool dump_trapezoids, FILE *out_fp)
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

            // Full trapezoid dump, for comparing against what the client holds.
            // Our importer reads a subset (finding F11), so the useful question is
            // "is this blob's parse contained in the client's set", not equality.
            if (dump_trapezoids && out_fp != NULL) {
                PathStaticData *static_data = &context.path.static_data;
                for (size_t p = 0; p < static_data->planes.len; ++p) {
                    PathPlane *plane = &static_data->planes.ptr[p];
                    for (size_t t = 0; t < plane->trapezoids.len; ++t) {
                        const PathTrapezoid *trap = &plane->trapezoids.ptr[t];
                        fprintf(out_fp, "0x%08X,%zu,%u,%.2f,%.2f,%.2f,%.2f,%.2f,%.2f\n",
                                file_id, p, trap->trap_id,
                                trap->xtl, trap->xtr, trap->yt,
                                trap->xbl, trap->xbr, trap->yb);
                    }
                }
            }
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
    FILE *trap_out = NULL;
    const char *find_csv = NULL;
    const char *write_path = NULL;
    uint32_t write_id = 0;
    bool min_given = false;

    for (int idx = 2; idx < argc; ++idx) {
        if (strcmp(argv[idx], "--dump") == 0 && idx + 1 < argc) {
            dump_id = (uint32_t) strtoul(argv[++idx], NULL, 0);
            do_dump = true;
        } else if (strcmp(argv[idx], "--trapezoids") == 0 && idx + 1 < argc) {
            // Per-trapezoid rows for containment matching against the client.
            trap_out = fopen(argv[++idx], "w");
            if (trap_out == NULL) {
                fprintf(stderr, "cannot write '%s'\n", argv[idx]);
                return 1;
            }
            fprintf(trap_out, "file_id,plane,trap_id,xtl,xtr,yt,xbl,xbr,yb\n");
        } else if (strcmp(argv[idx], "--find-floats") == 0 && idx + 1 < argc) {
            find_csv = argv[++idx];
        } else if (strcmp(argv[idx], "--write") == 0 && idx + 2 < argc) {
            // Dump one decompressed file verbatim: the way to look *inside* a blob
            // for what the RIFF chunks do not describe (map name, name id, ...).
            write_id = (uint32_t) strtoul(argv[++idx], NULL, 0);
            write_path = argv[++idx];
        } else if (strcmp(argv[idx], "--min-size") == 0 && idx + 1 < argc) {
            min_size = (size_t) strtoul(argv[++idx], NULL, 0);
            min_given = true;
        } else if (strcmp(argv[idx], "--max-size") == 0 && idx + 1 < argc) {
            max_size = (size_t) strtoul(argv[++idx], NULL, 0);
        }
    }

    FileArchive archive = {0};
    if (FaOpen(&archive, path) != 0) {
        fprintf(stderr, "failed to open '%s'\n", path);
        return 1;
    }

    if (write_path != NULL) {
        array_uint8_t content = {0};
        if (FaGetFile(&archive, write_id, &content) != 0) {
            fprintf(stderr, "0x%08X: not found\n", write_id);
            FaClose(&archive);
            return 1;
        }
        FILE *fp = fopen(write_path, "wb");
        if (fp == NULL) {
            fprintf(stderr, "cannot write '%s'\n", write_path);
            array_free(&content);
            FaClose(&archive);
            return 1;
        }
        fwrite(content.ptr, 1, content.len, fp);
        fclose(fp);
        fprintf(stderr, "wrote %zu bytes of 0x%08X to '%s'\n", content.len, write_id, write_path);
        array_free(&content);
        FaClose(&archive);
        return 0;
    }

    if (find_csv != NULL) {
        static FindPattern patterns[FIND_MAX_PATTERNS];
        int n_patterns = load_find_patterns(find_csv, patterns, FIND_MAX_PATTERNS);
        if (n_patterns == 0) {
            fprintf(stderr, "no patterns read from '%s'\n", find_csv);
            FaClose(&archive);
            return 1;
        }
        // A map can compress below the usual floor (Kamadan: 4980 bytes for 1.7 MB),
        // so the whole archive is searched unless a window was asked for.
        size_t floor = min_given ? min_size : 0;
        fprintf(stderr, "searching %d float-pair patterns (first: %s)\n",
                n_patterns, patterns[0].label);

        size_t n_entries = stbds_hmlen(archive.file_hash_table);
        size_t scanned = 0, hits = 0;
        printf("file_id,size,riff_type,patterns_matched,labels,first_offset\n");

        for (size_t idx = 0; idx < n_entries; ++idx) {
            uint32_t file_id = archive.file_hash_table[idx].key;
            if (file_id == 0) {
                continue;
            }
            MFTEntry entry;
            if (FaGetEntry(&archive, file_id, &entry) != 0) {
                continue;
            }
            if (entry.size < floor) {
                continue;
            }

            array_uint8_t content = {0};
            if (FaGetFile(&archive, file_id, &content) != 0) {
                array_free(&content);
                continue;
            }
            ++scanned;
            if (content.len < 1024) {
                array_free(&content);
                continue;
            }

            int matched = 0;
            size_t first_offset = 0;
            char labels[160] = {0};
            for (int p = 0; p < n_patterns; ++p) {
                float pair[2] = { patterns[p].a, patterns[p].b };
                uint8_t pat[sizeof(pair)];
                memcpy(pat, pair, sizeof(pair));
                const uint8_t *at = find_pattern(content.ptr, content.len, pat, sizeof(pat));
                if (at == NULL) {
                    continue;
                }
                if (matched == 0) {
                    first_offset = (size_t) (at - content.ptr);
                }
                if (matched < 5) {
                    size_t used = strlen(labels);
                    snprintf(labels + used, sizeof(labels) - used, "%s%s",
                             used ? "|" : "", patterns[p].label);
                }
                ++matched;
            }
            if (matched >= 2) {
                printf("0x%08X,%zu,%d,%d,\"%s\",%zu\n", file_id, content.len,
                       (int) RiffParseAndGetType(content.ptr, content.len),
                       matched, labels, first_offset);
                ++hits;
            }
            array_free(&content);
        }
        fprintf(stderr, "done: %zu ids, %zu decompressed, %zu hit(s)\n", n_entries, scanned, hits);
        FaClose(&archive);
        return 0;
    }

    if (do_dump) {
        PathingFingerprint fp = {0};
        size_t size = 0;
        if (fingerprint_file(&archive, dump_id, &size, &fp, trap_out != NULL, trap_out)) {
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
        if (fingerprint_file(&archive, file_id, &size, &fp, trap_out != NULL, trap_out)) {
            print_row(file_id, size, &fp);
            ++maps;
        }
    }

    fprintf(stderr, "done: %zu ids, %zu in size range, %zu fingerprinted map blobs\n",
            n_entries, candidates, maps);
    FaClose(&archive);
    return 0;
}



