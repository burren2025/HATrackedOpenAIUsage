"""Sensors for OpenAI Usage Monitor."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfInformation
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_API_KEY_ALIASES, CONF_ORG_NAME, CONF_PROJECT_ALIASES, DOMAIN
from .coordinator import OpenAIUsageCoordinator, UsageAggregate


@dataclass(frozen=True, kw_only=True)
class OpenAISensorDescription(SensorEntityDescription):
    """Sensor description with value extraction."""

    value_fn: Callable[[OpenAIUsageCoordinator], Any]
    attrs_fn: Callable[[OpenAIUsageCoordinator], dict[str, Any]] | None = None


TOTAL_DESCRIPTIONS: tuple[OpenAISensorDescription, ...] = (
    OpenAISensorDescription(
        key="cost_today",
        translation_key="cost_today",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        icon="mdi:cash",
        value_fn=lambda c: round(c.data.today.cost, 6),
        attrs_fn=lambda c: _aggregate_attrs(c.data.today),
    ),
    OpenAISensorDescription(
        key="cost_month_to_date",
        translation_key="cost_month_to_date",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        icon="mdi:cash-multiple",
        value_fn=lambda c: round(c.data.month.cost, 6),
        attrs_fn=lambda c: _aggregate_attrs(c.data.month),
    ),
    OpenAISensorDescription(
        key="requests_today",
        translation_key="requests_today",
        state_class=SensorStateClass.TOTAL,
        icon="mdi:counter",
        value_fn=lambda c: c.data.today.requests,
    ),
    OpenAISensorDescription(
        key="requests_month_to_date",
        translation_key="requests_month_to_date",
        state_class=SensorStateClass.TOTAL,
        icon="mdi:counter",
        value_fn=lambda c: c.data.month.requests,
    ),
    OpenAISensorDescription(
        key="input_tokens_today",
        translation_key="input_tokens_today",
        native_unit_of_measurement=UnitOfInformation.ITEMS,
        state_class=SensorStateClass.TOTAL,
        icon="mdi:text-box-arrow-right",
        value_fn=lambda c: c.data.today.input_tokens,
    ),
    OpenAISensorDescription(
        key="output_tokens_today",
        translation_key="output_tokens_today",
        native_unit_of_measurement=UnitOfInformation.ITEMS,
        state_class=SensorStateClass.TOTAL,
        icon="mdi:text-box-arrow-left",
        value_fn=lambda c: c.data.today.output_tokens,
    ),
    OpenAISensorDescription(
        key="total_tokens_today",
        translation_key="total_tokens_today",
        native_unit_of_measurement=UnitOfInformation.ITEMS,
        state_class=SensorStateClass.TOTAL,
        icon="mdi:text-box-multiple",
        value_fn=lambda c: c.data.today.total_tokens,
    ),
    OpenAISensorDescription(
        key="input_tokens_month_to_date",
        translation_key="input_tokens_month_to_date",
        native_unit_of_measurement=UnitOfInformation.ITEMS,
        state_class=SensorStateClass.TOTAL,
        icon="mdi:text-box-arrow-right",
        value_fn=lambda c: c.data.month.input_tokens,
    ),
    OpenAISensorDescription(
        key="output_tokens_month_to_date",
        translation_key="output_tokens_month_to_date",
        native_unit_of_measurement=UnitOfInformation.ITEMS,
        state_class=SensorStateClass.TOTAL,
        icon="mdi:text-box-arrow-left",
        value_fn=lambda c: c.data.month.output_tokens,
    ),
    OpenAISensorDescription(
        key="total_tokens_month_to_date",
        translation_key="total_tokens_month_to_date",
        native_unit_of_measurement=UnitOfInformation.ITEMS,
        state_class=SensorStateClass.TOTAL,
        icon="mdi:text-box-multiple",
        value_fn=lambda c: c.data.month.total_tokens,
    ),
    OpenAISensorDescription(
        key="estimated_credit_remaining",
        translation_key="estimated_credit_remaining",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:wallet",
        value_fn=lambda c: c.data.budget.get("estimated_remaining"),
        attrs_fn=lambda c: c.data.budget,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up sensors."""
    coordinator: OpenAIUsageCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[SensorEntity] = [
        OpenAITotalSensor(coordinator, entry, description)
        for description in TOTAL_DESCRIPTIONS
    ]
    known: set[tuple[str, str]] = set()

    def grouped_entities() -> list[OpenAIGroupedSensor]:
        new_entities: list[OpenAIGroupedSensor] = []
        groups = (
            ("api_key", coordinator.data.api_keys),
            ("project", coordinator.data.projects),
            ("model", coordinator.data.models),
        )
        for group_type, values in groups:
            for group_id in values:
                marker = (group_type, group_id)
                if marker in known:
                    continue
                known.add(marker)
                new_entities.append(OpenAIGroupedSensor(coordinator, entry, group_type, group_id))
        return new_entities

    entities.extend(grouped_entities())
    async_add_entities(entities)

    def add_new_grouped_entities() -> None:
        if new_entities := grouped_entities():
            async_add_entities(new_entities)

    entry.async_on_unload(coordinator.async_add_listener(add_new_grouped_entities))


