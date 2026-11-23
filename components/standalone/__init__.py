"""Run without Home Assistant: the device page's PIN and secrets, direct notifications, on-device weather and time
zone. See docs/standalone.md."""

import esphome.codegen as cg
from esphome.components import sensor
import esphome.config_validation as cv
from esphome.const import CONF_ID

DEPENDENCIES = ["web_server_base", "network"]
AUTO_LOAD = ["json"]

standalone_ns = cg.esphome_ns.namespace("standalone")
Standalone = standalone_ns.class_("Standalone", cg.Component)
CookAssistant = cg.esphome_ns.namespace("cook_assistant").class_("CookAssistant", cg.Component)

CONFIG_SCHEMA = cv.Schema(
    {
        cv.GenerateID(): cv.declare_id(Standalone),
        cv.Optional("temperature_unit", default="F"): cv.one_of("F", "C", upper=True),
        cv.Optional("wind_speed_unit", default="mph"): cv.one_of("mph", "km/h", "m/s"),
        # Sensors the on-device weather (Open-Meteo) publishes to while a location is set.
        cv.Optional("outdoor_temperature"): cv.use_id(sensor.Sensor),
        cv.Optional("outdoor_humidity"): cv.use_id(sensor.Sensor),
        cv.Optional("wind_speed"): cv.use_id(sensor.Sensor),
        cv.Optional("cook_assistant"): cv.use_id(CookAssistant),
        # For the device page's chart.
        cv.Optional("pit_temperature"): cv.use_id(sensor.Sensor),
        cv.Optional("pit_target"): cv.use_id(sensor.Sensor),
    }
).extend(cv.COMPONENT_SCHEMA)


async def to_code(config):
    var = cg.new_Pvariable(config[CONF_ID])
    await cg.register_component(var, config)
    cg.add(var.set_fahrenheit(config["temperature_unit"] == "F"))
    cg.add(var.set_wind_unit({"mph": "mph", "km/h": "kmh", "m/s": "ms"}[config["wind_speed_unit"]]))
    if all(k in config for k in ("outdoor_temperature", "outdoor_humidity", "wind_speed")):
        cg.add(var.set_weather_sensors(await cg.get_variable(config["outdoor_temperature"]),
                                       await cg.get_variable(config["outdoor_humidity"]),
                                       await cg.get_variable(config["wind_speed"])))
    if "pit_temperature" in config and "pit_target" in config:
        cg.add(var.set_pit_sensors(await cg.get_variable(config["pit_temperature"]),
                                   await cg.get_variable(config["pit_target"])))
    if "cook_assistant" in config:
        cg.add(var.set_cook_assistant(await cg.get_variable(config["cook_assistant"])))
