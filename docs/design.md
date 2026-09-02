# Debris — generic `.deb` builder for docker-compose apps

## Context

`Debris` is currently an empty repo (`README.md` + `.gitignore` only, marked as a Python module by the IDE config). The goal is to build the tool from scratch.

The problem: several internal apps are all deployed the same way — docker images driven by `docker compose` v2 — and each one needs to be installable on Debian/Ubuntu machines that sit on a **closed network** (no internet, internal git server, internal docker registry, internal apt mirror). Today that means hand-rolling a `.deb` per app.

Debris replaces that with one build tool driven by a **JSON spec per app**: it fetches the app's compose file from git, renders `.env` from a template using values in the spec, optionally bakes the docker images in for fully air-gapped installs, and emits a `.deb` that drops everything under `/opt/<pkg>/<version>/` plus optional `/usr/bin` helpers and desktop launchers (e.g. a "Restart" button).

Design decisions confirmed with the user:

| Area | Decision |
|---|---|
| Image delivery | Single `mode` switch per spec: `online` → `postinst` pulls from the internal registry; `offline` → images baked into the `.deb` and `docker load`ed |
| Compose source | Fetched from git at a pinned ref + subpath (a `local` source also supported for dev/CI) |
| `.env` | Template fetched alongside compose, `${VAR}` placeholders substituted from spec values; missing placeholder = build failure |
| Build method | Stage a filesystem tree, generate `DEBIAN/*`, run `dpkg-deb --build` (no debhelper needed) |
| Offline image list | Explicit list in the JSON spec |
| Install layout | `/opt/<pkg>/<version>/` shipped as ordinary dpkg-tracked files, with a `current` symlink |
| Versions / rollback | One version installed at a time — dpkg replaces the old one on upgrade. Rollback = keep every built `.deb` in the internal apt mirror and reinstall an older one |
| Runtime | **No systemd for now.** Optional `/usr/bin` start/stop helpers + optional `.desktop` entries |
| Deb deps | `Depends:` configurable per spec; the internal apt mirror is the target's own apt config |

Non-goals for v1: systemd units, k8s/Helm backends, apt-repo publishing, vendoring dependency `.deb`s. The code is structured so each can be added without a rewrite.

---

## Stack

- **Python 3.12, standard library only** at runtime. A closed network makes every pip dependency a liability, so no `jsonschema`/`PyYAML`/`requests`. Validation is hand-written with precise error messages; `git` and `docker` are invoked as subprocesses.
- **No install step and no packaging config.** Debris is delivered by `git bundle`-ing the
  repository into the closed network and running it from the checkout as `python3 -m debris`.
  This is only possible while the stdlib-only rule holds.
- `pytest` is the only dev tool, installed into a throwaway `.venv`. There is no linter or
  formatter — style is a review concern. Tests run as
  `PYTHONPATH=. .venv/bin/pytest`, since Debris is never installed.
- Verified available on this machine: `dpkg-deb`, `dpkg-buildpackage`, `docker`, Python 3.12. **`docker compose` (v2 plugin) is not installed here** — offline-mode image baking only needs `docker pull`/`docker save`, so builds work, but any test that shells out to `docker compose` must skip when the plugin is absent.

---

## The JSON spec

This is the core deliverable — everything else is machinery around it. A single file fully describes one app's package.

