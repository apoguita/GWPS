// gwdat-scan -- find every map file inside Gw.dat.
//
// Why: `GmMapConfig` needs a `map_file_id` per map (the Gw.dat MFT key, see
// FaArchive.h). The client's `AreaInfo.file_id` is that same key, but the client
// only populates it lazily for maps it has loaded, so it cannot be dumped in one
// pass from an idle client. Gw.dat can.
//
// This reuses the server's own archive reader and decompressor, so it exercises
// exactly the code path `GameSrv_LoadMap` uses (FaGetFile -> GmImportMap).
//
// Build: the CMake target `gwdat_scan` compiles this file together with
// build_open_tyria.c (with COMPILE_TOOLS defined, so that file skips main.c).
//
// Usage:
//   gwdat_scan <Gw.dat>                     scan for RIFF map blobs
//   gwdat_scan <Gw.dat> --dump 0x345CC      hex-dump the chunks of one file id
//   gwdat_scan <Gw.dat> --min-size 8000 --max-size 4000000
//
#define COMPILE_TOOLS 1
#include "../code/OpenTyria/build_open_tyria.c"

static void dump_bytes(const uint8_t *ptr, size_t len)
{
    for (size_t idx = 0; idx < len; ++idx) {
        printf("%02X", ptr[idx]);
        if ((idx % 16) == 15) {
            printf("\n      ");
        } else {
            printf(" ");
        }
    }
    printf("\n");
}

static void dump_file(FileArchive *archive, uint32_t file_id)
{
    array_uint8_t content = {0};
    if (FaGetFile(archive, file_id, &content) != 0) {
        printf("file 0x%08X: not found or failed to read\n", file_id);
        return;
    }

    printf("file 0x%08X: %zu bytes after decompression\n", file_id, content.len);
    printf("  first 32 bytes: ");
    dump_bytes(content.ptr, content.len < 32 ? content.len : 32);

    RiffType type = RiffParseAndGetType(content.ptr, content.len);
    printf("  riff type: %d (%s)\n", (int) type,
           type == RIFF_MAP1 ? "MAP1" : type == RIFF_MAP2 ? "MAP2" : "not a map");

    MapChunkArray chunks = {0};
    if (RiffParseChunks(content.ptr, content.len, &chunks) == 0) {
        printf("  %zu chunks:\n", chunks.len);
        for (size_t idx = 0; idx < chunks.len; ++idx) {
            MapChunk *chunk = &chunks.ptr[idx];
            uint32_t stage = chunk->chunk_id >> 28;
            uint32_t kind = (chunk->chunk_id >> 24) & 0xF;
            printf("    id=0x%08X stage=%u kind=%2u size=%9u",
                   chunk->chunk_id, stage, kind, chunk->chunk_size);
            if (chunk->chunk_size >= 16) {
                printf("  head=");
                for (size_t b = 0; b < 16; ++b) {
                    printf("%02X", chunk->chunk_data.ptr[b]);
                }
            }
            printf("\n");
        }
        array_free(&chunks);
    }
    array_free(&content);
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

    size_t n_entries = stbds_hmlen(archive.file_hash_table);
    fprintf(stderr, "opened '%s' (%" PRIu64 " bytes), %zu file ids\n",
            path, archive.file_size, n_entries);

    if (do_dump) {
        dump_file(&archive, dump_id);
        FaClose(&archive);
        return 0;
    }

    size_t scanned = 0;
    size_t candidates = 0;
    size_t maps = 0;

    // CSV on stdout so the output is trivially parseable.
    printf("file_id,size,riff_type,chunk_count,chunk_ids\n");

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
        array_uint8_t content = {0};
        if (FaGetFile(&archive, file_id, &content) != 0) {
            array_free(&content);
            continue;
        }
        ++scanned;

        RiffType type = RiffParseAndGetType(content.ptr, content.len);
        if (type == RIFF_MAP1 || type == RIFF_MAP2) {
            MapChunkArray chunks = {0};
            printf("0x%08X,%zu,%d,", file_id, content.len, (int) type);
            if (RiffParseChunks(content.ptr, content.len, &chunks) == 0) {
                printf("%zu,\"", chunks.len);
                for (size_t c = 0; c < chunks.len; ++c) {
                    printf("%s0x%08X", c ? " " : "", chunks.ptr[c].chunk_id);
                }
                printf("\"");
                array_free(&chunks);
            } else {
                printf("0,\"(unparsable)\"");
            }
            printf("\n");
            ++maps;
        }
        array_free(&content);
    }

    fprintf(stderr,
            "done: %zu ids, %zu in size range, %zu decompressed, %zu RIFF map blobs\n",
            n_entries, candidates, scanned, maps);
    FaClose(&archive);
    return 0;
}
