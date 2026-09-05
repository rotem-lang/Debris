"""Tests for the spec loader and validator.

Two things are being pinned down here. First, that defaults resolve in exactly one place,
so a key absent from the file produces the same value everywhere. Second, that every rule
in `_cross_check` fires -- those are the ones that catch a spec which is structurally valid
but would install a broken package, and they are the reason validation is hand-written.
"""

import copy
import json

import pytest

from debris.errors import SpecError
from debris.spec import HELPER_COMMANDS, load_spec


def minimal() -> dict:
    """The smallest spec that validates.

    Note what is *not* here: no `mode`, so it defaults to offline, which is why an image
    list is part of the minimum.
    """
    return {
        "schema_version": 1,
        "package": {
            "name": "acme-portal",
            "version": "1.4.2",
            "maintainer": "Ops Team <ops@corp.local>",
            "description": "ACME Portal",
        },
        "deployment": {
            "source": {
                "kind": "git",
                "url": "ssh://git@git.corp.local/apps/acme-portal.git",
                "ref": "v1.4.2",
            },
            "images": ["registry.corp.local:5000/acme/portal:1.4.2"],
        },
    }


def write(tmp_path, spec) -> str:
    path = tmp_path / "spec.json"
    path.write_text(json.dumps(spec) if isinstance(spec, dict) else spec)
    return str(path)


def load(tmp_path, spec, **kwargs):
    return load_spec(write(tmp_path, spec), **kwargs)


def problems(tmp_path, spec, **kwargs) -> str:
    with pytest.raises(SpecError) as exc:
        load(tmp_path, spec, **kwargs)
    return str(exc.value)


def edited(**sections) -> dict:
    """A minimal spec with sections merged in one level deep."""
    spec = copy.deepcopy(minimal())
    for name, value in sections.items():
        if isinstance(value, dict) and isinstance(spec.get(name), dict):
            spec[name] = {**spec[name], **value}
        else:
            spec[name] = value
    return spec


# --------------------------------------------------------------------------------------
# Defaults
# --------------------------------------------------------------------------------------


def test_minimal_spec_resolves_every_default(tmp_path):
    spec = load(tmp_path, minimal())

    assert spec.package.architecture == "all"
    assert spec.package.section == "misc"
    assert spec.package.priority == "optional"
    assert spec.package.depends == []
    assert spec.package.long_description is None

    assert spec.install.prefix == "/opt"
    assert spec.install.dir_name == "acme-portal"
    assert spec.install.version_dir == "1.4.2"
    assert spec.install.current_symlink is True
    assert spec.install.start_on_install is False
    assert spec.install.stop_on_remove is True

    assert spec.deployment.kind == "compose"
    assert spec.deployment.compose_files == ["docker-compose.yml"]
    assert spec.deployment.extra_files == []
    assert spec.deployment.registry.host is None
    assert spec.deployment.remove_image_archive_after_load is False

    assert spec.helpers.enabled is True
    assert spec.helpers.prefix == "acme-portal"
    assert spec.helpers.commands == list(HELPER_COMMANDS)

    assert spec.desktop_entries == []
    assert spec.files == []
    assert spec.hooks.postinst is None


def test_mode_defaults_to_offline(tmp_path):
    """The closed network is the normal case, so offline is what you get by not choosing.

    This is the other half of `--mode` having no argparse default: absent means "ask the
    spec", and the spec answers here.
    """
    assert load(tmp_path, minimal()).deployment.mode == "offline"


def test_env_template_defaults_to_none(tmp_path):
    """Assuming a '.env.template' would break every app that ships no env file.

    The failure would only appear once the fetch could not find it.
    """
    assert load(tmp_path, minimal()).deployment.env.template is None


def test_install_paths(tmp_path):
    install = load(tmp_path, minimal()).install
    assert install.root_dir == "/opt/acme-portal"
    assert install.target_dir == "/opt/acme-portal/1.4.2"
    assert install.current_dir == "/opt/acme-portal/current"


def test_helper_command_names(tmp_path):
    names = load(tmp_path, minimal()).helpers.command_names()
    assert names[0] == "acme-portal-start"
    assert "acme-portal-compose" in names


def test_dir_name_and_version_dir_follow_the_package(tmp_path):
    spec = load(tmp_path, edited(package={"name": "other-app", "version": "2.0.0"}))
    assert spec.install.target_dir == "/opt/other-app/2.0.0"


