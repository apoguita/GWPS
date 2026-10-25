# Packet scope: how a header is categorised

Every conversation about this server eventually becomes "is `<header>` a bug, a
missing feature, or noise?" — and the answer has never been written down. This
document defines the categories, says which source wins when they disagree, and
describes the catalogue that applies the rule mechanically.

The catalogue is generated, not hand-maintained: `data/packet-catalog.csv`,
built by `tools/packet-catalog.py`. Regenerate it after touching `msgdefs.c`,
`opcodes.h`, the dispatch switches, or after every capture.

```powershell
py tools/packet-catalog.py                 # folds in every captures/*.jsonl
py tools/packet-catalog.py --no-capture    # static view only
```

## The four sources, and what each one knows

| Source | Path | Only it knows | Trust for |
|--------|------|---------------|-----------|
| **Live capture** | `tools/sniff-capture.py` → `captures/*.jsonl` | what the client really sends, and how big | **size, existence, rate** |
| **Client tables** | `Py4GW_Stealth/py4gw/packet_sniffer.py` (247 StoC + 104 CToS names), `Py4GW_Reforged_Native/include/GW/common/opcodes.h` (217 StoC names), `include/GW/common/stoc.h` (123 packet structs) | the client's own vocabulary and structs | **names, payload semantics** |
| **Our formats** | `code/OpenTyria/msgdefs.c` / `.info` | which headers our server can **parse**, and its struct layout | **parse capability** |
| **Our dispatch** | `code/OpenTyria/{Game,Auth}Srv.c` | which of those we actually **handle** | **implementation state** |

### Precedence when they disagree

1. **A capture beats every table.** It is the wire. If `msgdefs` says 26 bytes and
   the client sends 28, the client is right and the table is a bug.
2. **The client's struct beats our struct** for payload meaning — it is the code
   that consumes the bytes. Our structs are reverse-engineered from it.
3. **Neither client table beats the other.** Reforged's opcode names and the
   sniffer's decoder names are two lineages that disagree (e.g. `0x0020` is
   `AGENT_SPAWNED` in one and `WORLD_CREATE_AGENT` in the other). The catalogue
   keeps both columns; a conflict is information, not an error.
4. **For outbound size, `GameMsg.h` wins over `msgdefs`.** `msgdefs` is the parse
   path; `GameSrv_BroadcastMessage(srv, buffer, sizeof(*msg))` sends the
   `GameMsg.h` struct. They are allowed to drift, and they have — see `0x29` below.

## Statuses — mechanical, produced by the tool

The tool derives exactly one status per header, from evidence only:

| Status | Meaning | Direction |
|--------|---------|-----------|
| `unparsed-inbound` | the client can send it; our format table has no entry, so `GameSrv_GetMessages` cannot bound it | CToS |
| `parsed-unhandled` | we can parse it and it is discarded → the `Unhandled ...` log line | CToS |
| `parsed-unhandled-observed` | as above, **and the client actually sent it in a capture** — this is the real worklist | CToS |
| `handled-unobserved` | a `case` exists; never seen in a capture | CToS |
| `handled-observed` | handled and observed: the working set | CToS |
| `produced` | our server builds this message | StoC |
| `never-produced` | parseable, never built by us | StoC |
| `unparseable-outbound` | no format entry | StoC |

`docs/04-scope.md`'s T15 log audit is the manual version of this table. The
catalogue replaces the manual pass: `status` is what T15 asks, computed.

## Scope tiers — judgement, recorded by hand

Status says what *is*; the tier says what it *should be*. A tier is never inferred
by the tool.

| Tier | Rule for admission | Where it lands |
|------|--------------------|----------------|
| **P0 — Phase 0** | a header some test in `04-scope.md` (T3–T14) needs to work | fix now |
| **P1 — Pre-Searing** | required to stand in an Ascalon-class outpost or explorable: spawn data, pathing, chat, items, party | milestone 1 |
| **P2 — Later** | needed for a functioning game but not for a logged-in character in a map: combat, skills, merchants, quests | milestone 5 |
| **N — Noise** | periodic by design: ticks, heartbeats, ping. Must be *understood*, never "fixed" | ignore, pin in tests |
| **X — Out of scope** | other campaigns, PvP, guild halls, Ascalon Academy | do not implement |

Two rules that keep this honest:

- **"Unimplemented" is not a tier.** Poker of a header into "out of scope" because
  it is not implemented yet is how a scope document becomes a lie. Tier is a
  product decision; status is the implementation fact.
