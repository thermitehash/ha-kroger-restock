"""Validate the blueprint and example automations with HA's own schemas."""

from __future__ import annotations

from pathlib import Path

from homeassistant.components.automation.config import async_validate_config_item
from homeassistant.components.blueprint import models
from homeassistant.components.blueprint.schemas import BLUEPRINT_SCHEMA
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from homeassistant.util.yaml import load_yaml_dict
import pytest

ROOT = Path(__file__).parent.parent
BLUEPRINT = ROOT / "blueprints/automation/kroger_restock/arrive_at_store.yaml"
EXAMPLES = [
    *sorted((ROOT / "examples").glob("*.yaml")),
    ROOT / "esphome" / "ha_feedback_automation.yaml",
]


def test_blueprint_schema() -> None:
    data = load_yaml_dict(str(BLUEPRINT))
    blueprint = models.Blueprint(
        data, expected_domain="automation", schema=BLUEPRINT_SCHEMA
    )
    assert blueprint.metadata["source_url"].endswith("arrive_at_store.yaml")
    assert set(blueprint.inputs) == {
        "person",
        "store_zone",
        "notify_device",
        "grocery_list",
        "in_cart_sensor",
        "waiting_sensor",
        "needs_review_sensor",
        "skip_when_empty",
    }


async def test_blueprint_instance_validates(hass: HomeAssistant) -> None:
    assert await async_setup_component(hass, "automation", {})
    data = load_yaml_dict(str(BLUEPRINT))
    blueprint = models.Blueprint(
        data, expected_domain="automation", schema=BLUEPRINT_SCHEMA
    )
    inputs = models.BlueprintInputs(
        blueprint,
        {
            "use_blueprint": {
                "path": "kroger_restock/arrive_at_store.yaml",
                "input": {
                    "person": "person.alex",
                    "store_zone": "zone.kroger",
                    "notify_device": "abc123",
                    "grocery_list": "todo.kroger_downtown",
                    "in_cart_sensor": "sensor.kroger_downtown_in_cart",
                    "waiting_sensor": "sensor.kroger_downtown_waiting_on_stock",
                    "needs_review_sensor": "sensor.kroger_downtown_needs_review",
                },
            }
        },
    )
    inputs.validate()
    config = inputs.async_substitute()
    assert config["triggers"][0]["entity_id"] == "person.alex"
    assert config["variables"]["skip_when_empty"] is True


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.name)
async def test_examples_validate(hass: HomeAssistant, path: Path) -> None:
    assert await async_setup_component(hass, "automation", {})
    config = load_yaml_dict(str(path))
    validated = await async_validate_config_item(hass, path.stem, config)
    assert validated is not None
    assert validated.validation_status.value == "ok", validated.validation_error
