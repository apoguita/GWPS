# OpenTyria

OpenTyria intend to be a fairly simple server in order to run all the stack
required to support connection from a Guild Wars client to this server possible.
Consequently, there is several design decisions that limit the scaling, but they
are chosen, because it simpliefied the final solution.

## How to use

### Compile sqlite

1. Move into the sqlite-amalgation directory.
2. Compile sqlite shell. `clang -o sqlite.exe sqlite3.c shell.c`

### Seed the database

1. From the `db` directory,
2. sqlite.exe database.db < seed.sql

### Generating Diffie-Hellman key params:

1. Use the Python script `tools/gen-dhm-keys.py` to generate Diffie-Hellman params.
2. Use the Python script `tools/patch-gw.py` to update an executable with the
   appropriate patches.

### Fix DHM params in OpenTyria

1. This should be temporary, but you need to fix the `server_private` and
   `prime_modulus` in `code/main.c`. Those values can be in `keys.txt`.

### Copy Gw.dat in the root of OpenTyria

### Starting everything

1. Launch the "webgate" `python tools/webgate.py`
2. Launch OpenTyria
3. Launch the patched Guild Wars, e.g. `Gw.custom.exe -authsrv 127.0.0.1 -portal 127.0.0.1`
4. Use one of user1@example.com, user2@example.com, or user3@example.com to connect.

## Known issues
