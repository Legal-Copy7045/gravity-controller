import esphome.codegen as cg
from esphome.components import sensor
import esphome.config_validation as cv
from esphome.const import DEVICE_CLASS_TEMPERATURE, STATE_CLASS_MEASUREMENT

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


CONFIG_SCHEMA = GRAVITY980_CHILD_SCHEMA.extend({cv.Optional(k): _schema(v[2]) for k, v in KEYS.items()})


async def to_code(config):
    from esphome.core import CORE

    parent = await cg.get_variable(config[CONF_GRAVITY980_ID])
    hub = CORE.config.get("gravity980") or {}
    unit = "°F" if hub.get(CONF_TEMPERATURE_UNIT, "F") == "F" else "°C"
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
