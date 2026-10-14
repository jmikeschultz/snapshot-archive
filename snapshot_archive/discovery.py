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


def discover_stream_source(hass: HomeAssistant, device_id: str) -> str | None:
    """Read Ring-MQTT's live RTSP source from this device's enabled Info sensor.

    Resolve on each capture because MQTT state may arrive after entry setup.
    Credentials stay in memory and must never appear in logs or API results.
    """
    from urllib.parse import urlsplit

    registry = er.async_get(hass)
    for entry in er.async_entries_for_device(registry, device_id):
        if entry.disabled_by is not None or entry.domain != "sensor":
            continue
        state = hass.states.get(entry.entity_id)
        source = state.attributes.get("stream_Source") if state else None
        if not isinstance(source, str):
            continue
        try:
            parsed = urlsplit(source)
            if (
                parsed.scheme == "rtsp"
                and parsed.hostname
                and parsed.path.endswith("_live")
                and not parsed.query
                and not parsed.fragment
                and not any(character.isspace() for character in source)
            ):
                return source
        except ValueError:
            continue
    return None
