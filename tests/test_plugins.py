"""Tests for the plugin registry and target construction path."""

from __future__ import annotations

import pytest

from eaiv.plugins import PluginMetadata, PluginRegistry, get_registry
from eaiv.targets import QEMUTarget, build_target


def test_registry_register_and_create():
    reg = PluginRegistry()
    meta = PluginMetadata(name="fake", version="1.0", description="", plugin_type="target")
    reg.register(meta, lambda cfg: {"built_from": cfg})

    assert reg.get("target", "fake") is meta
    assert reg.create("target", "fake", {"x": 1}) == {"built_from": {"x": 1}}


def test_registry_duplicate_registration_rejected():
    reg = PluginRegistry()
    meta = PluginMetadata(name="dup", version="1.0", description="", plugin_type="sensor")
    reg.register(meta, dict)
    with pytest.raises(ValueError, match="already registered"):
        reg.register(meta, dict)


def test_registry_instances_are_isolated():
    a, b = PluginRegistry(), PluginRegistry()
    a.register(
        PluginMetadata(name="only-a", version="1.0", description="", plugin_type="target"), dict
    )
    assert b.get("target", "only-a") is None


def test_builtin_targets_registered_in_default_registry():
    names = {m.name for m in get_registry().list_plugins("target")}
    assert {"qemu", "serial", "jlink"} <= names


def test_build_target_goes_through_registry():
    target = build_target({"kind": "qemu", "qemu": {"machine": "mps2-an385"}})
    assert isinstance(target, QEMUTarget)
    target.close()


def test_build_target_unknown_kind_lists_alternatives():
    with pytest.raises(ValueError, match="qemu"):
        build_target({"kind": "no-such-board"})
