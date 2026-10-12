
"""Configuration flow for Snapshot Archive."""

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.helpers import selector

from .const import CONF_DEVICES, DOMAIN
from .retention import (
    DEFAULT_RETENTION_DAYS,
    DEFAULT_MAX_SIZE_GB,
)

CONF_RETENTION_DAYS = "retention_days"
CONF_MAX_SIZE_GB = "max_size_gb"


def settings_schema(
    devices=None,
    retention_days=DEFAULT_RETENTION_DAYS,
    max_size_gb=DEFAULT_MAX_SIZE_GB,
):
    """Build the configuration form."""

    return vol.Schema(
        {
            vol.Required(
                CONF_DEVICES,
                default=devices or [],
            ): selector.DeviceSelector(
                selector.DeviceSelectorConfig(multiple=True)
            ),
            vol.Required(
                CONF_RETENTION_DAYS,
                default=retention_days,
            ): vol.All(
                vol.Coerce(int),
                vol.Range(min=1, max=3650),
            ),
            vol.Required(
                CONF_MAX_SIZE_GB,
                default=max_size_gb,
            ): vol.All(
                vol.Coerce(int),
                vol.Range(min=1, max=1000),
            ),
        }
    )


class SnapshotArchiveConfigFlow(
    config_entries.ConfigFlow, domain=DOMAIN
):
    """Configure Snapshot Archive."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Initial configuration."""

        if user_input is not None:
            await self.async_set_unique_id(DOMAIN)
            self._abort_if_unique_id_configured()

            return self.async_create_entry(
                title="Snapshot Archive",
                data=user_input,
            )

        return self.async_show_form(
            step_id="user",
            data_schema=settings_schema(),
        )

    @staticmethod
    def async_get_options_flow(config_entry):
        """Provide options editor."""
        return SnapshotArchiveOptionsFlow()


class SnapshotArchiveOptionsFlow(config_entries.OptionsFlow):
    """Edit camera selection and retention."""

    async def async_step_init(self, user_input=None):
        """Configure integration options."""

        if user_input is not None:
            return self.async_create_entry(
                title="",
                data=user_input,
            )

        devices = self.config_entry.options.get(
            CONF_DEVICES,
            self.config_entry.data.get(CONF_DEVICES, []),
        )

        retention_days = self.config_entry.options.get(
            CONF_RETENTION_DAYS,
            self.config_entry.data.get(
                CONF_RETENTION_DAYS,
                DEFAULT_RETENTION_DAYS,
            ),
        )

        max_size_gb = self.config_entry.options.get(
            CONF_MAX_SIZE_GB,
            self.config_entry.data.get(
                CONF_MAX_SIZE_GB,
                DEFAULT_MAX_SIZE_GB,
            ),
        )

        return self.async_show_form(
            step_id="init",
            data_schema=settings_schema(
                devices,
                retention_days,
                max_size_gb,
            ),
        )
