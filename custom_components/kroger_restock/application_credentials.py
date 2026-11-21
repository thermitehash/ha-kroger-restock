"""Application credentials platform for Kroger Restock.

Kroger's token endpoint expects the client ID and secret in an HTTP Basic
``Authorization`` header rather than in the form body, so we override the
token request of HA's stock implementation.
"""

from __future__ import annotations

import base64
import logging
import time
from typing import Any, cast

from aiohttp import ClientError
from homeassistant.components.application_credentials import (
    AuthImplementation,
    AuthorizationServer,
    ClientCredential,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_entry_oauth2_flow
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import OAUTH2_AUTHORIZE, OAUTH2_SCOPES, OAUTH2_TOKEN, SCOPE_PRODUCT

_LOGGER = logging.getLogger(__name__)

# Refresh client-credentials tokens this long before they expire.
_APP_TOKEN_MARGIN = 60


class KrogerOAuth2Implementation(AuthImplementation):
    """Kroger OAuth2 implementation using HTTP Basic client auth."""

    _app_token: str | None = None
    _app_token_expires_at: float = 0.0

    @property
    def extra_authorize_data(self) -> dict[str, Any]:
        """Request the scopes we need."""
        return {"scope": " ".join(OAUTH2_SCOPES)}

    def _basic_credentials(self) -> str:
        raw = f"{self.client_id}:{self.client_secret}".encode()
        return base64.b64encode(raw).decode("ascii")

    async def _post_token(self, data: dict[str, Any]) -> dict[str, Any]:
        session = async_get_clientsession(self.hass)
        try:
            resp = await session.post(
                self.token_url,
                data=data,
                headers={
                    "Accept": "application/json",
                    "Authorization": f"Basic {self._basic_credentials()}",
                },
            )
            if resp.status >= 400:
                _LOGGER.debug(
                    "Kroger token request failed (%s): %s",
                    resp.status,
                    (await resp.text())[:200],
                )
            resp.raise_for_status()
            return cast(dict[str, Any], await resp.json())
        except ClientError as err:
            # Reuse HA's mapping so 4xx triggers re-auth and 5xx/429 retry.
            config_entry_oauth2_flow._raise_mapped_token_error(err, self.service_domain)

    async def _token_request(self, data: dict) -> dict:
        """Make a token request with Basic auth."""
        return await self._post_token(data)

    async def async_get_app_token(self) -> str:
        """Return a client-credentials token for catalog calls.

        Only used if Kroger refuses the user token for product calls.
        """
        if (
            self._app_token is not None
            and self._app_token_expires_at > time.time() + _APP_TOKEN_MARGIN
        ):
            return self._app_token
        token = await self._post_token(
            {"grant_type": "client_credentials", "scope": SCOPE_PRODUCT}
        )
        self._app_token = str(token["access_token"])
        self._app_token_expires_at = time.time() + float(token.get("expires_in", 1800))
        return self._app_token


async def async_get_authorization_server(hass: HomeAssistant) -> AuthorizationServer:
    """Return the Kroger authorization server."""
    return AuthorizationServer(authorize_url=OAUTH2_AUTHORIZE, token_url=OAUTH2_TOKEN)


async def async_get_auth_implementation(
    hass: HomeAssistant, auth_domain: str, credential: ClientCredential
) -> config_entry_oauth2_flow.AbstractOAuth2Implementation:
    """Return the Kroger auth implementation."""
    return KrogerOAuth2Implementation(
        hass,
        auth_domain,
        credential,
        AuthorizationServer(authorize_url=OAUTH2_AUTHORIZE, token_url=OAUTH2_TOKEN),
    )


async def async_get_description_placeholders(hass: HomeAssistant) -> dict[str, str]:
    """Return placeholders for the credentials dialog."""
    return {
        "developer_url": "https://developer.kroger.com/",
        "redirect_uri": "https://my.home-assistant.io/redirect/oauth",
    }
