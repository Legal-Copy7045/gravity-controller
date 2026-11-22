import esphome.codegen as cg
from esphome.components import binary_sensor
import esphome.config_validation as cv
from esphome.const import DEVICE_CLASS_CONNECTIVITY, DEVICE_CLASS_DOOR, DEVICE_CLASS_PROBLEM, DEVICE_CLASS_RUNNING, ENTITY_CATEGORY_DIAGNOSTIC

from . import CONF_GRAVITY980_ID, GRAVITY980_CHILD_SCHEMA

DEPENDENCIES = ["gravity980"]

KEYS = {
    "connected": ("set_connected_binary_sensor", dict(device_class=DEVICE_CLASS_CONNECTIVITY, entity_category=ENTITY_CATEGORY_DIAGNOSTIC)),
    "door": ("set_door_binary_sensor", dict(device_class=DEVICE_CLASS_DOOR)),
    "fan": ("set_fan_binary_sensor", dict(device_class=DEVICE_CLASS_RUNNING, icon="mdi:fan")),
    "fan_turbo": ("set_fan_turbo_binary_sensor", dict(icon="mdi:fan-plus")),
    "alarm": ("set_alarm_binary_sensor", dict(device_class=DEVICE_CLASS_PROBLEM, icon="mdi:alarm-light")),
}

CONFIG_SCHEMA = GRAVITY980_CHILD_SCHEMA.extend(
    {cv.Optional(k): binary_sensor.binary_sensor_schema(**v[1]) for k, v in KEYS.items()}
)


async def to_code(config):
    parent = await cg.get_variable(config[CONF_GRAVITY980_ID])
    for key, (setter, _) in KEYS.items():
        if key in config:
            b = await binary_sensor.new_binary_sensor(config[key])
            cg.add(getattr(parent, setter)(b))
