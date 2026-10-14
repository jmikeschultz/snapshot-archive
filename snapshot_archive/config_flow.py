"""Configuration and options for snapshot and optional video capture."""

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.helpers import selector

from .const import (
    CONF_CLIP_SECONDS,
    CONF_DEVICES,
    CONF_MIN_FREE_GB,
    CONF_VIDEO_DEVICES,
    CONF_VIDEO_MAX_SIZE_GB,
    CONF_VIDEO_RETENTION_DAYS,
    DEFAULT_CLIP_SECONDS,
    DEFAULT_MIN_FREE_GB,
    DEFAULT_VIDEO_MAX_SIZE_GB,
    DEFAULT_VIDEO_RETENTION_DAYS,
    DOMAIN,
)
from .retention import DEFAULT_MAX_SIZE_GB, DEFAULT_RETENTION_DAYS

CONF_RETENTION_DAYS = "retention_days"
CONF_MAX_SIZE_GB = "max_size_gb"
DEFAULTS = {
    CONF_DEVICES: [],
    CONF_RETENTION_DAYS: DEFAULT_RETENTION_DAYS,
    CONF_MAX_SIZE_GB: DEFAULT_MAX_SIZE_GB,
    CONF_VIDEO_DEVICES: [],
    CONF_CLIP_SECONDS: DEFAULT_CLIP_SECONDS,
    CONF_VIDEO_RETENTION_DAYS: DEFAULT_VIDEO_RETENTION_DAYS,
    CONF_VIDEO_MAX_SIZE_GB: DEFAULT_VIDEO_MAX_SIZE_GB,
    CONF_MIN_FREE_GB: DEFAULT_MIN_FREE_GB,
}
RANGES = {
    CONF_RETENTION_DAYS: (1, 3650),
    CONF_MAX_SIZE_GB: (1, 1000),
    CONF_CLIP_SECONDS: (5, 60),
    CONF_VIDEO_RETENTION_DAYS: (1, 365),
    CONF_VIDEO_MAX_SIZE_GB: (1, 1000),
    CONF_MIN_FREE_GB: (1, 1000),
}


def settings_schema(settings=None):
    """Build one schema for initial setup, errors, and options editing."""
    values = {**DEFAULTS, **(settings or {})}
    schema = {}
    for key in DEFAULTS:
        marker = vol.Optional if key == CONF_VIDEO_DEVICES else vol.Required
        field = marker(key, default=values[key])
        if key in (CONF_DEVICES, CONF_VIDEO_DEVICES):
            schema[field] = selector.DeviceSelector(
                selector.DeviceSelectorConfig(multiple=True)
            )
        else:
            minimum, maximum = RANGES[key]
            schema[field] = vol.All(vol.Coerce(int), vol.Range(min=minimum, max=maximum))
    return vol.Schema(schema)


def selection_errors(settings):
    """Never enable video on a device outside the monitored selection."""
    if not set(settings.get(CONF_VIDEO_DEVICES, [])).issubset(settings[CONF_DEVICES]):
        return {"base": "video_not_selected"}
    return {}


class SnapshotArchiveConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Configure Snapshot Archive."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = selection_errors(user_input) if user_input is not None else {}
        if user_input is not None and not errors:
            await self.async_set_unique_id(DOMAIN)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(title="Snapshot Archive", data=user_input)
        return self.async_show_form(
            step_id="user", data_schema=settings_schema(user_input), errors=errors
        )

    @staticmethod
    def async_get_options_flow(config_entry):
        return SnapshotArchiveOptionsFlow()


class SnapshotArchiveOptionsFlow(config_entries.OptionsFlow):
    """Edit monitored devices, video selection, and separate retention budgets."""

    async def async_step_init(self, user_input=None):
        errors = selection_errors(user_input) if user_input is not None else {}
        if user_input is not None and not errors:
            return self.async_create_entry(title="", data=user_input)
        settings = {**self.config_entry.data, **self.config_entry.options}
        if user_input is not None:
            settings.update(user_input)
        return self.async_show_form(
            step_id="init", data_schema=settings_schema(settings), errors=errors
        )
