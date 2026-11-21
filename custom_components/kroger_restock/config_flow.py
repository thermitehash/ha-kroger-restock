"""Config and options flows for Kroger Restock."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

from homeassistant.config_entries import (
    SOURCE_REAUTH,
    ConfigEntry,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_entry_oauth2_flow
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    ConfigEntrySelector,
    ConfigEntrySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
import voluptuous as vol

from .api import KrogerApiClient, KrogerError, Location
from .application_credentials import KrogerOAuth2Implementation
from .const import (
    CONF_DEBOUNCE_SECONDS,
    CONF_EXTRA_SENDER_DOMAINS,
    CONF_GIVE_UP_DAYS,
    CONF_IMAP_ENTRY,
    CONF_IPP_URL,
    CONF_LEAD_TIME_DAYS,
    CONF_LOCATION_ID,
    CONF_LOCATION_NAME,
    CONF_MODALITY,
    CONF_NOTIFY_ORDERS,
    CONF_NOTIFY_TARGETS,
    CONF_ORDER_DAYS,
    CONF_PAPER_WIDTH,
    CONF_READD_SHORTED,
    CONF_RECEIPT_HOST,
    CONF_RECEIPT_PORT,
    CONF_SAVE_PDF,
    CONF_STOCK_CHECK_HOURS,
    CONF_ZIP_CODE,
    DEFAULT_DEBOUNCE_SECONDS,
    DEFAULT_GIVE_UP_DAYS,
    DEFAULT_LEAD_TIME_DAYS,
    DEFAULT_MODALITY,
    DEFAULT_NOTIFY_ORDERS,
    DEFAULT_PAPER_WIDTH,
    DEFAULT_READD_SHORTED,
    DEFAULT_RECEIPT_PORT,
    DEFAULT_SAVE_PDF,
    DEFAULT_STOCK_CHECK_HOURS,
    DOMAIN,
    MODALITIES,
    PAPER_WIDTHS,
    WEEKDAYS,
)

_LOGGER = logging.getLogger(__name__)

ZIP_SCHEMA = vol.Schema({vol.Required(CONF_ZIP_CODE): TextSelector()})

MODALITY_SELECTOR = SelectSelector(
    SelectSelectorConfig(
        options=list(MODALITIES),
        translation_key=CONF_MODALITY,
        mode=SelectSelectorMode.LIST,
    )
)


def _valid_zip(value: str) -> str | None:
    digits = value.strip()[:5]
    return digits if len(digits) == 5 and digits.isdigit() else None


def _location_selector(locations: list[Location]) -> SelectSelector:
    return SelectSelector(
        SelectSelectorConfig(
            options=[
                SelectOptionDict(value=loc.location_id, label=loc.label)
                for loc in locations
            ],
            mode=SelectSelectorMode.LIST,
        )
    )


async def _async_find_locations(
    api: KrogerApiClient, zip_code: str
) -> tuple[list[Location], str | None]:
    """Return (locations, error_key)."""
    try:
        locations = await api.async_get_locations(zip_code)
    except KrogerError:
        _LOGGER.exception("Store lookup failed")
        return [], "cannot_connect"
    if not locations:
        return [], "no_stores"
    return locations, None


class KrogerRestockFlowHandler(
    config_entry_oauth2_flow.AbstractOAuth2FlowHandler, domain=DOMAIN
):
    """Handle the Kroger sign-in, store and modality steps."""

    DOMAIN = DOMAIN
    VERSION = 1
    MINOR_VERSION = 1

    def __init__(self) -> None:
        """Initialize."""
        super().__init__()
        self._oauth_data: dict[str, Any] = {}
        self._locations: dict[str, Location] = {}
        self._location: Location | None = None
        self._api: KrogerApiClient | None = None

    @property
    def logger(self) -> logging.Logger:
        """Return logger."""
        return _LOGGER

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow."""
        return KrogerRestockOptionsFlow()

    def _make_api(self, token: Mapping[str, Any]) -> KrogerApiClient:
        access_token = str(token["access_token"])

        async def user_token() -> str:
            return access_token

        impl = self.flow_impl
        app_token = (
            impl.async_get_app_token
            if isinstance(impl, KrogerOAuth2Implementation)
            else None
        )
        return KrogerApiClient(
            async_get_clientsession(self.hass), user_token, app_token
        )

    async def async_oauth_create_entry(self, data: dict[str, Any]) -> ConfigFlowResult:
        """Finish sign-in: identify the account, then pick a store."""
        api = self._make_api(data["token"])
        try:
            profile_id = await api.async_get_profile_id()
        except KrogerError:
            _LOGGER.exception("Could not read Kroger profile")
            return self.async_abort(reason="cannot_connect")

        await self.async_set_unique_id(profile_id)
        if self.source == SOURCE_REAUTH:
            self._abort_if_unique_id_mismatch(reason="wrong_account")
            return self.async_update_reload_and_abort(
                self._get_reauth_entry(), data_updates=data
            )
        self._abort_if_unique_id_configured()
        self._oauth_data = data
        self._api = api
        return await self.async_step_store()

    async def async_step_store(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for a ZIP code to find nearby stores."""
        errors: dict[str, str] = {}
        if user_input is not None:
            if (zip_code := _valid_zip(user_input[CONF_ZIP_CODE])) is None:
                errors[CONF_ZIP_CODE] = "invalid_zip"
            else:
                assert self._api is not None
                locations, error = await _async_find_locations(self._api, zip_code)
                if error:
                    errors["base"] = error
                else:
                    self._locations = {loc.location_id: loc for loc in locations}
                    return await self.async_step_pick_store()
        return self.async_show_form(
            step_id="store", data_schema=ZIP_SCHEMA, errors=errors
        )

    async def async_step_pick_store(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick one store from the results."""
        if user_input is not None:
            self._location = self._locations[user_input[CONF_LOCATION_ID]]
            return await self.async_step_modality()
        return self.async_show_form(
            step_id="pick_store",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_LOCATION_ID): _location_selector(
                        list(self._locations.values())
                    )
                }
            ),
        )

    async def async_step_modality(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose pickup or delivery."""
        if user_input is not None:
            assert self._location is not None
            return self.async_create_entry(
                title=self._location.name,
                data={
                    **self._oauth_data,
                    CONF_LOCATION_ID: self._location.location_id,
                    CONF_LOCATION_NAME: self._location.label,
                    CONF_MODALITY: user_input[CONF_MODALITY],
                },
            )
        return self.async_show_form(
            step_id="modality",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_MODALITY, default=DEFAULT_MODALITY
                    ): MODALITY_SELECTOR
                }
            ),
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Start re-auth when the refresh token stops working."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm re-auth."""
        if user_input is None:
            return self.async_show_form(step_id="reauth_confirm")
        return await self.async_step_user()


def _notify_options(hass: HomeAssistant) -> list[str]:
    services = hass.services.async_services_for_domain("notify")
    return sorted(
        f"notify.{name}" for name in services if name.startswith("mobile_app_")
    )


class KrogerRestockOptionsFlow(OptionsFlow):
    """Change the store, modality and behaviour settings."""

    def __init__(self) -> None:
        """Initialize."""
        self._locations: dict[str, Location] = {}

    def _get(self, key: str, default: Any) -> Any:
        if key in self.config_entry.options:
            return self.config_entry.options[key]
        return self.config_entry.data.get(key, default)

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose what to change."""
        return self.async_show_menu(
            step_id="init", menu_options=["settings", "store", "printing", "orders"]
        )

    async def async_step_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """General settings."""
        if user_input is not None:
            return self.async_create_entry(
                data={**self.config_entry.options, **user_input}
            )
        notify_choices = sorted(
            set(_notify_options(self.hass)) | set(self._get(CONF_NOTIFY_TARGETS, []))
        )
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_MODALITY, default=self._get(CONF_MODALITY, DEFAULT_MODALITY)
                ): MODALITY_SELECTOR,
                vol.Required(
                    CONF_ORDER_DAYS, default=self._get(CONF_ORDER_DAYS, [])
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=list(WEEKDAYS),
                        multiple=True,
                        translation_key=CONF_ORDER_DAYS,
                        mode=SelectSelectorMode.LIST,
                    )
                ),
                vol.Required(
                    CONF_LEAD_TIME_DAYS,
                    default=self._get(CONF_LEAD_TIME_DAYS, DEFAULT_LEAD_TIME_DAYS),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=0, max=6, step=1, mode=NumberSelectorMode.BOX
                    )
                ),
                vol.Required(
                    CONF_STOCK_CHECK_HOURS,
                    default=self._get(
                        CONF_STOCK_CHECK_HOURS, DEFAULT_STOCK_CHECK_HOURS
                    ),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=1,
                        max=48,
                        step=0.5,
                        unit_of_measurement="h",
                        mode=NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(
                    CONF_GIVE_UP_DAYS,
                    default=self._get(CONF_GIVE_UP_DAYS, DEFAULT_GIVE_UP_DAYS),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=1,
                        max=365,
                        step=1,
                        unit_of_measurement="d",
                        mode=NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(
                    CONF_DEBOUNCE_SECONDS,
                    default=self._get(CONF_DEBOUNCE_SECONDS, DEFAULT_DEBOUNCE_SECONDS),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=0,
                        max=30,
                        step=0.5,
                        unit_of_measurement="s",
                        mode=NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(
                    CONF_NOTIFY_TARGETS, default=self._get(CONF_NOTIFY_TARGETS, [])
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=notify_choices,
                        multiple=True,
                        custom_value=True,
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                ),
            }
        )
        return self.async_show_form(step_id="settings", data_schema=schema)

    async def async_step_store(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Find a different store by ZIP code."""
        errors: dict[str, str] = {}
        if user_input is not None:
            if (zip_code := _valid_zip(user_input[CONF_ZIP_CODE])) is None:
                errors[CONF_ZIP_CODE] = "invalid_zip"
            else:
                api = self.config_entry.runtime_data.api
                locations, error = await _async_find_locations(api, zip_code)
                if error:
                    errors["base"] = error
                else:
                    self._locations = {loc.location_id: loc for loc in locations}
                    return await self.async_step_pick_store()
        return self.async_show_form(
            step_id="store", data_schema=ZIP_SCHEMA, errors=errors
        )

    async def async_step_pick_store(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick one store from the results."""
        if user_input is not None:
            location = self._locations[user_input[CONF_LOCATION_ID]]
            return self.async_create_entry(
                data={
                    **self.config_entry.options,
                    CONF_LOCATION_ID: location.location_id,
                    CONF_LOCATION_NAME: location.label,
                }
            )
        return self.async_show_form(
            step_id="pick_store",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_LOCATION_ID): _location_selector(
                        list(self._locations.values())
                    )
                }
            ),
        )

    async def async_step_printing(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Receipt and PDF printer settings."""
        errors: dict[str, str] = {}
        if user_input is not None:
            url = (user_input.get(CONF_IPP_URL) or "").strip()
            if url and not url.lower().startswith(
                ("ipp://", "ipps://", "http://", "https://")
            ):
                errors[CONF_IPP_URL] = "invalid_ipp_url"
            else:
                data = {**self.config_entry.options, **user_input}
                data[CONF_RECEIPT_HOST] = (
                    user_input.get(CONF_RECEIPT_HOST) or ""
                ).strip()
                data[CONF_IPP_URL] = url
                data[CONF_RECEIPT_PORT] = int(user_input[CONF_RECEIPT_PORT])
                return self.async_create_entry(data=data)
        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_RECEIPT_HOST,
                    description={"suggested_value": self._get(CONF_RECEIPT_HOST, "")},
                ): TextSelector(),
                vol.Required(
                    CONF_RECEIPT_PORT,
                    default=self._get(CONF_RECEIPT_PORT, DEFAULT_RECEIPT_PORT),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=1, max=65535, step=1, mode=NumberSelectorMode.BOX
                    )
                ),
                vol.Required(
                    CONF_PAPER_WIDTH,
                    default=self._get(CONF_PAPER_WIDTH, DEFAULT_PAPER_WIDTH),
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=list(PAPER_WIDTHS),
                        translation_key=CONF_PAPER_WIDTH,
                        mode=SelectSelectorMode.LIST,
                    )
                ),
                vol.Optional(
                    CONF_IPP_URL,
                    description={"suggested_value": self._get(CONF_IPP_URL, "")},
                ): TextSelector(TextSelectorConfig(type=TextSelectorType.URL)),
                vol.Required(
                    CONF_SAVE_PDF, default=self._get(CONF_SAVE_PDF, DEFAULT_SAVE_PDF)
                ): BooleanSelector(),
            }
        )
        return self.async_show_form(
            step_id="printing", data_schema=schema, errors=errors
        )

    async def async_step_orders(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Order tracking from Kroger's emails via the IMAP integration."""
        if user_input is not None:
            data = {**self.config_entry.options, **user_input}
            data[CONF_IMAP_ENTRY] = user_input.get(CONF_IMAP_ENTRY) or ""
            data[CONF_EXTRA_SENDER_DOMAINS] = (
                user_input.get(CONF_EXTRA_SENDER_DOMAINS) or ""
            ).strip()
            return self.async_create_entry(data=data)
        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_IMAP_ENTRY,
                    description={"suggested_value": self._get(CONF_IMAP_ENTRY, None)},
                ): ConfigEntrySelector(ConfigEntrySelectorConfig(integration="imap")),
                vol.Required(
                    CONF_NOTIFY_ORDERS,
                    default=self._get(CONF_NOTIFY_ORDERS, DEFAULT_NOTIFY_ORDERS),
                ): BooleanSelector(),
                vol.Required(
                    CONF_READD_SHORTED,
                    default=self._get(CONF_READD_SHORTED, DEFAULT_READD_SHORTED),
                ): BooleanSelector(),
                vol.Optional(
                    CONF_EXTRA_SENDER_DOMAINS,
                    description={
                        "suggested_value": self._get(CONF_EXTRA_SENDER_DOMAINS, "")
                    },
                ): TextSelector(),
            }
        )
        return self.async_show_form(step_id="orders", data_schema=schema)
