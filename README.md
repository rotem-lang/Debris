# Debris

Debian based installment maker.

Debris builds `.deb` packages for applications deployed with Docker images and
`docker compose` v2. One JSON spec per app describes the whole package — where to fetch
the compose file from, how to render `.env`, whether to bake the images in for air-gapped
installs, which helper commands and desktop launchers to ship — and `debris build` turns
that into an installable package.

It targets **closed networks**: no internet on the target machines, an internal git
server, an internal docker registry, an internal apt mirror.

There is nothing to install — Debris uses only the Python standard library, so you clone
the repository and run it in place:

```bash
python3 -m debris validate examples/online-app/spec.json
python3 -m debris build    examples/online-app/spec.json -o dist/
```

To work on Debris itself, create a venv for the test tooling:

```bash
python3 -m venv .venv && .venv/bin/pip install pytest
PYTHONPATH=. .venv/bin/pytest -q
```

## Status

Early development. The CLI surface is defined; the commands are being implemented branch
by branch — see the status table in [CLAUDE.md](CLAUDE.md).

## Documentation

- [CLAUDE.md](CLAUDE.md) — architecture, constraints, and the packaging decisions that
  aren't obvious from the code.
- [docs/design.md](docs/design.md) — the full design: JSON spec reference, install layout,
  maintainer script behaviour, and the verification plan.