def test_install_overrides_win_over_package_derived_defaults(tmp_path):
    spec = load(
        tmp_path, edited(install={"prefix": "/srv", "dir_name": "portal", "version_dir": "next"})
    )
    assert spec.install.target_dir == "/srv/portal/next"


# --------------------------------------------------------------------------------------
# The --mode override
# --------------------------------------------------------------------------------------


def test_mode_override_replaces_the_spec_value(tmp_path):
    spec = edited(deployment={**minimal()["deployment"], "mode": "offline"})
    spec["deployment"]["registry"] = {"host": "registry.corp.local:5000"}
    assert load(tmp_path, spec, mode="online").deployment.mode == "online"


def test_mode_override_decides_which_cross_checks_apply(tmp_path):
    """A spec that is valid online is not automatically valid offline.

    `--mode offline` needs an image list the online spec never had to provide.
    """
    spec = minimal()
    spec["deployment"]["mode"] = "online"
    spec["deployment"]["registry"] = {"host": "registry.corp.local:5000"}
    del spec["deployment"]["images"]

    load(tmp_path, spec)  # valid as written
    assert "at least one image is required" in problems(tmp_path, spec, mode="offline")


def test_mode_override_is_checked(tmp_path):
    assert "unknown mode 'airgapped'" in problems(tmp_path, minimal(), mode="airgapped")


def test_override_does_not_hide_a_bad_mode_in_the_file(tmp_path):
    """`validate` has no `--mode`.

    A spec that only builds because the flag masked a typo would fail the moment someone
    validated it.
    """
    spec = minimal()
    spec["deployment"]["mode"] = "ofline"
    assert "deployment.mode" in problems(tmp_path, spec, mode="offline")


# --------------------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------------------


def test_all_problems_are_reported_in_one_run(tmp_path):
    """One `validate` should be enough to fix everything, not the first thing."""
    spec = edited(package={"name": "Bad_Name", "maintainer": "ops"})
    spec["deployment"]["images"] = ["registry.corp.local:5000/acme/portal"]

    report = problems(tmp_path, spec)
    assert "3 problems" in report
    assert "package.name" in report
    assert "package.maintainer" in report
    assert "deployment.images[0]" in report


def test_a_single_problem_is_not_pluralised(tmp_path):
    assert "1 problem\n" in problems(tmp_path, edited(package={"maintainer": "ops"}))


def test_one_mistake_produces_one_message(tmp_path):
    """A missing `package.name` must not also be blamed on the keys that derive from it.

    `install.dir_name` and `helpers.prefix` both default to the package name.
    """
    spec = minimal()
    del spec["package"]["name"]

    report = problems(tmp_path, spec)
    assert "1 problem\n" in report
    assert "package.name: required key is missing" in report


def test_missing_file(tmp_path):
    with pytest.raises(SpecError, match="no such file"):
        load_spec(tmp_path / "absent.json")


def test_invalid_json_reports_a_position(tmp_path):
    assert "invalid JSON" in problems(tmp_path, '{"schema_version": 1,}')


def test_top_level_must_be_an_object(tmp_path):
    assert "expected a JSON object, got a list" in problems(tmp_path, "[]")


def test_unsupported_schema_version(tmp_path):
    assert "unsupported schema version 2" in problems(tmp_path, edited(schema_version=2))


# --------------------------------------------------------------------------------------
# Field validation
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["acme-portal", "app2", "lib+tool", "a.b", "x9"])
def test_accepts_debian_package_names(tmp_path, name):
    assert load(tmp_path, edited(package={"name": name})).package.name == name


@pytest.mark.parametrize("name", ["Acme", "acme_portal", "a", "-acme", "acme portal", ""])
def test_rejects_non_debian_package_names(tmp_path, name):
    assert "package.name" in problems(tmp_path, edited(package={"name": name}))


@pytest.mark.parametrize("version", ["1.4.2", "1.4.2-1", "2024.05.1", "1.0~rc1", "1.0+deb12u1"])
def test_accepts_debian_versions(tmp_path, version):
    assert load(tmp_path, edited(package={"version": version})).package.version == version


