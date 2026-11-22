import esphome.codegen as cg
from esphome.components import sensor
import esphome.config_validation as cv
from esphome.const import (
    DEVICE_CLASS_SIGNAL_STRENGTH,
    DEVICE_CLASS_TEMPERATURE,
    ENTITY_CATEGORY_DIAGNOSTIC,
    STATE_CLASS_MEASUREMENT,
    UNIT_DECIBEL_MILLIWATT,
)

from . import CONF_GRAVITY980_ID, CONF_TEMPERATURE_UNIT, GRAVITY980_CHILD_SCHEMA

DEPENDENCIES = ["gravity980"]

KEYS = {
    "pit_temperature": ("PROBE_PIT", "temp", "mdi:thermometer"),
    "pit_target": ("PROBE_PIT", "target", "mdi:thermometer-check"),
    "food1_temperature": ("PROBE_FOOD1", "temp", "mdi:food-steak"),
    "food1_target": ("PROBE_FOOD1", "target", "mdi:target"),
    "food2_temperature": ("PROBE_FOOD2", "temp", "mdi:food-drumstick"),
    "food2_target": ("PROBE_FOOD2", "target", "mdi:target"),
}


def _schema(icon):
    return sensor.sensor_schema(
        device_class=DEVICE_CLASS_TEMPERATURE,
        state_class=STATE_CLASS_MEASUREMENT,
        accuracy_decimals=0,
        icon=icon,
    )


def _signal(icon):
    return sensor.sensor_schema(
        unit_of_measurement=UNIT_DECIBEL_MILLIWATT,
        device_class=DEVICE_CLASS_SIGNAL_STRENGTH,
        state_class=STATE_CLASS_MEASUREMENT,
        entity_category=ENTITY_CATEGORY_DIAGNOSTIC,
        accuracy_decimals=0,
        icon=icon,
    )


SIGNALS = {
    # The controller <-> grill Bluetooth link (or the grill's advertisements while not connected).
    "bluetooth_signal": ("set_ble_signal_sensor", "mdi:bluetooth"),
    # The grill's own Wi-Fi to the router, as the grill reports it over Bluetooth.
    "grill_wifi_signal": ("set_grill_wifi_signal_sensor", "mdi:wifi"),
}

CONFIG_SCHEMA = GRAVITY980_CHILD_SCHEMA.extend(
    {**{cv.Optional(k): _schema(v[2]) for k, v in KEYS.items()}, **{cv.Optional(k): _signal(v[1]) for k, v in SIGNALS.items()}}
)


async def to_code(config):
    from esphome.core import CORE

    parent = await cg.get_variable(config[CONF_GRAVITY980_ID])
    hub = CORE.config.get("gravity980") or {}
    unit = "°F" if hub.get(CONF_TEMPERATURE_UNIT, "F") == "F" else "°C"
    for key, (setter, _) in SIGNALS.items():
        if key in config:
            cg.add(getattr(parent, setter)(await sensor.new_sensor(config[key])))
    for key, (probe, kind, _) in KEYS.items():
        if key not in config:
            continue
        conf = dict(config[key])
        conf.setdefault("unit_of_measurement", unit)
        s = await sensor.new_sensor(conf)
        p = cg.RawExpression(f"esphome::gravity980::{probe}")
        if kind == "temp":
            cg.add(parent.set_temperature_sensor(p, s))
        else:
            cg.add(parent.set_target_sensor(p, s))
