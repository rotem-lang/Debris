# CLAUDE.md

Guidance for Claude Code when working in this repository.

## What Debris is

Debris builds Debian packages (`.deb`) for applications that are deployed with Docker
images and `docker compose` v2. One JSON spec file per app describes the whole package;
`debris build spec.json` fetches the app's compose file from git, renders `.env` from a
template, optionally bakes the docker images in, and emits an installable `.deb`.

Everything is shaped by one constraint: **the target machines sit on a closed network.**
No internet, an internal git server, an internal docker registry, an internal apt mirror.
Anything that assumes outbound connectivity is wrong here.

## How Debris is delivered and run

`git bundle` the repository, carry it across to the closed network, clone it there, and run
it in place:

```bash
python3 -m debris build spec.json -o dist/
```

**There is no install step and no packaging config** — no `pyproject.toml`, no wheel, no
`debris` console script. That is only possible because of the stdlib-only rule below, and
it is why that rule is worth defending. Any change that introduces a runtime dependency
also introduces a deployment problem.

## Hard constraints

- **Runtime dependencies: standard library only.** No `jsonschema`, no `PyYAML`, no
  `requests`. A dependency would mean mirroring packages into the closed network and
  reintroducing an install step, so spec validation is hand-written and `git` / `docker` /
  `dpkg-deb` are invoked as subprocesses. `pytest` is dev-only and must never be imported
  by anything under `debris/`.
- **No debhelper.** Packages are built by staging a filesystem tree, generating
  `DEBIAN/control` plus maintainer scripts, and calling `dpkg-deb --build`. A build host
  needs only `dpkg-deb`, `git`, `docker` and Python 3.12.
- **Generated maintainer scripts are POSIX `sh`**, `set -eu`, and must be idempotent —
  dpkg can call them more than once. All values are substituted at build time; nothing is
  templated on the target.

## Architecture

The pipeline is `fetch → render → stage → dpkg-deb`, orchestrated by `builder.py`:

| Module | Role |
|---|---|
| `spec.py` | Dataclasses, loader and hand-written validator for the JSON spec |
| `scaffold.py` | The starter spec `debris init` writes |
| `sources/` | `Source` protocol + registry; `git.py` (shallow fetch, sparse checkout), `local.py` |
| `backends/` | `Backend` protocol + registry; `compose.py` is the only v1 implementation |
| `render.py` | `${VAR}` substitution for `.env`, strict about unresolved placeholders |
| `images.py` | `docker pull` / `save` / digest capture for offline mode |
| `staging.py` | Assembles the package filesystem tree in a temp dir |
| `control.py` | `DEBIAN/control`, `md5sums`, maintainer scripts |
| `dpkg.py` | `dpkg-deb --build` invocation and `.deb` filename conventions |

`sources/` and `backends/` are registries rather than `if` chains because both are known
extension points: more source kinds, and eventually a Kubernetes/Helm backend alongside
`compose`. The spec nests backend config under `deployment.kind`, so adding one does not
touch the CLI or the packaging code.

## Install layout

```
/opt/<pkg>/<version>/docker-compose.yml
/opt/<pkg>/<version>/.env
/opt/<pkg>/<version>/.debris-manifest.json
/opt/<pkg>/<version>/images/images.tar        # offline mode only
/opt/<pkg>/current -> <version>               # relative symlink, shipped in the .deb
/usr/bin/<pkg>-{start,stop,restart,status,logs,compose}
/usr/share/applications/*.desktop
```

Helpers resolve `/opt/<pkg>/current` at call time, never a baked version path, so they
survive upgrades and downgrades untouched.

## Decisions that aren't obvious from the code

Read this section before changing the packaging layout — each of these was chosen against
a plausible-looking alternative that does not work.

- **One version on disk at a time.** It's tempting to keep `/opt/<pkg>/1.4.2` and
  `/opt/<pkg>/1.5.0` side by side for instant rollback. dpkg makes this impossible under a
  single package name: installing 1.5.0 is an *upgrade*, and after unpacking, dpkg deletes
  every file the old version owned that the new one doesn't ship, then prunes the empty
  directory. The version directory is kept in the path anyway, for provenance and because
  it makes the `current` symlink meaningful.
- **Rollback is "archive every `.deb`".** Since versions can't coexist, going back means
  `dpkg -i <pkg>_1.4.2_all.deb` or `apt install <pkg>=1.4.2`. Every artifact Debris
  produces must therefore be retained in the internal mirror — that is a documented
  operational requirement, not an optional nicety. Use `apt-mark hold` after a deliberate
  downgrade so the next `apt upgrade` doesn't undo it.
- **`current` is a real symlink shipped inside the archive**, not something `postinst`
  creates with `ln -sfn`. dpkg unpacks and replaces symlinks correctly, so upgrades and
  downgrades repoint it with zero maintainer-script logic.
- **Offline image lists are explicit in the spec**, not parsed out of the compose file.
  Parsing would require a YAML dependency and post-interpolation resolution, which
  violates the stdlib-only rule for a small convenience.