@pytest.mark.parametrize("version", ["v1.4.2", "1:1.4.2", "1.4 2", ""])
def test_rejects_versions_dpkg_would_refuse(tmp_path, version):
    assert "package.version" in problems(tmp_path, edited(package={"version": version}))


def test_epoch_rejection_explains_itself(tmp_path):
    assert "epochs are not supported" in problems(tmp_path, edited(package={"version": "1:1.0"}))


@pytest.mark.parametrize("maintainer", ["ops", "Ops Team", "<ops@corp.local>", "Ops <ops>"])
def test_rejects_malformed_maintainers(tmp_path, maintainer):
    assert "package.maintainer" in problems(tmp_path, edited(package={"maintainer": maintainer}))


def test_description_must_be_one_line(tmp_path):
    report = problems(tmp_path, edited(package={"description": "synopsis\nmore"}))
    assert "long_description" in report


def test_wrong_types_are_named(tmp_path):
    report = problems(tmp_path, edited(package={"depends": "docker-ce", "priority": 3}))
    assert "package.depends: expected a list of strings, got a string" in report
    assert "package.priority: expected a string, got a number" in report


def test_booleans_are_not_coerced(tmp_path):
    assert "expected a boolean, got a string" in problems(
        tmp_path, edited(install={"start_on_install": "yes"})
    )


def test_unknown_key_is_rejected_with_a_suggestion(tmp_path):
    """A typo'd key would otherwise be silently ignored.

    The mistake would surface as a missing feature on the target machine.
    """
    report = problems(tmp_path, edited(package={"dependes": ["docker-ce"]}))
    assert "package.dependes: unknown key; did you mean 'depends'?" in report


def test_unknown_key_with_no_near_match(tmp_path):
    report = problems(tmp_path, edited(package={"zzzzzz": 1}))
    assert "package.zzzzzz: unknown key" in report
    assert "did you mean" not in report


def test_priority_choices(tmp_path):
    assert "expected one of" in problems(tmp_path, edited(package={"priority": "urgent"}))


# --------------------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("path", ["/etc/compose.yml", "../outside/compose.yml"])
def test_source_paths_must_stay_inside_the_fetched_tree(tmp_path, path):
    spec = minimal()
    spec["deployment"]["compose_files"] = [path]
    assert "deployment.compose_files[0]" in problems(tmp_path, spec)


def test_compose_files_must_not_be_empty(tmp_path):
    spec = minimal()
    spec["deployment"]["compose_files"] = []
    assert "compose_files: must not be empty" in problems(tmp_path, spec)


def test_install_prefix_must_be_absolute(tmp_path):
    assert "install.prefix" in problems(tmp_path, edited(install={"prefix": "opt"}))


@pytest.mark.parametrize("dest", ["/usr/share/../../etc/passwd", "/opt/../etc/x"])
def test_absolute_destinations_must_not_climb_out(tmp_path, dest):
    """dpkg records the literal path, so '..' in a dest stages outside the tree."""
    (tmp_path / "logo.png").write_bytes(b"")
    spec = minimal()
    spec["files"] = [{"source": "logo.png", "dest": dest}]
    assert "must not contain '..'" in problems(tmp_path, spec)


def test_install_prefix_must_not_climb_out(tmp_path):
    assert "must not contain '..'" in problems(
        tmp_path, edited(install={"prefix": "/opt/../srv"})
    )


# --------------------------------------------------------------------------------------
# Images
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "image",
    [
        "registry.corp.local:5000/acme/portal:1.4.2",
        "acme/portal:latest",
        "registry.corp.local:5000/acme/portal@sha256:" + "a" * 64,
    ],
)
def test_accepts_pinned_image_references(tmp_path, image):
    spec = minimal()
    spec["deployment"]["images"] = [image]
    assert load(tmp_path, spec).deployment.images == [image]


def test_untagged_image_is_rejected(tmp_path):
    """An untagged reference means ':latest'.

    On a closed network that may not be in the internal registry at all -- and if it is,
    it is not the same image tomorrow.
    """
    spec = minimal()
    spec["deployment"]["images"] = ["registry.corp.local:5000/acme/portal"]
    assert "must name an explicit tag or digest" in problems(tmp_path, spec)


