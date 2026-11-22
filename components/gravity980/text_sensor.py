import esphome.codegen as cg
from esphome.components import text_sensor
import esphome.config_validation as cv
from esphome.const import ENTITY_CATEGORY_DIAGNOSTIC

from . import CONF_GRAVITY980_ID, GRAVITY980_CHILD_SCHEMA

DEPENDENCIES = ["gravity980"]

CONFIG_SCHEMA = GRAVITY980_CHILD_SCHEMA.extend(
    {
        cv.Optional("raw_frame"): text_sensor.text_sensor_schema(
            entity_category=ENTITY_CATEGORY_DIAGNOSTIC, icon="mdi:hexadecimal"
        ),
        cv.Optional("link"): text_sensor.text_sensor_schema(
            entity_category=ENTITY_CATEGORY_DIAGNOSTIC, icon="mdi:connection"
        ),
        # The grill's own Wi-Fi report (over Bluetooth): network, IP, signal, status code.
        cv.Optional("grill_wifi"): text_sensor.text_sensor_schema(
            entity_category=ENTITY_CATEGORY_DIAGNOSTIC, icon="mdi:wifi-cog"
        ),
        # The Wi-Fi networks the grill can see (after "Grill Wi-Fi: scan").
        cv.Optional("wifi_networks"): text_sensor.text_sensor_schema(
            entity_category=ENTITY_CATEGORY_DIAGNOSTIC, icon="mdi:wifi-star"
        ),
    }
)


async def to_code(config):
    parent = await cg.get_variable(config[CONF_GRAVITY980_ID])
    if "raw_frame" in config:
        cg.add(parent.set_raw_frame_text_sensor(await text_sensor.new_text_sensor(config["raw_frame"])))
    if "link" in config:
        cg.add(parent.set_transport_text_sensor(await text_sensor.new_text_sensor(config["link"])))
    if "wifi_networks" in config:
        cg.add(parent.set_wifi_networks_text_sensor(await text_sensor.new_text_sensor(config["wifi_networks"])))
    if "grill_wifi" in config:
        cg.add(parent.set_wifi_text_sensor(await text_sensor.new_text_sensor(config["grill_wifi"])))