- **Never bind-mount runtime data inside `/opt/<pkg>/<version>/`.** dpkg removes only the
  files it owns, so a `./data` bind-mount would be orphaned there while the compose file
  next to it disappears on upgrade. Use named volumes, or pass a path like
  `/var/lib/<pkg>` in through an env var.
- **`postinst` does not start the stack by default** (`install.start_on_install`).
  Installing a package and having containers come up unannounced is surprising; the admin
  runs `<pkg>-start`.
- **`--mode` must default to `None`, not to a mode.** It is an *override*: absent means
  "use `deployment.mode` from the spec". Giving the flag a default makes the spec field
  permanently unreachable and makes `validate` (which has no `--mode`) disagree with
  `build` about the same file. Offline-by-default belongs in the spec loader, where
  `deployment.mode` defaults to `"offline"` when the key is absent.
- **Validation reports every problem at once, not the first.** A round trip to a
  closed-network machine is expensive, so one `validate` has to be enough to fix the whole
  file. That is what shapes `_Reader` in `spec.py`: a failed read records a problem and
  returns `None` instead of raising, and `load_spec` refuses to return a `Spec` while any
  problem is outstanding. The refusal is what keeps the `str` annotations on the dataclasses
  honest even though a reader can hand back `None` — do not relax it.
- **Every spec default lives in the loader.** Dataclass fields carry no defaults at all.
  Splitting them between the dataclass and the loader is how a value ends up meaning one
  thing in `validate` and another in `build`, which is the same failure the `--mode` bullet
  above describes.
- **An unknown key in a spec is an error, not a warning.** A misspelt `dependes` is silently
  ignored otherwise, and the mistake surfaces as a missing feature on the target rather than
  as a build failure. `reject_unknown` suggests the nearest real key.
- **`schema/debris.schema.json` is editor autocomplete only and is never read at runtime.**
  `spec.py` is authoritative; JSON Schema cannot express the cross-field rules that actually
  prevent broken installs, and `jsonschema` would be a dependency to mirror. Because nothing
  breaks when the schema drifts, `tests/test_schema.py` compares its patterns, defaults and
  key sets against `spec.py` — keep that test passing rather than deleting the schema.

## Commands

Run Debris straight from the repository root:

```bash
python3 -m debris init     demo              # writes demo/spec.json, then edit it
python3 -m debris validate demo/spec.json
python3 -m debris build    demo/spec.json -o dist/ --source-dir /path/to/checkout
python3 -m debris inspect  dist/acme-portal_1.4.2_all.deb
```

`validate` prints the spec with every default resolved, which is the point of running it —
the defaults are what a build will use and they are invisible in the file.

`--source-dir` substitutes a local checkout for the git fetch. Use it in tests and
whenever the build host can't reach the git server.

The `examples/` directory referenced elsewhere in this file lands on `docs/readme-examples`;
until then `debris init` is the way to get a spec that validates.

Development tooling lives in a throwaway venv, needed only to run the tests and linter:

```bash
python3 -m venv .venv && .venv/bin/pip install pytest   # one-time setup
PYTHONPATH=. .venv/bin/pytest -q                       # tests
```

There is no linter or formatter. Style is a review concern: match the surrounding code.

`PYTHONPATH=.` is required: Debris is never installed, and pytest does not put the
repository root on `sys.path` by itself, so without it every test fails with
`ModuleNotFoundError: No module named 'debris'`.

`python3-venv` is not installed by default on every machine (`apt install python3.12-venv`).

There is deliberately no task runner, no packaging config, and no `pip install` of Debris
itself.

## Conventions

- Branches: `<type>/<kebab-case>` (`feat/`, `fix/`, `ref/`, `test/`, `docs/`, `chore/`),
  cut from `dev` and merged back to `dev`. `main` is release-only.
- Tests that need the docker daemon, `docker compose`, or a registry must **skip** when
  those are unavailable rather than fail. `docker compose` v2 is not installed on the
  primary dev machine.

## Status

Build order — `0 → 1 → 2 → 3` is a hard chain; once 3 lands, 4, 5 and 6 are independent.

| # | Branch | Scope | State |
|---|---|---|---|
| 0 | `chore/scaffold` | `CLAUDE.md`, `docs/design.md`, package + CLI skeleton, tests | done |
| 1 | `feat/spec-validation` | `spec.py`, `scaffold.py`, JSON schema, `debris validate`, `debris init` | done |
| 2 | `feat/sources-and-render` | `sources/{local,git}.py`, `render.py` | todo |
| 3 | `feat/deb-build` | staging, control, dpkg, compose backend, maintainer scripts, `debris build` | todo |
| 4 | `feat/offline-images` | `images.py`, `images.tar` staging, `docker load` | todo |
| 5 | `feat/helpers-desktop-files` | `/usr/bin` helpers, `.desktop` entries, `files[]`, `hooks` | todo |
| 6 | `test/install-integration` | `debian:12` install → upgrade → rollback → purge test | todo |
| 7 | `docs/readme-examples` | README closed-network guide, both examples | todo |

Out of scope for v1: systemd units, k8s/Helm backends, apt-repo publishing, vendoring
dependency `.deb`s.

The full design rationale lives in `docs/design.md`.
