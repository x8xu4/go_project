# KataGo concurrency benchmark

This directory is isolated from the production analysis path. The runner reads
the production SGF, model, and configuration, creates benchmark-only config
copies, and writes all KataGo logs and results below this directory.

The fixed workload is positions 128 through 191 (64 positions) of the 336-move
`[朴廷桓]vs[安成浚]1765452105010001779.sgf`, supplied as one request with the
full move list and an `analyzeTurns` subset. It uses 100 visits, PV length 8,
and no ownership, matching the production whole-game request.

Run from the project root with:

```sh
./venv/bin/python benchmark/benchmark_katago.py
```
