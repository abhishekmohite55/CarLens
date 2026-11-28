"""VIN providers: each module has decode(vin, settings) -> raw answer and record(raw) -> the part the field map reads.
Nothing else. A failure to get an answer raises ProviderDown."""
from __future__ import annotations

from types import ModuleType


class ProviderDown(Exception):
    """No usable answer: timeout, network error, 5xx, an answer that is not the expected JSON."""


def provider_module(name: str) -> ModuleType:
    from . import mcpvin, vpic  # one import per provider
    modules = {"vpic": vpic, "mcpvin": mcpvin}
    if name not in modules:
        raise ValueError(f"unknown VIN provider {name!r}")
    return modules[name]


KNOWN = ("vpic",)  # providers that decode a VIN (vin.provider)
DETAILS = ("mcpvin",)  # providers of vehicle details (vin.details_provider, stage U4)
