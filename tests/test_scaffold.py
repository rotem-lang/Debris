"""Tests for `debris init`.

The one that matters is `test_scaffold_validates`: a scaffold that does not pass
`debris validate` makes the first thing a new user does fail, and leaves them debugging
Debris instead of their app.
"""

import json

import pytest

from debris.errors import SpecError
from debris.scaffold import scaffold_spec, write_scaffold
from debris.spec import load_spec


@pytest.mark.parametrize("offline", [False, True])
def test_scaffold_validates_unchanged(tmp_path, offline):
    path = write_scaffold("acme-portal", is_offline=offline, directory=tmp_path)
    spec = load_spec(path)
    assert spec.package.name == "acme-portal"
    assert spec.deployment.mode == ("offline" if offline else "online")


def test_offline_scaffold_lists_images(tmp_path):
    spec = load_spec(write_scaffold("acme-portal", is_offline=True, directory=tmp_path))
    assert spec.deployment.images == ["registry.corp.local:5000/acme-portal/app:0.1.0"]


def test_online_scaffold_names_a_registry(tmp_path):
    spec = load_spec(write_scaffold("acme-portal", is_offline=False, directory=tmp_path))
    assert spec.deployment.registry.host == "registry.corp.local:5000"


def test_scaffold_ships_a_working_restart_button(tmp_path):
    """The desktop entry has to name a helper that is actually generated.

    That is exactly what the cross-check in the validator enforces.
    """
    spec = load_spec(write_scaffold("acme-portal", is_offline=False, directory=tmp_path))
    entry = spec.desktop_entries[0]
    assert entry.exec == "acme-portal-restart"
    assert entry.exec in spec.helpers.command_names()


def test_scaffold_keeps_data_out_of_the_version_directory(tmp_path):
    """The scaffold must not point anything persistent at /opt/<pkg>/<version>.

    dpkg deletes that directory on upgrade, so anything living there is lost.
    """
    spec = load_spec(write_scaffold("acme-portal", is_offline=False, directory=tmp_path))
    assert spec.deployment.env.vars["DATA_DIR"] == "/var/lib/acme-portal"
    assert not spec.deployment.env.vars["DATA_DIR"].startswith(spec.install.root_dir)


def test_scaffold_writes_readable_json(tmp_path):
    path = write_scaffold("acme-portal", is_offline=False, directory=tmp_path)
    text = path.read_text()
    assert text.endswith("\n")
    assert '\n  "package"' in text  # indented, not a single line
    assert json.loads(text)


def test_init_refuses_to_clobber_an_edited_spec(tmp_path):
    write_scaffold("acme-portal", is_offline=False, directory=tmp_path)
    with pytest.raises(SpecError, match="already exists"):
        write_scaffold("acme-portal", is_offline=False, directory=tmp_path)


@pytest.mark.parametrize("name", ["Acme", "acme_portal", "a", "acme portal"])
def test_init_rejects_names_that_cannot_be_a_package(tmp_path, name):
    with pytest.raises(SpecError, match="Debian package name"):
        write_scaffold(name, is_offline=False, directory=tmp_path)


def test_init_rejects_a_bad_name_before_creating_anything(tmp_path):
    with pytest.raises(SpecError):
        write_scaffold("Acme", is_offline=False, directory=tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_scaffold_spec_is_plain_data():
    """`scaffold_spec` returns the dict itself.

    Tests and callers can inspect it without touching the filesystem.
    """
    assert scaffold_spec("demo", offline=True)["deployment"]["mode"] == "offline"
