"""FleetNet procedural warehouse layout generator.

This package generates validated, reproducible 2D warehouse environments
(geometry + navigation graph + derived metrics) as the environment
foundation for the later FleetNet robot simulation. It does not implement
any robot algorithm (CBBA/Karma, D* Lite, MDPiBT, NH-ORCA, Zenoh) — see
the ``fleetnet_layout.serialization`` output contract for the boundary.
"""

SCHEMA_VERSION = "1.0"
GENERATOR_VERSION = "0.1.0"

__all__ = ["SCHEMA_VERSION", "GENERATOR_VERSION"]