```jsonc
{
  "schema_version": 1,

  "package": {
    "name": "acme-portal",
    "version": "1.4.2",
    "architecture": "all",
    "maintainer": "Ops Team <ops@corp.local>",
    "description": "ACME Portal",
    "long_description": "Multi-line extended description.",
    "section": "misc",
    "priority": "optional",
    "homepage": "https://wiki.corp.local/acme-portal",
    "depends":    ["docker-ce", "docker-compose-plugin"],
    "recommends": [],
    "conflicts":  [],
    "replaces":   []
  },

  "install": {
    "prefix": "/opt",                 // -> /opt/acme-portal/1.4.2
    "dir_name": "acme-portal",        // defaults to package.name
    "version_dir": "1.4.2",           // defaults to package.version
    "current_symlink": true,          // /opt/acme-portal/current -> 1.4.2
    "start_on_install": false,        // postinst does NOT bring the stack up by default
    "stop_on_remove": true            // prerm runs `docker compose down`
  },

  "deployment": {
    "kind": "compose",                // future: "helm" | "manifests"
    "mode": "online",                 // "online" | "offline"; defaults to "offline" if absent

    "source": {
      "kind": "git",                  // "git" | "local"
      "url": "ssh://git@gitlab.corp.local/apps/acme-portal.git",
      "ref": "v1.4.2",                // tag, branch, or full SHA
      "path": "deploy",               // subpath inside the repo
      "insecure_tls": false
    },

    "compose_files": ["docker-compose.yml"],
    "extra_files": ["config/nginx.conf"],   // copied verbatim from the source
    "render_templates": [],                 // extra fetched files to run ${VAR} substitution on

    "env": {
      "template": ".env.template",    // path within source.path; null = no env file
      "output": ".env",
      "strict": true,                 // unresolved ${VAR} -> build error
      "vars": {
        "APP_VERSION": "1.4.2",
        "REGISTRY": "registry.corp.local:5000",
        "DATA_DIR": "/var/lib/acme-portal"
      }
    },

    "registry": {
      "host": "registry.corp.local:5000",
      "require_login": false          // online mode: postinst fails early if not logged in
    },

    // Required when mode == "offline". Baked via `docker save` at build time.
    "images": [
      "registry.corp.local:5000/acme/portal:1.4.2",
      "registry.corp.local:5000/acme/worker:1.4.2"
    ],
    "remove_image_archive_after_load": false
  },

  "helpers": {
    "enabled": true,
    "prefix": "acme-portal",          // -> /usr/bin/acme-portal-start, -stop, ...
    "commands": ["start", "stop", "restart", "status", "logs", "compose"]
  },

  "desktop_entries": [
    {
      "filename": "acme-portal-restart.desktop",
      "name": "Restart ACME Portal",
      "comment": "Restart the ACME Portal stack",
      "exec": "acme-portal-restart",
      "icon": "acme-portal",
      "terminal": true,
      "categories": ["System", "Utility"]
    }
  ],

  "files": [
    { "source": "assets/acme.png",
      "dest": "/usr/share/icons/hicolor/128x128/apps/acme-portal.png",
      "mode": "0644" }
  ],

  "hooks": {
    "postinst": "hooks/acme-postinst.sh",   // appended to the generated script
    "prerm": null,
    "postrm": null
  }
}
```

`files[].source` and `hooks.*` resolve relative to the spec file's own directory, so a spec plus its assets is a self-contained folder.

---

## Package layout

Everything ships as ordinary dpkg-tracked files — no postinst unpacking, no indirection:

```
/opt/acme-portal/1.4.2/docker-compose.yml
/opt/acme-portal/1.4.2/.env
/opt/acme-portal/1.4.2/config/nginx.conf
/opt/acme-portal/1.4.2/.debris-manifest.json
/opt/acme-portal/1.4.2/images/images.tar        # offline mode only
/opt/acme-portal/current -> 1.4.2               # relative symlink, shipped in the .deb
/usr/bin/acme-portal-{start,stop,restart,status,logs,compose}
/usr/share/applications/acme-portal-restart.desktop
/usr/share/icons/hicolor/128x128/apps/acme-portal.png
```

The `current` symlink is staged as a real relative symlink inside the archive rather than being created by `postinst` — dpkg unpacks and replaces symlinks correctly, so upgrades and downgrades repoint it with no maintainer-script logic at all.

**Upgrade semantics.** Installing `1.5.0` upgrades the same package name, so after unpacking dpkg deletes the files `1.4.2` owned and prunes its directory. One version on disk at a time; `current` follows automatically. Rollback is `dpkg -i acme-portal_1.4.2_all.deb`, or `apt install acme-portal=1.4.2` once every build is archived in the internal mirror — so **every `.deb` Debris produces must be kept**, which the README will call out. `apt-mark hold` after a deliberate downgrade prevents the next `apt upgrade` from undoing it.

**Consequence to document:** never bind-mount runtime data inside `/opt/<pkg>/<version>/`. dpkg removes only the files it owns, so a `./data` bind-mount would survive as an orphaned directory while its sibling compose file vanishes. Named volumes, or a path like `/var/lib/<pkg>` passed in through an env var, are the right answer — hence `DATA_DIR` in the example spec.

**Provenance.** `.debris-manifest.json` records the resolved git commit SHA, image digests (`docker inspect` after pull), a hash of the spec file, the Debris version and the build timestamp. On a closed network that is the audit trail for "what exactly is running on this box", and `debris inspect` reads it back out of a `.deb`.

---

## Repo layout

