"""Discover camera-related entities for selected devices."""

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er


def discover_camera_entities(
    hass: HomeAssistant,
    device_id: str,
) -> dict[str, str | None]:
    """Find motion sensor, snapshot button, and camera for a device."""

    registry = er.async_get(hass)
    entries = er.async_entries_for_device(registry, device_id)

    result = {
        "motion": None,
        "snapshot_button": None,
        "camera": None,
    }

    for entry in entries:
        if entry.disabled_by is not None:
            continue
        entity_id = entry.entity_id
        name = (
            f"{entry.original_name or ''} "
            f"{entry.unique_id or ''}"
        ).lower()

        if entry.domain == "binary_sensor":
            if "motion" in name:
                result["motion"] = entity_id

        elif entry.domain == "button":
            if "snapshot" in name:
                result["snapshot_button"] = entity_id

        elif entry.domain == "camera":
            if "snapshot" in name:
                result["camera"] = entity_id

    return result