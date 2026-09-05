# Debris code standards

Read by `debris-implementer` and `debris-reviewer` before they touch code. This file is the
authority for structure; `CLAUDE.md` is the authority for architecture and constraints.

**Structure is not style.** A reviewer once waved through a 1159-line `spec.py` because its
instructions said not to report style preferences. Formatting and naming taste are style.
Module size, function size, nesting depth and mixed responsibilities are structure, and they
are the difference between a change taking ten minutes and taking a day. They are reportable
defects and they block a change from being called done.

## Budgets

| Limit | Value | On breach |
|---|---|---|
| Module | 400 lines | Split it into modules with distinct responsibilities |
| Function / method | 40 lines including its docstring; aim for under 20 | Extract the named steps |
| Nesting depth inside a function | 3 | Guard-clause the early returns, extract the inner block |
| Parameters | 5 | Pass a dataclass, or the function does too much |
| `if`/`elif` chain dispatching on a value | 3 branches | Table, dict or registry keyed by that value |

These are limits, not targets — do not pad or split to hit a number. Exceeding one is
allowed when the alternative is genuinely worse, but the file must then carry a comment
saying why. An uncommented breach is a defect.

## Measure, do not eyeball

```bash
python3 - <<'EOF'
import ast, pathlib
for path in sorted(pathlib.Path("debris").rglob("*.py")):
    source = path.read_text()
    lines = len(source.splitlines())
    if lines > 400:
        print(f"MODULE {lines:5d}  {path}")
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            length = node.end_lineno - node.lineno + 1
            if length > 40:
                print(f"FUNC   {length:5d}  {path}:{node.lineno}  {node.name}")
EOF
```

Run this against any module you changed or reviewed. Silence means you are inside budget.

## SRP — one module, one reason to change

A module holds one concern. If you cannot name that concern in a short phrase without
"and", it is more than one module.

These concerns never share a file:

- Data shapes (dataclasses) and the logic that populates them
- Error/problem accumulation and the code that reports problems
- Low-level parsing primitives and the domain rules built on them
- Per-section readers and the cross-section rules that run after them
- Anything that shells out (`git`, `docker`, `dpkg-deb`) and anything that decides *what* to
  shell out about

### Worked example: the `spec.py` split

`debris/spec.py` is the live case — 1159 lines mixing all five concerns above. The shape to
move toward, as a package so that `from debris.spec import load_spec, Spec` keeps working:

```
debris/spec/
    __init__.py     re-exports load_spec, Spec and the section dataclasses
    model.py        dataclasses only, no logic beyond derived properties
    problems.py     _Problems
    reader.py       _Reader primitives: string, boolean, string_list, child, reject_unknown
    values.py       value-level rules: _image_problem, _relative_path_problem, _closest
    sections.py     _read_package, _read_install, _read_deployment, ...
    crosscheck.py   _cross_check and the _check_* helpers
```

Each file names one reason to change. Adding a spec key touches `sections.py`; tightening
image-reference rules touches `values.py`; neither makes you scroll past the other.

## OCP — extend by adding a file, not by editing a chain

`sources/` and `backends/` are registries for a reason: a new source kind or backend is a new
file plus a registration, never a new `elif` in a dispatcher someone else owns. Hold that
line when you add anything with variants — spec section kinds, image handling, helper script
kinds. If adding the second variant of something means editing three existing functions, the
first variant was built wrong; fix it as part of adding the second.

## LSP, ISP, DIP in this repo

- **LSP.** Every `Source` is substitutable for every other. Same return contract, same
  exception types, no "this one also needs `prepare()` called first". `local.py` and `git.py`
  are interchangeable from the builder's view or the protocol is a lie.
- **ISP.** Protocols stay minimal. Do not add a method to `Source` that only `git.py` can
  implement and `local.py` has to stub with `pass` or `raise NotImplementedError`.
- **DIP.** `builder.py` depends on the `Source` and `Backend` protocols, never on `git.py` or
  `compose.py` directly. Subprocess calls live behind a seam so tests can run without a
  docker daemon — that is also what makes the skip-when-unavailable rule in `CLAUDE.md`
  cheap to honour.

## Functions

A function does one thing at one level of abstraction. A 50-line function that reads as
*validate, then normalise, then assemble* is three functions and a four-line caller.

- Guard clauses over nested `if`. Return early on the bad case.
- Name the extracted step for *what it decides*, not for where it sits: `_image_problem`,
  not `_check_part_two`.
- A comment introducing a block ("# now resolve the paths") is the extraction telling you
  where the seam is. Make it a function name.

## Formatting

There is no formatter, so these are enforced by review. They are not preferences — every one
is derived from what the existing code already does, so "match the surrounding code" and
"follow this list" give the same answer.

- **Line length: 96, for code and prose alike.** One limit, because two limits bought
  nothing: an earlier draft wrapped comments at 90 to match the `# ----` banners, which made
  28 lines "violations" for being 1–4 characters over, while the same rules call for deleting
  those banners. A rule whose only effect is reflowing prose by a word is noise.
- **Double quotes.** Single quotes only to avoid escaping an embedded double quote, as in
  `'mode "offline" bakes the images into the .deb'`.
- **Four-space indent.** A wrapped `if (...)` condition indents 8, so the condition cannot be
  misread as the body:

  ```python
  if (
          deployment.mode == "online"
          and not deployment.registry.host
  ):
      problems.add(...)
  ```

- **Multi-line calls and collections:** if the arguments fit on a single continuation line,
  wrap them there and stop. Otherwise one element per line, trailing comma after the last,
  and the closing bracket alone on a line at the statement's indent. Both forms are already
  in use and both are correct; what is wrong is one element per line *without* the trailing
  comma, or mixing the two inside one call.
- **Imports:** three blocks separated by one blank line — stdlib, third-party (`pytest`, in
  tests only), then `debris.*`. Inside a block, plain `import x` before `from x import y`,
  each group sorted, and the names inside a `from x import a, b, c` sorted too.
- **Blank lines:** two before a top-level `def`, `class` or decorator; one between methods.
- **Docstrings:** `"""Single line, ending in a period."""` Multi-line is a one-line summary,
  a blank line, then prose wrapped at 90, with the closing `"""` on its own line.
- **Naming:** full words over abbreviations (`component`, not `comp`), `_leading_underscore`
  for module-private, `UPPER_SNAKE` for module constants.
- **Error messages** quote user-supplied values with `!r`: `f"{ref!r} must not contain
  whitespace"`. The value the user typed must be visible in the message.
- **No new section banners.** The `# ----` dividers in `spec.py` mark what should have been
  separate modules. Once a file is split, the filename does that job. Adding a banner is a
  signal to split instead.

## Do not over-correct

Splitting badly is its own defect, and this repo is stdlib-only, run from a checkout, with
no framework to hide indirection. Do not:

- Introduce an interface or protocol with one implementation and no second one planned
- Create one-function modules, or a package where two modules would do
- Add a layer that has exactly one caller and only forwards arguments
- Turn a function into a class because it feels more object-oriented, or add getters and
  setters around plain dataclass fields
- Split a cohesive 60-line function into six 10-line functions that are only ever called in
  sequence by one caller — that moves the reading, it does not reduce it

The test for a split: after it, can each piece be read, changed or tested without the
others in front of you? If not, you have moved lines, not separated concerns.
