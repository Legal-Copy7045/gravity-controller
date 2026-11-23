import esphome.codegen as cg
from esphome.components import switch
import esphome.config_validation as cv
from esphome.const import ENTITY_CATEGORY_CONFIG

from . import CONF_GRAVITY980_ID, GRAVITY980_CHILD_SCHEMA, gravity980_ns

DEPENDENCIES = ["gravity980"]

Gravity980EnableSwitch = gravity980_ns.class_("Gravity980EnableSwitch", switch.Switch, cg.Component)

CONFIG_SCHEMA = GRAVITY980_CHILD_SCHEMA.extend(
    {
        cv.Optional("bridge_enabled"): switch.switch_schema(
            Gravity980EnableSwitch,
            entity_category=ENTITY_CATEGORY_CONFIG,
            icon="mdi:lan-connect",
            default_restore_mode="RESTORE_DEFAULT_ON",
        ).extend(cv.COMPONENT_SCHEMA),
    }
)


async def to_code(config):
    parent = await cg.get_variable(config[CONF_GRAVITY980_ID])
    if "bridge_enabled" in config:
        s = await switch.new_switch(config["bridge_enabled"])
        await cg.register_component(s, config["bridge_enabled"])
        cg.add(s.set_parent(parent))
