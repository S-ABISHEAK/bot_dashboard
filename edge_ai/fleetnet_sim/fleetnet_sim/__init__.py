"""FleetNet multi-robot simulation & telemetry layer.

Drives the real algorithms in ``Fleet_SIH/core`` (never reimplemented)
over layouts produced by ``warehouse_layout``'s ``fleetnet_layout``
package, and persists complete telemetry for later ML dataset
construction. See the repo's README for architecture and usage.
"""
from fleetnet_sim import _paths  # noqa: F401  (side effect: sys.path bootstrap for `core`)

SCHEMA_VERSION = "1.0"
SIM_VERSION = "0.1.0"

__all__ = ["SCHEMA_VERSION", "SIM_VERSION"]
