"""Ftrack session utilities for Maya.

This module contains ftrack API helpers for fetching component data.
Separated for easier removal/replacement in the future.
"""
from __future__ import annotations

import logging
from typing import Any

try:
    import ftrack_api
    FTRACK_API_AVAILABLE: bool = True
except Exception:
    ftrack_api = None  # type: ignore
    FTRACK_API_AVAILABLE = False

_log = logging.getLogger(__name__)

# Module-level session cache (reused across calls)
_session_cache: Any = None


def _get_ftrack_session() -> Any:
    """Get or create a cached ftrack session.

    Returns:
        ftrack_api.Session or None if not available.
    """
    global _session_cache

    if not FTRACK_API_AVAILABLE:
        _log.warning("ftrack_api not available")
        return None

    if _session_cache is not None:
        return _session_cache

    try:
        _session_cache = ftrack_api.Session()
        _log.info("Created new ftrack session for mroya.maya")
        return _session_cache
    except Exception as exc:
        _log.error("Failed to create ftrack session: %s", exc)
        return None


def get_component_path_by_id(component_id: str) -> str | None:
    """Fetch the filesystem path for a component by its ID.

    Args:
        component_id: The ftrack Component ID.

    Returns:
        The filesystem path string, or None if not found/error.
    """
    if not component_id:
        return None

    session = _get_ftrack_session()
    if not session:
        return None

    _SKIP_LOCATIONS = {"ftrack.server", "ftrack.unmanaged", "s3.studio.storage"}

    try:
        component = session.get("Component", component_id)
        if not component:
            _log.warning("Component not found: %s", component_id)
            return None

        for comp_location in component["component_locations"]:
            location = comp_location["location"]

            if location["name"] in _SKIP_LOCATIONS:
                continue

            availability = location.get_component_availability(component)
            if availability != 100:
                continue

            try:
                path = location.get_filesystem_path(component)
                if path:
                    _log.debug(
                        "Resolved path for component %s via location '%s': %s",
                        component_id,
                        location["name"],
                        path,
                    )
                    return str(path)
            except Exception:
                continue

        _log.warning("Could not resolve path for component %s in any location", component_id)
        return None

    except Exception as exc:
        _log.error("Error fetching component path for %s: %s", component_id, exc)
        return None


def get_versions_with_component(
    asset_id: str, component_name: str
) -> list[dict[str, Any]]:
    """Return all asset versions that contain a component with *component_name*.

    Results are sorted by version number descending (newest first).

    Each entry is a dict with keys:
        ``version``  – the int version number
        ``version_id`` – the AssetVersion id
        ``component_id`` – the matching Component id

    Returns an empty list on any error.
    """
    if not asset_id or not component_name:
        return []

    session = _get_ftrack_session()
    if not session:
        return []

    try:
        versions = session.query(
            'AssetVersion where asset_id is "{0}"'
            ' and components any (name is "{1}")'
            " order by version descending".format(asset_id, component_name)
        ).all()

        result: list[dict[str, Any]] = []
        for v in versions:
            comp_id = None
            for comp in v["components"]:
                if comp["name"] == component_name:
                    comp_id = comp["id"]
                    break
            result.append(
                {
                    "version": v["version"],
                    "version_id": v["id"],
                    "component_id": comp_id,
                }
            )
        return result
    except Exception as exc:
        _log.error(
            "Error fetching versions for asset %s / component '%s': %s",
            asset_id,
            component_name,
            exc,
        )
        return []
