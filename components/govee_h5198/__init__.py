"""Govee H5198 4-probe meat thermometer, read directly from its Bluetooth advertisements."""

import esphome.codegen as cg
from esphome.components import binary_sensor, ble_device_base, sensor
import esphome.config_validation as cv
from esphome.const import (
    CONF_ID,
    CONF_MAC_ADDRESS,
    DEVICE_CLASS_CONNECTIVITY,
    DEVICE_CLASS_SIGNAL_STRENGTH,
    DEVICE_CLASS_TEMPERATURE,
    ENTITY_CATEGORY_DIAGNOSTIC,
    STATE_CLASS_MEASUREMENT,
)

AUTO_LOAD = ["ble_device_base", "sensor", "binary_sensor"]
CODEOWNERS = []

ns = cg.esphome_ns.namespace("govee_h5198")
GoveeH5198 = ns.class_("GoveeH5198", ble_device_base.ESPBTDeviceListener, cg.Component)

PROBES = [f"probe_{i}" for i in range(1, 5)]

CONFIG_SCHEMA = cv.Schema(
    {
        cv.GenerateID(): cv.declare_id(GoveeH5198),
        cv.Optional(CONF_MAC_ADDRESS): cv.mac_address,
        cv.Optional("temperature_unit", default="F"): cv.one_of("F", "C", upper=True),
        cv.Optional("log_raw", default=False): cv.boolean,
        **{
            cv.Optional(p): sensor.sensor_schema(
                device_class=DEVICE_CLASS_TEMPERATURE, state_class=STATE_CLASS_MEASUREMENT, accuracy_decimals=1,
                icon="mdi:thermometer-bluetooth",
            )
            for p in PROBES
        },
        # The high-temperature alarm set on the thermometer for each probe (its own target).
        **{
            cv.Optional(f"{p}_alarm"): sensor.sensor_schema(
                device_class=DEVICE_CLASS_TEMPERATURE, accuracy_decimals=1, icon="mdi:thermometer-alert",
                entity_category=ENTITY_CATEGORY_DIAGNOSTIC,
            )
            for p in PROBES
        },
        cv.Optional("rssi"): sensor.sensor_schema(
            unit_of_measurement="dBm", device_class=DEVICE_CLASS_SIGNAL_STRENGTH, accuracy_decimals=0,
            entity_category=ENTITY_CATEGORY_DIAGNOSTIC,
        ),
        cv.Optional("connected"): binary_sensor.binary_sensor_schema(
            device_class=DEVICE_CLASS_CONNECTIVITY, entity_category=ENTITY_CATEGORY_DIAGNOSTIC
        ),
    }
).extend(ble_device_base.BLE_DEVICE_SCHEMA).extend(cv.COMPONENT_SCHEMA)


async def to_code(config):
    var = cg.new_Pvariable(config[CONF_ID])
    await cg.register_component(var, config)
    await ble_device_base.register_ble_device(var, config)
    f = config["temperature_unit"] == "F"
    cg.add(var.set_fahrenheit(f))
    cg.add(var.set_log_raw(config["log_raw"]))
    if CONF_MAC_ADDRESS in config:
        cg.add(var.set_address(config[CONF_MAC_ADDRESS].as_hex))
    for i, p in enumerate(PROBES):
        if p in config:
            c = dict(config[p])
            c["unit_of_measurement"] = "°F" if f else "°C"
            s = await sensor.new_sensor(c)
            cg.add(var.set_probe_sensor(i, s))
        if f"{p}_alarm" in config:
            c = dict(config[f"{p}_alarm"])
            c["unit_of_measurement"] = "°F" if f else "°C"
            cg.add(var.set_alarm_sensor(i, await sensor.new_sensor(c)))
    if "rssi" in config:
        cg.add(var.set_rssi_sensor(await sensor.new_sensor(config["rssi"])))
    if "connected" in config:
        cg.add(var.set_connected_binary_sensor(await binary_sensor.new_binary_sensor(config["connected"])))
