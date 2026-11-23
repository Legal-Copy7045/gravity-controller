import esphome.codegen as cg
from esphome.components import button
import esphome.config_validation as cv
from esphome.const import ENTITY_CATEGORY_CONFIG

from . import CONF_GRAVITY980_ID, GRAVITY980_CHILD_SCHEMA, gravity980_ns

DEPENDENCIES = ["gravity980"]

CaptureClearButton = gravity980_ns.class_("CaptureClearButton", button.Button, cg.Component)

CONFIG_SCHEMA = GRAVITY980_CHILD_SCHEMA.extend(
    {
        # Capture mode: forget the recorded writes.
        cv.Optional("clear_capture"): button.button_schema(
            CaptureClearButton, entity_category=ENTITY_CATEGORY_CONFIG, icon="mdi:delete-sweep"
        ).extend(cv.COMPONENT_SCHEMA),
    }
)


async def to_code(config):
    parent = await cg.get_variable(config[CONF_GRAVITY980_ID])
    if "clear_capture" in config:
        b = await button.new_button(config["clear_capture"])
        await cg.register_component(b, config["clear_capture"])
        cg.add(b.set_capture(parent.capture().address))
