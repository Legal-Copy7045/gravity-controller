import esphome.codegen as cg
from esphome.components import number
import esphome.config_validation as cv
from esphome.const import DEVICE_CLASS_TEMPERATURE
from esphome.core import CORE

from . import CONF_GRAVITY980_ID, CONF_TEMPERATURE_UNIT, GRAVITY980_CHILD_SCHEMA, gravity980_ns

DEPENDENCIES = ["gravity980"]

Gravity980TargetNumber = gravity980_ns.class_("Gravity980TargetNumber", number.Number, cg.Component)

# (probe enum, min °F, max °F)
KEYS = {
    "pit_target": ("PROBE_PIT", 200, 700, "mdi:thermometer-chevron-up"),
    "food1_target": ("PROBE_FOOD1", 50, 350, "mdi:target"),
    "food2_target": ("PROBE_FOOD2", 50, 350, "mdi:target"),
}

CONFIG_SCHEMA = GRAVITY980_CHILD_SCHEMA.extend(
    {
        cv.Optional(k): number.number_schema(
            Gravity980TargetNumber, device_class=DEVICE_CLASS_TEMPERATURE, icon=v[3]
        ).extend(cv.COMPONENT_SCHEMA)
        for k, v in KEYS.items()
    }
)


def _f_to_c(f):
    return round((f - 32) * 5 / 9)


async def to_code(config):
    parent = await cg.get_variable(config[CONF_GRAVITY980_ID])
    hub = CORE.config.get("gravity980") or {}
    fahrenheit = hub.get(CONF_TEMPERATURE_UNIT, "F") == "F"
    for key, (probe, lo, hi, _) in KEYS.items():
        if key not in config:
            continue
        conf = dict(config[key])
        conf.setdefault("unit_of_measurement", "°F" if fahrenheit else "°C")
        if fahrenheit:
            n = await number.new_number(conf, min_value=lo, max_value=hi, step=5)
        else:
            n = await number.new_number(conf, min_value=_f_to_c(lo) + 1, max_value=_f_to_c(hi), step=1)
        await cg.register_component(n, conf)
        cg.add(n.set_parent(parent))
        p = cg.RawExpression(f"esphome::gravity980::{probe}")
        cg.add(n.set_probe(p))
        cg.add(parent.set_target_number(p, n))
