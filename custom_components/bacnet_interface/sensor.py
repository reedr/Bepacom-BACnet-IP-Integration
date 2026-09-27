from collections.abc import Callable
from dataclasses import dataclass
from math import log10
from typing import Any

from homeassistant.components.sensor import (SensorDeviceClass, SensorEntity,
                                             SensorEntityDescription,
                                             SensorStateClass)
from homeassistant.components.sensor.const import DEVICE_CLASS_UNITS
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (CONF_ENABLED, CONF_NAME, UnitOfEnergy,
                                 UnitOfVolume)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util.dt import utcnow

from .const import STATETEXT_OFFSET  # JCO
from .const import DOMAIN, LOGGER
from .coordinator import EcoPanelDataUpdateCoordinator, EcoPanelDeviceInfoCoordinator
from .helper import (bacnet_to_device_class, bacnet_to_ha_units,
                     decimal_places_needed)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up EcoPanel sensor based on a config entry."""
    coordinator: EcoPanelDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    entity_list: list = []

    info_coordinator = EcoPanelDeviceInfoCoordinator(hass, coordinator.interface)
    await info_coordinator.async_refresh()

    # Collect from all devices the objects that can become a sensor
    for deviceid in coordinator.data.devices:
        if not coordinator.data.devices[deviceid].objects:
            LOGGER.warning(f"No objects in {deviceid}!")
            continue

        entity_list.append(
            DeviceIdEntity(
                coordinator=coordinator,
                info_coordinator=info_coordinator,
                deviceid=deviceid,
            )
        )
        entity_list.extend(
            entity_class(
                coordinator=info_coordinator,
                data_coordinator=coordinator,
                deviceid=deviceid,
            )
            for entity_class in (
                IpAddressEntity,
                SystemStatusEntity,
                DatabaseRevisionEntity,
                CovSubscriptionsEntity,
            )
        )

        for objectid in coordinator.data.devices[deviceid].objects:
            if (
                not coordinator.data.devices[deviceid]
                .objects[objectid]
                .objectIdentifier
            ):
                LOGGER.warning(f"No object identifier for {objectid} in {deviceid}!")
                continue

            if (
                coordinator.data.devices[deviceid].objects[objectid].objectIdentifier[0]
                == "analogInput"
            ):
                entity_list.append(
                    AnalogInputEntity(
                        coordinator=coordinator, deviceid=deviceid, objectid=objectid
                    )
                )
            # elif coordinator.data.devices[deviceid].objects[objectid].objectType == 'accumulator':
            #    entity_list.append(AnalogInputEntity(coordinator=coordinator, deviceid=deviceid, objectid=objectid))
            # elif coordinator.data.devices[deviceid].objects[objectid].objectType == 'averaging':
            #    entity_list.append(AveragingEntity(coordinator=coordinator, deviceid=deviceid, objectid=objectid))
            elif (
                coordinator.data.devices[deviceid].objects[objectid].objectIdentifier[0]
                == "multiStateInput"
            ):
                entity_list.append(
                    MultiStateInputEntity(
                        coordinator=coordinator, deviceid=deviceid, objectid=objectid
                    )
                )

    async_add_entities(entity_list)


class AnalogInputEntity(CoordinatorEntity[EcoPanelDataUpdateCoordinator], SensorEntity):
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: EcoPanelDataUpdateCoordinator,
        deviceid: str,
        objectid: str,
    ):
        """Initialize a BACnet AnalogInput object as entity."""
        super().__init__(coordinator=coordinator)
        self.deviceid = deviceid
        self.objectid = objectid

    @property
    def unique_id(self) -> str:
        return f"{self.deviceid}_{self.objectid}"

    @property
    def name(self) -> str:
        name = self.coordinator.config_entry.data.get(CONF_NAME, "object_name")
        if name == "description":
            return f"{self.coordinator.data.devices[self.deviceid].objects[self.objectid].description}"
        elif name == "object_identifier":
            identifier = (
                self.coordinator.data.devices[self.deviceid]
                .objects[self.objectid]
                .objectIdentifier
            )
            return f"{identifier[0]}:{identifier[1]}"
        else:
            return f"{self.coordinator.data.devices[self.deviceid].objects[self.objectid].objectName}"

    @property
    def entity_registry_enabled_default(self) -> bool:
        """Return if the entity should be enabled when first added to the entity registry."""
        return self.coordinator.config_entry.data.get(CONF_ENABLED, False)

    @property
    def native_value(self):
        value = (
            self.coordinator.data.devices[self.deviceid]
            .objects[self.objectid]
            .presentValue
        )
        
        if value is None:
            return value

        if (
            resolution := self.coordinator.data.devices[self.deviceid]
            .objects[self.objectid]
            .resolution
        ):
            if resolution >= 1:
                return int(value)
            resolution = decimal_places_needed(resolution)
            #LOGGER.warning(f"Val {value} Res {resolution}!")
            return round(value, resolution)
        elif (
            covIncrement := self.coordinator.data.devices[self.deviceid]
            .objects[self.objectid]
            .covIncrement
        ):
            if covIncrement >= 1:
                return int(value)
            covIncrement = decimal_places_needed(covIncrement)
            return round(value, covIncrement)

        return round(value, 1)

    @property
    def icon(self):
        return "mdi:gauge"

    @property
    def device_class(self) -> str | None:
        if (
            units := self.coordinator.data.devices[self.deviceid]
            .objects[self.objectid]
            .units
        ):
            return bacnet_to_device_class(units, DEVICE_CLASS_UNITS)
        else:
            return None

    @property
    def native_unit_of_measurement(self) -> str | None:
        if (
            units := self.coordinator.data.devices[self.deviceid]
            .objects[self.objectid]
            .units
        ):
            return bacnet_to_ha_units(units)
        else:
            return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "inAlarm": bool(
                self.coordinator.data.devices[self.deviceid]
                .objects[self.objectid]
                .statusFlags[0]
            ),
            "fault": bool(
                self.coordinator.data.devices[self.deviceid]
                .objects[self.objectid]
                .statusFlags[1]
            ),
            "overridden": bool(
                self.coordinator.data.devices[self.deviceid]
                .objects[self.objectid]
                .statusFlags[2]
            ),
            "outOfService": bool(
                self.coordinator.data.devices[self.deviceid]
                .objects[self.objectid]
                .statusFlags[3]
            ),
            "reliability": self.coordinator.data.devices[self.deviceid]
            .objects[self.objectid]
            .reliability,
            "eventState": self.coordinator.data.devices[self.deviceid]
            .objects[self.objectid]
            .eventState,
        }

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self.deviceid)},
            name=f"{self.coordinator.data.devices[self.deviceid].objects[self.deviceid].objectName}",
            manufacturer=self.coordinator.data.devices[self.deviceid]
            .objects[self.deviceid]
            .vendorName,
            model=self.coordinator.data.devices[self.deviceid]
            .objects[self.deviceid]
            .modelName,
        )

    @property
    def state_class(self) -> str:
        if self.native_unit_of_measurement in UnitOfEnergy:
            return "total"
        elif self.native_unit_of_measurement in UnitOfVolume:
            return "total"
        else:
            return "measurement"


class MultiStateInputEntity(
    CoordinatorEntity[EcoPanelDataUpdateCoordinator], SensorEntity
):
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: EcoPanelDataUpdateCoordinator,
        deviceid: str,
        objectid: str,
    ):
        """Initialize a BACnet MultiStateInput object as entity."""
        super().__init__(coordinator=coordinator)
        self.deviceid = deviceid
        self.objectid = objectid

    @property
    def unique_id(self) -> str:
        return f"{self.deviceid}_{self.objectid}"

    @property
    def name(self) -> str:
        name = self.coordinator.config_entry.data.get(CONF_NAME, "object_name")
        if name == "description":
            return f"{self.coordinator.data.devices[self.deviceid].objects[self.objectid].description}"
        elif name == "object_identifier":
            identifier = (
                self.coordinator.data.devices[self.deviceid]
                .objects[self.objectid]
                .objectIdentifier
            )
            return f"{identifier[0]}:{identifier[1]}"
        else:
            return f"{self.coordinator.data.devices[self.deviceid].objects[self.objectid].objectName}"

    @property
    def entity_registry_enabled_default(self) -> bool:
        """Return if the entity should be enabled when first added to the entity registry."""
        return self.coordinator.config_entry.data.get(CONF_ENABLED, False)

    @property
    def native_value(self):
        state_val = (
            self.coordinator.data.devices[self.deviceid]
            .objects[self.objectid]
            .presentValue
        )

        if (
            state_text := self.coordinator.data.devices[self.deviceid]
            .objects[self.objectid]
            .stateText
        ):
            return state_text[state_val - STATETEXT_OFFSET]  # JCO
        else:
            return state_val

    @property
    def icon(self):
        return "mdi:menu"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "inAlarm": bool(
                self.coordinator.data.devices[self.deviceid]
                .objects[self.objectid]
                .statusFlags[0]
            ),
            "fault": bool(
                self.coordinator.data.devices[self.deviceid]
                .objects[self.objectid]
                .statusFlags[1]
            ),
            "overridden": bool(
                self.coordinator.data.devices[self.deviceid]
                .objects[self.objectid]
                .statusFlags[2]
            ),
            "outOfService": bool(
                self.coordinator.data.devices[self.deviceid]
                .objects[self.objectid]
                .statusFlags[3]
            ),
            "reliability": self.coordinator.data.devices[self.deviceid]
            .objects[self.objectid]
            .reliability,
            "eventState": self.coordinator.data.devices[self.deviceid]
            .objects[self.objectid]
            .eventState,
        }

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self.deviceid)},
            name=f"{self.coordinator.data.devices[self.deviceid].objects[self.deviceid].objectName}",
            manufacturer=self.coordinator.data.devices[self.deviceid]
            .objects[self.deviceid]
            .vendorName,
            model=self.coordinator.data.devices[self.deviceid]
            .objects[self.deviceid]
            .modelName,
        )


def bacnet_device_info(
    coordinator: EcoPanelDataUpdateCoordinator,
    deviceid: str,
    info_coordinator: EcoPanelDeviceInfoCoordinator | None = None,
) -> DeviceInfo:
    """Device info for a BACnet device, based on its device object."""
    device_object = coordinator.data.devices[deviceid].objects.get(deviceid)
    device_info = DeviceInfo(
        identifiers={(DOMAIN, deviceid)},
        name=device_object.objectName if device_object else deviceid,
        manufacturer=device_object.vendorName if device_object else None,
        model=device_object.modelName if device_object else None,
    )
    info = ((info_coordinator and info_coordinator.data) or {}).get(deviceid) or {}
    versions = [
        version
        for version in (
            info.get("firmwareRevision"),
            info.get("applicationSoftwareVersion")
            and f"application {info.get('applicationSoftwareVersion')}",
        )
        if version
    ]
    if versions:
        device_info["sw_version"] = ", ".join(versions)
    return device_info


class DeviceIdEntity(CoordinatorEntity[EcoPanelDataUpdateCoordinator], SensorEntity):
    """Diagnostic sensor showing the BACnet device instance."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:identifier"
    _attr_name = "Device ID"

    def __init__(
        self,
        coordinator: EcoPanelDataUpdateCoordinator,
        info_coordinator: EcoPanelDeviceInfoCoordinator,
        deviceid: str,
    ):
        super().__init__(coordinator=coordinator)
        self.deviceid = deviceid
        self._attr_unique_id = f"{deviceid}_deviceid"
        self._attr_device_info = bacnet_device_info(
            coordinator, deviceid, info_coordinator
        )

    @property
    def native_value(self) -> int | str:
        instance = self.deviceid.split(":")[-1]
        return int(instance) if instance.isdigit() else self.deviceid


