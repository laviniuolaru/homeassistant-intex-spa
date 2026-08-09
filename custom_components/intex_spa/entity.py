"""Shared base for every Intex spa entity."""

from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_DEVICE_ID, DOMAIN
from .coordinator import IntexSpaCoordinator


class IntexSpaEntity(CoordinatorEntity[IntexSpaCoordinator]):
    """Ties an entity to one data point and to the spa's device entry."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: IntexSpaCoordinator, key: str) -> None:
        super().__init__(coordinator)
        device_id = coordinator.entry.data[CONF_DEVICE_ID]
        self._attr_unique_id = f"{device_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            name=coordinator.entry.title,
            manufacturer="Intex",
            model="PureSpa",
            model_id=coordinator.entry.data.get("product_id") or None,
        )

    def dp(self, dp_id: str) -> Any:
        """Current value of a data point, or None when the spa has not reported it."""
        return (self.coordinator.data or {}).get(dp_id)

    @property
    def available(self) -> bool:
        return super().available and bool(self.coordinator.data)