class OpenAITotalSensor(CoordinatorEntity[OpenAIUsageCoordinator], SensorEntity):
    """A fixed organization-level sensor."""

    entity_description: OpenAISensorDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: OpenAIUsageCoordinator,
        entry: ConfigEntry,
        description: OpenAISensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = _device_info(entry)

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self.coordinator)

    @property
    def native_unit_of_measurement(self) -> str | None:
        if self.entity_description.device_class == SensorDeviceClass.MONETARY:
            return self.coordinator.data.month.currency
        return self.entity_description.native_unit_of_measurement

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs = {"last_updated": self.coordinator.data.last_updated}
        if self.entity_description.attrs_fn:
            attrs.update(self.entity_description.attrs_fn(self.coordinator))
        if self.coordinator.data.unavailable_categories:
            attrs["unavailable_categories"] = self.coordinator.data.unavailable_categories
        return attrs


class OpenAIGroupedSensor(CoordinatorEntity[OpenAIUsageCoordinator], SensorEntity):
    """Dynamic grouped sensor for API key, project, or model."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:cash-fast"
    _attr_state_class = SensorStateClass.TOTAL

    def __init__(
        self,
        coordinator: OpenAIUsageCoordinator,
        entry: ConfigEntry,
        group_type: str,
        group_id: str,
    ) -> None:
        super().__init__(coordinator)
        self.entry = entry
        self.group_type = group_type
        self.group_id = group_id
        self._attr_unique_id = f"{entry.entry_id}_{group_type}_{group_id}"
        self._attr_device_info = _device_info(entry)

    @property
    def translation_key(self) -> str:
        return f"{self.group_type}_usage"

    @property
    def translation_placeholders(self) -> dict[str, str]:
        return {"name": self._display_name}

    @property
    def native_value(self) -> float | None:
        aggregate = self._aggregate
        return round(aggregate.cost, 6) if aggregate else None

    @property
    def native_unit_of_measurement(self) -> str:
        return self.coordinator.data.month.currency

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        aggregate = self._aggregate
        if not aggregate:
            return {"id": self.group_id}
        attrs = _aggregate_attrs(aggregate)
        attrs["id"] = self.group_id
        attrs["friendly_alias"] = self._display_name
        return attrs

    @property
    def _aggregate(self) -> UsageAggregate | None:
        if self.group_type == "api_key":
            return self.coordinator.data.api_keys.get(self.group_id)
        if self.group_type == "project":
            return self.coordinator.data.projects.get(self.group_id)
        return self.coordinator.data.models.get(self.group_id)

    @property
    def _display_name(self) -> str:
        if self.group_type == "api_key":
            return _aliases(self.entry, CONF_API_KEY_ALIASES).get(self.group_id, self.group_id)
        if self.group_type == "project":
            return _aliases(self.entry, CONF_PROJECT_ALIASES).get(self.group_id, self.group_id)
        return self.group_id


def _aggregate_attrs(aggregate: UsageAggregate) -> dict[str, Any]:
    return {
        "cost": round(aggregate.cost, 6),
        "requests": aggregate.requests,
        "input_tokens": aggregate.input_tokens,
        "output_tokens": aggregate.output_tokens,
        "total_tokens": aggregate.total_tokens,
        "currency": aggregate.currency,
        "model_breakdown": aggregate.model_breakdown,
        "line_items": aggregate.line_items,
        "usage_categories": aggregate.categories,
        "last_updated": aggregate.last_updated,
    }


def _aliases(entry: ConfigEntry, key: str) -> dict[str, str]:
    try:
        parsed = json.loads(entry.options.get(key) or "{}")
    except json.JSONDecodeError:
        return {}
    return {str(k): str(v) for k, v in parsed.items()}


def _device_info(entry: ConfigEntry) -> dict[str, Any]:
    return {
        "identifiers": {(DOMAIN, entry.entry_id)},
        "name": entry.data.get(CONF_ORG_NAME, "OpenAI Usage"),
        "manufacturer": "OpenAI",
    }