- **A tier can be granted, never assumed.** If a header shows up in a capture and
  nobody granted it a tier, it is `P0-review`, not `P2`.

## Invariants the capture established (2026-10-24)

Measured on 711 packets, 698 StoC + 11 CToS, from a live client:

- **The wire header is 4 bytes, and its upper half is always zero.** In every
  captured packet `u16@+2 == 0`; there is no length field. Our format tables count
  the header as 2 bytes (`TYPE_MSG_HEADER` unpacks a `uint16_t`), so a complete
  fixed-size entry lands on `struct + 2` on the wire.
- **That +2 baseline is verified**, on messages whose tables we track correctly:
  `0x001E` (6→8), `0x0081` (6→8), `0x3D` (26→28).
- **Thirteen headers disagree with it.** Deltas from +4 to +17 — e.g. `0x0029`
  `AGENT_MOVE_TO_POINT`, format 18, wire 24. At least one is a *known* two-source
  drift: the send path uses `GameMsg.h`'s `GameSrv_MoveAgentToPoint` (22 bytes,
  → 24 on the wire), so the live message is consistent with the sender and the
  **`msgdefs` entry is the stale one**. The other twelve need the same treatment,
  one at a time, against the client's struct.
- **Do not "fix" a size mismatch by editing `msgdefs` to match a capture** without
  checking which side sends the message. Inbound sizes come from `msgdefs`;
  outbound sizes come from `GameMsg.h`.

## Naming: three vocabularies, one column each

| Column | Vocabulary | Example, header `0x0020` |
|--------|-----------|--------------------------|
| `name_ours` | `opcodes.h` | `GAME_SMSG_WORLD_CREATE_AGENT` |
| `name_client_reforged` | Reforged opcodes | `AGENT_SPAWNED` |
| `name_client_sniffer` | the sniffer's decoder tables | `WORLD_CREATE_AGENT` |

When our name and a client name diverge, the catalogue is the record of the
translation. **61 headers currently disagree between the two client tables alone**,
before our names are considered — `0x3D` is the settled example: the client calls
it `MOVE_TO_COORD_WITH_DIR`, we call it `GAME_CMSG_POSITION_UPDATE`, and the capture
says the payload is a position report — our name describes it better, but anyone
cross-referencing client tooling needs to know both (finding F9 in
`docs/test-log.md`).

## Procedure: classifying one header

1. Find it: `py tools/sniff-capture.py --header 0x<hh> --seconds 20` with the
   client in the relevant state. No capture, no opinion.
2. Read its row in `data/packet-catalog.csv`: `status`, both client names, sizes.
3. Decode the payload against the client's struct in
   `Py4GW_Reforged_Native/include/GW/common/stoc.h` (or the sniffer's decoder),
   **not** against ours — ours is what is being verified.
4. Assign a tier, and write down which test needs it (for P0) or which play
   feature needs it (for P1).
5. Record the outcome in `docs/test-log.md` with the capture it came from.

**"Done" for one header** means all four: it parses at the captured size, it is
handled (or deliberately ignored with a tier of N/X), its payload fields are named
in our struct, and a capture diff exists that would notice if it regressed.

## Current shape of the catalogue

782 headers: 60 `AUTH_CMSG`, 40 `AUTH_SMSG`, 194 `GAME_CMSG`, 488 `GAME_SMSG`.

| Status | Count |
|--------|-------|
| `never-produced` | 492 |
| `parsed-unhandled` | 222 |
| `produced` | 36 |
| `handled-unobserved` | 30 |
| `handled-observed` | 1 |
| `parsed-unhandled-observed` | 1 |
| `unparsed-inbound` | **0** |

Read that honestly: the server handles **18 game inbound headers and produces 36
outbound**, against 194 + 488 that exist. The `0` on `unparsed-inbound` is a
*statement about the table*, not a guarantee — it means every inbound header we
know of has a format entry, not that every header the client can send does.

## Open items this document creates

1. **Triage the 13 size disagreements** into "stale `msgdefs`" (fix the table) or
   "send-path bug" (fix the struct) — one commit each, with the capture cited.
2. **`0x39` `INTERACT_LIVING`**: format 7, wire 12, and unhandled. It is the
   interaction packet, so it is P1 at the latest; its format is wrong first.
3. **Decide tiers for the 36 produced headers** — they are the ones the server
   already speaks, so they should be the first rows with a tier.
4. **Re-capture against our own server** once it is up: a diff against the golden
   capture is what turns these categories into T7/T10 evidence.