```
debris/
  __main__.py            cli.py            errors.py
  spec.py                # dataclasses + loader + hand-written validator
  sources/               __init__.py (Source protocol + registry)
                         git.py    # shallow fetch, sparse-checkout of source.path
                         local.py  # copy from a directory
  backends/              __init__.py (Backend protocol + registry)
                         compose.py  # the only v1 backend; k8s slots in here later
  render.py              # ${VAR} substitution, strict-mode reporting
  images.py              # docker pull / save / inspect-digest
  staging.py             # build the tree under a temp dir
  control.py             # DEBIAN/control, md5sums, maintainer scripts
  dpkg.py                # dpkg-deb --build, .deb filename conventions
  builder.py             # orchestration
  templates/             postinst.sh  prerm.sh  postrm.sh
                         helper.sh    desktop.entry
schema/debris.schema.json    # editor autocomplete only, not runtime validation
examples/online-app/  examples/offline-app/
tests/
README.md  CLAUDE.md
```

Two registries (`sources`, `backends`) keep the extension points explicit — a future `backends/helm.py` implements the same protocol and the CLI needs no changes.

**Backend protocol** (`backends/__init__.py`): `validate(spec)`, `fetch(spec, workdir)`, `stage(spec, workdir, tree)`, `helper_command(name) -> str`, `postinst_lines(spec)`, `prerm_lines(spec)`. `compose.py` is the only implementation in v1.

---

## Generated maintainer scripts

`set -eu` POSIX shell rendered from `debris/templates/` with values substituted at build time — no runtime templating on the target. All idempotent, since dpkg may call them more than once.

- **`postinst configure`** — verify `docker` and `docker compose version` exist, failing with an actionable message if not; then either `docker load -i .../images/images.tar` (offline, optionally deleting the archive afterwards) or `docker compose pull` (online, preceded by a `docker login` check when `require_login`); `docker compose up -d` only if `start_on_install`; finally append `hooks.postinst`.
- **`prerm remove|upgrade`** — if `stop_on_remove`, `cd` into this version's directory and `docker compose down`, guarded so a missing directory or an already-stopped stack is not an error.
- **`postrm purge`** — `rm -rf /opt/<pkg>` to clear anything untracked left behind. `postrm remove` touches nothing.

The ordering that matters: on upgrade the **old** package's `prerm` runs before the **new** package's `postinst`, so the running stack is torn down before the new compose file lands.

---

## Helper scripts

One dispatcher template rendered per command into `/usr/bin/<prefix>-<command>`. Each resolves `/opt/<pkg>/current` at call time rather than a baked version path, so the helpers keep working across upgrades and downgrades untouched:

```sh
docker compose --project-name <pkg> --env-file /opt/<pkg>/current/.env \
               -f /opt/<pkg>/current/docker-compose.yml <args>
```

`start`/`stop`/`restart`/`status`/`logs` map to `up -d`/`down`/`down && up -d`/`ps`/`logs -f`, and `compose` passes arguments straight through as an admin escape hatch. Desktop entries invoke these same helpers, which is how the "Restart" button works.

---

## CLI

```
python3 -m debris validate <spec.json>              # schema + cross-field checks, no network
python3 -m debris build    <spec.json> [-o dist/] [--mode online|offline] [--var K=V]
                            [--source-dir DIR] [--work-dir DIR] [--keep-work]
python3 -m debris init     <name> [--offline]       # scaffold a spec + assets dir
python3 -m debris inspect  <file.deb>               # print the embedded .debris-manifest.json
```

`--var` overrides `deployment.env.vars` for CI. `--source-dir` substitutes a local checkout for the git fetch — fast iteration, and the escape hatch when the build host can't reach git. Output follows Debian convention: `<name>_<version>_<arch>.deb`.

Cross-field validation worth calling out, since these are the failures that would otherwise surface as a broken package on a machine that's awkward to reach: `mode: offline` requires a non-empty `images` list; `mode: online` requires `registry.host`; every `desktop_entries[].exec` that looks like a helper must match a generated helper name; `package.name` and `package.version` must match Debian's allowed character sets; `files[].source` must exist relative to the spec.

---

## Execution plan — one branch per step

Branches follow the existing `ref/slim-gitignore` convention (`<type>/<kebab-case>`), cut from `dev` and merged back to `dev`. `main` stays release-only.

