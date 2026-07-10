from eaiv.targets.base import Target, TargetInfo
from eaiv.targets.jlink import JLinkTarget
from eaiv.targets.qemu import QEMUTarget
from eaiv.targets.serial import SerialTarget

_REGISTRY = {"qemu": QEMUTarget, "serial": SerialTarget, "jlink": JLinkTarget}


def build_target(spec: dict) -> Target:
    kind = spec.get("kind", "qemu")
    if kind not in _REGISTRY:
        raise ValueError(f"Unknown target kind: {kind!r} (expected one of {list(_REGISTRY)})")
    return _REGISTRY[kind](spec)


__all__ = ["Target", "TargetInfo", "build_target", "QEMUTarget", "SerialTarget", "JLinkTarget"]