def test_registry_port_is_not_mistaken_for_a_tag(tmp_path):
    """':5000' is the port, not a tag, so this reference is unpinned despite the colon."""
    spec = minimal()
    spec["deployment"]["images"] = ["registry.corp.local:5000/acme/portal"]
    assert "must name an explicit tag" in problems(tmp_path, spec)

    spec["deployment"]["images"] = ["registry.corp.local:5000/acme/portal:1.4.2"]
    assert load(tmp_path, spec).deployment.images


def test_malformed_digest_is_rejected(tmp_path):
    spec = minimal()
    spec["deployment"]["images"] = ["acme/portal@sha256:beef"]
    assert "64 hex characters" in problems(tmp_path, spec)


# --------------------------------------------------------------------------------------
# Cross-field checks
# --------------------------------------------------------------------------------------


def test_offline_requires_images(tmp_path):
    spec = minimal()
    del spec["deployment"]["images"]
    assert "at least one image is required" in problems(tmp_path, spec)


def test_online_requires_a_registry_host(tmp_path):
    spec = minimal()
    spec["deployment"]["mode"] = "online"
    assert "deployment.registry.host" in problems(tmp_path, spec)


def test_online_may_still_list_images(tmp_path):
    """Keeping the list lets the same spec be built either way with `--mode`."""
    spec = minimal()
    spec["deployment"]["mode"] = "online"
    spec["deployment"]["registry"] = {"host": "registry.corp.local:5000"}
    assert load(tmp_path, spec).deployment.images


def test_env_vars_without_a_template_have_nowhere_to_go(tmp_path):
    spec = minimal()
    spec["deployment"]["env"] = {"vars": {"APP_VERSION": "1.4.2"}}
    assert "nothing to substitute into" in problems(tmp_path, spec)


def test_env_var_names_must_be_usable_in_a_dotenv_file(tmp_path):
    spec = minimal()
    spec["deployment"]["env"] = {"template": ".env.template", "vars": {"APP VERSION": "1"}}
    assert "deployment.env.vars.APP VERSION" in problems(tmp_path, spec)


def test_env_var_values_must_be_strings(tmp_path):
    spec = minimal()
    spec["deployment"]["env"] = {"template": ".env.template", "vars": {"PORT": 8080}}
    assert "quote the value" in problems(tmp_path, spec)


def test_desktop_entry_must_run_a_helper_that_exists(tmp_path):
    """Otherwise the restart button is a button that does nothing."""
    spec = minimal()
    spec["helpers"] = {"commands": ["start", "stop"]}
    spec["desktop_entries"] = [
        {"filename": "x.desktop", "name": "Restart", "exec": "acme-portal-restart"}
    ]
    report = problems(tmp_path, spec)
    assert "not one of the generated helpers" in report


def test_desktop_entry_against_disabled_helpers(tmp_path):
    spec = minimal()
    spec["helpers"] = {"enabled": False}
    spec["desktop_entries"] = [
        {"filename": "x.desktop", "name": "Restart", "exec": "acme-portal-restart"}
    ]
    assert "helpers.enabled is false" in problems(tmp_path, spec)


def test_desktop_entry_may_run_something_other_than_a_helper(tmp_path):
    spec = minimal()
    spec["desktop_entries"] = [
        {"filename": "x.desktop", "name": "Docs", "exec": "xdg-open https://wiki.corp.local"}
    ]
    assert load(tmp_path, spec).desktop_entries[0].exec.startswith("xdg-open")


def test_desktop_entry_arguments_are_ignored_when_matching_helpers(tmp_path):
    spec = minimal()
    spec["desktop_entries"] = [
        {"filename": "x.desktop", "name": "Logs", "exec": "acme-portal-logs --follow"}
    ]
    assert load(tmp_path, spec).desktop_entries[0].exec == "acme-portal-logs --follow"


def test_desktop_filenames_must_be_unique(tmp_path):
    spec = minimal()
    entry = {"filename": "x.desktop", "name": "Restart", "exec": "acme-portal-restart"}
    spec["desktop_entries"] = [entry, dict(entry, name="Restart again")]
    assert "already used by desktop_entries[0]" in problems(tmp_path, spec)


def test_desktop_filename_must_end_in_desktop(tmp_path):
    spec = minimal()
    spec["desktop_entries"] = [{"filename": "x.txt", "name": "X", "exec": "true"}]
    assert "ending in '.desktop'" in problems(tmp_path, spec)