class DeviceInfoEntity(CoordinatorEntity[EcoPanelDeviceInfoCoordinator], SensorEntity):
    """Base for diagnostic sensors fed by the add-on's device info endpoint."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _info_key: str = ""
    _unique_suffix: str = ""

    def __init__(
        self,
        coordinator: EcoPanelDeviceInfoCoordinator,
        data_coordinator: EcoPanelDataUpdateCoordinator,
        deviceid: str,
    ):
        super().__init__(coordinator=coordinator)
        self.deviceid = deviceid
        self._attr_unique_id = f"{deviceid}_{self._unique_suffix}"
        self._attr_device_info = bacnet_device_info(
            data_coordinator, deviceid, coordinator
        )

    @property
    def _info(self) -> dict[str, Any]:
        return (self.coordinator.data or {}).get(self.deviceid) or {}

    @property
    def available(self) -> bool:
        return super().available and self._info.get(self._info_key) is not None


class IpAddressEntity(DeviceInfoEntity):
    """Diagnostic sensor showing the IP address of a BACnet device.

    For routed devices this is the address of the router, the full BACnet
    address is available as an attribute.
    """

    _attr_icon = "mdi:ip-network"
    _attr_name = "IP address"
    _info_key = "ip_address"
    _unique_suffix = "ipaddress"

    @property
    def available(self) -> bool:
        # the BACnet address is useful even when the IP address is unknown
        return super(DeviceInfoEntity, self).available and bool(self._info)

    @property
    def native_value(self) -> str | None:
        return self._info.get("ip_address")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"bacnet_address": self._info.get("address")}


class SystemStatusEntity(DeviceInfoEntity):
    """Diagnostic sensor showing the device's reported system status."""

    _attr_icon = "mdi:heart-pulse"
    _attr_name = "System status"
    _info_key = "systemStatus"
    _unique_suffix = "systemstatus"

    @property
    def native_value(self) -> str | None:
        return self._info.get("systemStatus")


class DatabaseRevisionEntity(DeviceInfoEntity):
    """Diagnostic sensor showing the device's database revision.

    The device increments it whenever its configuration or program changes.
    """

    _attr_icon = "mdi:database-edit"
    _attr_name = "Database revision"
    _info_key = "databaseRevision"
    _unique_suffix = "databaserevision"

    @property
    def native_value(self) -> int | None:
        return self._info.get("databaseRevision")


class CovSubscriptionsEntity(DeviceInfoEntity):
    """Diagnostic sensor counting the device's active COV subscriptions."""

    _attr_icon = "mdi:bell-ring-outline"
    _attr_name = "CoV subscriptions"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _info_key = "cov_subscriptions"
    _unique_suffix = "covsubscriptions"

    @property
    def native_value(self) -> int | None:
        return (self._info.get("cov_subscriptions") or {}).get("total")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        subscriptions = self._info.get("cov_subscriptions") or {}
        return {
            "own": subscriptions.get("own"),
            "by_recipient": subscriptions.get("by_recipient"),
            "min_time_remaining_by_recipient": subscriptions.get(
                "min_time_remaining_by_recipient"
            ),
        }
