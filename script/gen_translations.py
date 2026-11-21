"""Generate translations/en.json from strings.json (resolves [%key:...%] refs).

Run: python script/gen_translations.py
"""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

ROOT = Path(__file__).resolve().parent.parent / "custom_components" / "kroger_restock"

COMMON = {
    "common::config_flow::title::oauth2_pick_implementation": "Pick authentication method",
    "common::config_flow::title::reauth": "Authentication expired for {name}",
    "common::config_flow::error::cannot_connect": "Failed to connect",
    "common::config_flow::abort::already_configured_account": "Account is already configured",
    "common::config_flow::abort::already_in_progress": "Configuration flow is already in progress",
    "common::config_flow::abort::oauth2_error": "Received invalid token data.",
    "common::config_flow::abort::oauth2_failed": "Error while obtaining access token.",
    "common::config_flow::abort::oauth2_timeout": "Timeout resolving OAuth token.",
    "common::config_flow::abort::oauth2_unauthorized": "OAuth authorization error while obtaining access token.",
    "common::config_flow::abort::oauth2_missing_configuration": "The component is not configured. Please follow the documentation.",
    "common::config_flow::abort::oauth2_missing_credentials": "The integration requires application credentials.",
    "common::config_flow::abort::oauth2_authorize_url_timeout": "Timeout generating authorize URL.",
    "common::config_flow::abort::oauth2_no_url_available": "No URL available. For information about this error, [check the help section]({docs_url})",
    "common::config_flow::abort::oauth2_user_rejected_authorize": "Account linking rejected: {error}",
    "common::config_flow::abort::reauth_successful": "Re-authentication was successful",
    "common::config_flow::create_entry::authenticated": "Successfully authenticated",
}


def main() -> None:
    """Write en.json."""
    strings = json.loads((ROOT / "strings.json").read_text())

    def lookup(key: str) -> str:
        if key in COMMON:
            return COMMON[key]
        parts = key.split("::")
        node: Any = strings
        for part in parts[2:]:
            node = node[part]
        return resolve(node)

    def resolve(value: Any) -> Any:
        if isinstance(value, dict):
            return {k: resolve(v) for k, v in value.items()}
        if isinstance(value, str):
            return re.sub(r"\[%key:([^%]+)%\]", lambda m: lookup(m.group(1)), value)
        return value

    out = ROOT / "translations" / "en.json"
    out.write_text(json.dumps(resolve(strings), indent=2, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