def test_file_destinations_must_be_unique(tmp_path):
    (tmp_path / "a.png").write_bytes(b"")
    (tmp_path / "b.png").write_bytes(b"")
    spec = minimal()
    spec["files"] = [
        {"source": "a.png", "dest": "/usr/share/icons/x.png"},
        {"source": "b.png", "dest": "/usr/share/icons/x.png"},
    ]
    assert "already used by files[0]" in problems(tmp_path, spec)


def test_file_source_must_exist_beside_the_spec(tmp_path):
    spec = minimal()
    spec["files"] = [{"source": "assets/logo.png", "dest": "/usr/share/icons/logo.png"}]
    assert "does not exist" in problems(tmp_path, spec)


def test_file_source_is_resolved_relative_to_the_spec(tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "logo.png").write_bytes(b"")
    spec = minimal()
    spec["files"] = [{"source": "assets/logo.png", "dest": "/usr/share/icons/logo.png"}]
    assert load(tmp_path, spec).files[0].mode == "0644"


def test_file_mode_must_be_octal(tmp_path):
    (tmp_path / "logo.png").write_bytes(b"")
    spec = minimal()
    spec["files"] = [{"source": "logo.png", "dest": "/usr/share/x.png", "mode": "rwxr-xr-x"}]
    assert "octal mode" in problems(tmp_path, spec)


@pytest.mark.parametrize("mode", ["4755", "2755", "1777"])
def test_setuid_and_sticky_modes_are_out_of_reach(tmp_path, mode):
    """dpkg wants a `dpkg-statoverride` for these.

    Nothing Debris ships needs one, and a spec file is the wrong place to grant them by
    accident.
    """
    (tmp_path / "logo.png").write_bytes(b"")
    spec = minimal()
    spec["files"] = [{"source": "logo.png", "dest": "/usr/share/x.png", "mode": mode}]
    assert "setuid, setgid and sticky bits are not supported" in problems(tmp_path, spec)


def test_hooks_must_exist_beside_the_spec(tmp_path):
    spec = minimal()
    spec["hooks"] = {"postinst": "hooks/after.sh"}
    assert "hooks.postinst: 'hooks/after.sh' does not exist" in problems(tmp_path, spec)


def test_hooks_are_loaded_when_present(tmp_path):
    (tmp_path / "hooks").mkdir()
    (tmp_path / "hooks" / "after.sh").write_text("echo hi\n")
    spec = minimal()
    spec["hooks"] = {"postinst": "hooks/after.sh"}
    assert load(tmp_path, spec).hooks.postinst == "hooks/after.sh"


# --------------------------------------------------------------------------------------
# Sources
# --------------------------------------------------------------------------------------


def test_git_source_requires_url_and_ref(tmp_path):
    spec = minimal()
    spec["deployment"]["source"] = {"kind": "git"}
    report = problems(tmp_path, spec)
    assert "deployment.source.url: required key is missing" in report
    assert "deployment.source.ref: required key is missing" in report


def test_local_source_reads_a_directory(tmp_path):
    (tmp_path / "checkout").mkdir()
    spec = minimal()
    spec["deployment"]["source"] = {"kind": "local", "path": "checkout"}
    source = load(tmp_path, spec).deployment.source
    assert source.kind == "local"
    assert source.url is None


def test_local_source_directory_must_exist(tmp_path):
    spec = minimal()
    spec["deployment"]["source"] = {"kind": "local", "path": "checkout"}
    assert "is not a directory" in problems(tmp_path, spec)


def test_local_source_rejects_git_only_keys(tmp_path):
    """A half-converted spec would otherwise look pinned to a ref that is never used."""
    (tmp_path / "checkout").mkdir()
    spec = minimal()
    spec["deployment"]["source"] = {
        "kind": "local",
        "path": "checkout",
        "ref": "v1.4.2",
    }
    assert 'is not used when source.kind is "local"' in problems(tmp_path, spec)


def test_unknown_source_kind(tmp_path):
    spec = minimal()
    spec["deployment"]["source"] = {"kind": "svn", "url": "x", "ref": "y"}
    assert "deployment.source.kind" in problems(tmp_path, spec)


def test_unknown_backend_kind(tmp_path):
    spec = minimal()
    spec["deployment"]["kind"] = "helm"
    assert "deployment.kind" in problems(tmp_path, spec)