| # | Branch | Scope | Depends on |
|---|---|---|---|
| 0 | `chore/scaffold` | `CLAUDE.md`, `docs/design.md`, `debris/` package with `cli.py` argparse skeleton, `tests/` smoke tests, `.gitignore` touch-up | — |
| 1 | `feat/spec-validation` | `spec.py` dataclasses + loader + hand-written validator (incl. `deployment.mode` defaulting to `"offline"`), `errors.py`, `schema/debris.schema.json`, `debris validate`, `debris init` | 0 |
| 2 | `feat/sources-and-render` | `sources/` (protocol + registry, `local.py`, `git.py`), `render.py` | 1 |
| 3 | `feat/deb-build` | `staging.py`, `control.py`, `dpkg.py`, `builder.py`, `backends/compose.py`, maintainer-script templates, `debris build`, `debris inspect` | 2 |
| 4 | `feat/offline-images` | `images.py`, `images/images.tar` staging, `docker load` in postinst | 3 |
| 5 | `feat/helpers-desktop-files` | `/usr/bin` helper generation, `.desktop` entries, `files[]` mapping, `hooks[]` injection | 3 |
| 6 | `test/install-integration` | The `debian:12` container install → upgrade → rollback → purge test | 3 |
| 7 | `docs/readme-examples` | README closed-network guide, `examples/online-app`, `examples/offline-app` | 4, 5 |

**Sequencing.** 0→1→2→3 is a hard chain — each needs the previous one's types to exist. Once 3 lands, **4, 5 and 6 are independent and can run in parallel**; 7 closes it out. Branch 3 is the large one and is the natural place to stop and review, since it produces the first installable `.deb`.

**Definition of done per branch:** `pytest` green, and for 3–6 an artifact or container assertion actually exercised — not just unit tests.

### Branch 0 detail: `CLAUDE.md`

Written first so every later session starts with the context this planning conversation produced. Contents:

- **What Debris is** — one paragraph, plus the closed-network constraint that motivates everything.
- **Hard constraints** — stdlib-only at runtime (no pip deps to mirror); `git`/`docker`/`dpkg-deb` as subprocesses; build must work with no internet and no debhelper.
- **Architecture** — the spec-file-driven pipeline (fetch → render → stage → `dpkg-deb`), the `sources/` and `backends/` registries and why they exist (k8s later), and the install layout.
- **The decisions that aren't obvious from the code**, each with its reasoning: why one version on disk at a time (dpkg deletes the old version's files on upgrade, so multi-version coexistence under a single package name is not possible); why rollback is "archive every `.deb`" rather than a symlink flip; why `current` is a shipped symlink instead of postinst logic; why offline image lists are explicit in the spec rather than parsed from compose (avoids a YAML dependency); why runtime data must not be bind-mounted inside the version directory.
- **Commands** — `pytest`, `python3 -m debris build examples/online-app/spec.json -o dist/ --source-dir ...`.
- **Conventions** — branch naming, `dev` as the integration branch, POSIX `sh` for generated scripts.
- **Status** — the branch table above, with what's landed.

---

## Verification

Everything below runs on this machine — no debhelper, no internet.

**Unit** (`pytest`): validation rules; env rendering including strict failures and `$`-containing values; control-file field ordering and multi-line description folding; `.deb` filename generation; symlink staging.

**Build integration** — build `examples/online-app` with `--source-dir` (no network) and assert on the artifact:
```bash
dpkg-deb -I dist/acme-portal_1.4.2_all.deb        # control fields, Depends
dpkg-deb -c dist/acme-portal_1.4.2_all.deb        # payload paths, modes, symlink target
dpkg-deb --fsys-tarfile ... | tar -xO ./opt/acme-portal/1.4.2/.debris-manifest.json
```
Shell-lint the generated maintainer scripts with `sh -n`, plus `shellcheck` when present.

**Install integration** — a `debian:12` container test, skipped when the docker daemon is unreachable. This is the test that pins down the upgrade behaviour the whole layout depends on:
1. `dpkg -i` the 1.4.2 build → assert `/opt/acme-portal/1.4.2/{docker-compose.yml,.env}` exist and `current` resolves to `1.4.2`.
2. `dpkg -i` a 1.5.0 build → assert `1.5.0` is present, **`/opt/acme-portal/1.4.2` is gone**, and `current` now resolves to `1.5.0`.
3. `dpkg -i` the 1.4.2 build again (the rollback path) → assert `current` is back on `1.4.2`.
4. `dpkg --purge` → assert `/opt/acme-portal` is gone entirely.

**Offline mode** — needs a reachable registry, so the test stands up a throwaway local `registry:2` container with a tiny image pushed to it, builds with `--mode offline`, and asserts `images/images.tar` is in the payload and `docker load` succeeds. Skipped when docker is unavailable.

**Manual smoke** — `python3 -m debris init demo && python3 -m debris validate demo/demo.json && python3 -m debris build demo/demo.json -o dist/`.
