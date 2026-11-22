"""Cook assistant: learning cook-time prediction, stall detection, cook programs and alerts.

Works with any ESPHome temperature sensors, so it serves both the stock-controller
bridge (gravity980) and the future replacement controller.
"""

from esphome import automation
import esphome.codegen as cg
from esphome.components import binary_sensor, button, number, select, sensor, switch, text, text_sensor
import esphome.config_validation as cv
from esphome.const import (
    CONF_ID,
    CONF_NAME,
    CONF_TIME_ID,
    CONF_TRIGGER_ID,
    DEVICE_CLASS_DURATION,
    DEVICE_CLASS_PROBLEM,
    DEVICE_CLASS_RUNNING,
    ENTITY_CATEGORY_CONFIG,
    ENTITY_CATEGORY_DIAGNOSTIC,
    STATE_CLASS_MEASUREMENT,
    UNIT_MINUTE,
)

CODEOWNERS = []
AUTO_LOAD = ["sensor", "binary_sensor", "text_sensor", "number", "select", "switch", "button", "text"]

ca_ns = cg.esphome_ns.namespace("cook_assistant")
CookAssistant = ca_ns.class_("CookAssistant", cg.Component)
FoodProbe = ca_ns.struct("FoodProbe")
CANumber = ca_ns.class_("CANumber", number.Number, cg.Component)
CASelect = ca_ns.class_("CASelect", select.Select, cg.Component)
CASwitch = ca_ns.class_("CASwitch", switch.Switch, cg.Component)
CAButton = ca_ns.class_("CAButton", button.Button)
CAText = ca_ns.class_("CAText", text.Text, cg.Component)
NotifyTrigger = ca_ns.class_(
    "NotifyTrigger", automation.Trigger.template(cg.std_string, cg.std_string, cg.int_, cg.std_string)
)
SetPitTrigger = ca_ns.class_("SetPitTrigger", automation.Trigger.template(cg.float_))
CookCompleteTrigger = ca_ns.class_("CookCompleteTrigger", automation.Trigger.template(cg.std_string))

PROFILES = ["Auto", "Pork shoulder", "Brisket", "Ribs", "Beef roast", "Poultry", "Sausage", "Fish"]

CONF_TEMPERATURE_UNIT = "temperature_unit"
CONF_PROBES = "probes"
CONF_KEY = "key"
CONF_PRESETS = "presets"
CONF_PROGRAM = "program"

U_PER_HOUR = "°/h"


def _ref(cls):
    return cv.use_id(cls)


def _min_sensor(icon):
    return sensor.sensor_schema(
        unit_of_measurement=UNIT_MINUTE,
        device_class=DEVICE_CLASS_DURATION,
        state_class=STATE_CLASS_MEASUREMENT,
        accuracy_decimals=0,
        icon=icon,
    )


PROBE_SCHEMA = cv.Schema(
    {
        cv.GenerateID(): cv.declare_id(FoodProbe),
        cv.Required(CONF_KEY): cv.All(cv.string, cv.Length(min=1, max=16)),
        cv.Required(CONF_NAME): cv.string,
        cv.Required("temperature"): _ref(sensor.Sensor),
        cv.Optional("target"): _ref(sensor.Sensor),
        cv.Optional("target_number"): number.number_schema(CANumber, icon="mdi:target").extend(cv.COMPONENT_SCHEMA),
        cv.Optional("profile"): select.select_schema(CASelect, icon="mdi:food-steak").extend(cv.COMPONENT_SCHEMA),
        cv.Optional("weight"): number.number_schema(CANumber, icon="mdi:weight").extend(cv.COMPONENT_SCHEMA),
        cv.Optional("wrapped"): switch.switch_schema(CASwitch, icon="mdi:package-variant-closed").extend(
            cv.COMPONENT_SCHEMA
        ),
        cv.Optional("time_remaining"): _min_sensor("mdi:timer-sand"),
        cv.Optional("time_remaining_low"): _min_sensor("mdi:timer-sand-complete"),
        cv.Optional("time_remaining_high"): _min_sensor("mdi:timer-sand-empty"),
        cv.Optional("estimated_total"): _min_sensor("mdi:clock-outline"),
        cv.Optional("stall_remaining"): _min_sensor("mdi:timer-pause"),
        cv.Optional("rate"): sensor.sensor_schema(
            unit_of_measurement=U_PER_HOUR, state_class=STATE_CLASS_MEASUREMENT, accuracy_decimals=1,
            icon="mdi:trending-up",
        ),
        cv.Optional("finish_time"): text_sensor.text_sensor_schema(icon="mdi:clock-check"),
        cv.Optional("phase"): text_sensor.text_sensor_schema(icon="mdi:progress-clock"),
        cv.Optional("estimate_info"): text_sensor.text_sensor_schema(
            icon="mdi:information-outline", entity_category=ENTITY_CATEGORY_DIAGNOSTIC
        ),
        cv.Optional("stall"): binary_sensor.binary_sensor_schema(icon="mdi:pause-octagon"),
        cv.Optional("probe_warning"): binary_sensor.binary_sensor_schema(device_class=DEVICE_CLASS_PROBLEM),
        # rest coach
        cv.Optional("pulled"): switch.switch_schema(CASwitch, icon="mdi:silverware-fork").extend(cv.COMPONENT_SCHEMA),
        cv.Optional("pull_at"): sensor.sensor_schema(accuracy_decimals=0, icon="mdi:thermometer-chevron-down"),
        cv.Optional("rest_ready"): _min_sensor("mdi:timer-sand-paused"),
    }
)

PRESET_SCHEMA = cv.Schema({cv.Required(CONF_NAME): cv.string, cv.Required(CONF_PROGRAM): cv.string})

BUTTONS = ["start_program", "pause_program", "resume_program", "skip_step", "stop_program", "clear_history"]
BUTTON_ICONS = {
    "start_program": "mdi:play",
    "pause_program": "mdi:pause",
    "resume_program": "mdi:play-pause",
    "skip_step": "mdi:skip-next",
    "stop_program": "mdi:stop",
    "clear_history": "mdi:delete-clock",
}


def _time_schema():
    from esphome.components import time as time_

    return cv.use_id(time_.RealTimeClock)


CONFIG_SCHEMA = cv.Schema(
    {
        cv.GenerateID(): cv.declare_id(CookAssistant),
        cv.Optional(CONF_TEMPERATURE_UNIT, default="F"): cv.one_of("F", "C", upper=True),
        cv.Required("pit_temperature"): _ref(sensor.Sensor),
        cv.Optional("pit_setpoint"): _ref(sensor.Sensor),
        cv.Optional("lid"): _ref(binary_sensor.BinarySensor),
        cv.Optional("link"): _ref(binary_sensor.BinarySensor),
        cv.Optional("fan"): _ref(binary_sensor.BinarySensor),
        # fuel gauge
        cv.Optional("hopper_capacity", default=7.26): cv.positive_float,  # kg (Gravity 980: 16 lb)
        cv.Optional("fuel_level"): sensor.sensor_schema(
            unit_of_measurement="%", accuracy_decimals=0, icon="mdi:gauge", state_class=STATE_CLASS_MEASUREMENT
        ),
        cv.Optional("fuel_left"): sensor.sensor_schema(accuracy_decimals=1, icon="mdi:weight", state_class=STATE_CLASS_MEASUREMENT),
        cv.Optional("fuel_hours_left"): sensor.sensor_schema(
            unit_of_measurement="h", accuracy_decimals=1, icon="mdi:timer-sand", state_class=STATE_CLASS_MEASUREMENT
        ),
        cv.Optional("fuel_burn_rate"): sensor.sensor_schema(accuracy_decimals=2, icon="mdi:fire", state_class=STATE_CLASS_MEASUREMENT),
        cv.Optional("fuel_empty_at"): text_sensor.text_sensor_schema(icon="mdi:clock-alert-outline"),
        cv.Optional("fuel_type"): select.select_schema(CASelect, icon="mdi:fire-circle").extend(cv.COMPONENT_SCHEMA),
        cv.Optional("slice_at"): number.number_schema(CANumber, icon="mdi:knife").extend(cv.COMPONENT_SCHEMA),
        cv.Optional("ambient_temperature"): _ref(sensor.Sensor),
        cv.Optional("ambient_humidity"): _ref(sensor.Sensor),
        cv.Optional("wind_speed"): _ref(sensor.Sensor),
        # Units of the weather sensors (Home Assistant's unit system), independent of temperature_unit.
        cv.Optional("ambient_temperature_unit"): cv.one_of("F", "C", upper=True),
        cv.Optional("wind_speed_unit", default="mph"): cv.one_of("mph", "km/h", "m/s", lower=True),
        # The grill's accepted pit range (programs outside it are refused). Default: the stock controller, 200-700 °F.
        cv.Optional("pit_min", default=93.333): cv.float_,
        cv.Optional("pit_max", default=371.111): cv.float_,
        cv.Optional(CONF_TIME_ID): _time_schema(),
        cv.Required(CONF_PROBES): cv.All(cv.ensure_list(PROBE_SCHEMA), cv.Length(min=1, max=8)),
        cv.Optional(CONF_PRESETS, default=[]): cv.ensure_list(PRESET_SCHEMA),
        cv.Optional("on_set_pit"): automation.validate_automation(
            {cv.GenerateID(CONF_TRIGGER_ID): cv.declare_id(SetPitTrigger)}
        ),
        cv.Optional("on_notify"): automation.validate_automation(
            {cv.GenerateID(CONF_TRIGGER_ID): cv.declare_id(NotifyTrigger)}
        ),
        cv.Optional("on_cook_complete"): automation.validate_automation(
            {cv.GenerateID(CONF_TRIGGER_ID): cv.declare_id(CookCompleteTrigger)}
        ),
        cv.Optional("cook_active"): binary_sensor.binary_sensor_schema(
            device_class=DEVICE_CLASS_RUNNING, icon="mdi:grill"
        ),
        cv.Optional("cook_elapsed"): _min_sensor("mdi:timer-outline"),
        cv.Optional("history_count"): sensor.sensor_schema(
            accuracy_decimals=0, icon="mdi:history", entity_category=ENTITY_CATEGORY_DIAGNOSTIC
        ),
        cv.Optional("grill_factor"): sensor.sensor_schema(
            accuracy_decimals=2, icon="mdi:tune", entity_category=ENTITY_CATEGORY_DIAGNOSTIC
        ),
        cv.Optional("program_status"): text_sensor.text_sensor_schema(icon="mdi:format-list-numbered"),
        cv.Optional("program_state"): text_sensor.text_sensor_schema(icon="mdi:state-machine"),
        cv.Optional("program_error"): text_sensor.text_sensor_schema(
            icon="mdi:alert-circle-outline", entity_category=ENTITY_CATEGORY_DIAGNOSTIC
        ),
        cv.Optional("program_text"): text.text_schema(CAText, icon="mdi:script-text").extend(cv.COMPONENT_SCHEMA),
        cv.Optional("preset"): select.select_schema(CASelect, icon="mdi:book-open-variant").extend(
            cv.COMPONENT_SCHEMA
        ),
        cv.Optional("alerts_enabled"): switch.switch_schema(
            CASwitch, icon="mdi:bell", entity_category=ENTITY_CATEGORY_CONFIG, default_restore_mode="RESTORE_DEFAULT_ON"
        ).extend(cv.COMPONENT_SCHEMA),
        **{cv.Optional(b): button.button_schema(CAButton, icon=BUTTON_ICONS[b]) for b in BUTTONS},
    }
).extend(cv.COMPONENT_SCHEMA)


async def to_code(config):
    var = cg.new_Pvariable(config[CONF_ID])
    await cg.register_component(var, config)
    fahrenheit = config[CONF_TEMPERATURE_UNIT] == "F"
    tunit = "°F" if fahrenheit else "°C"
    cg.add(var.set_fahrenheit(fahrenheit))

    cg.add(var.set_pit_temperature(await cg.get_variable(config["pit_temperature"])))
    for key, setter in [
        ("pit_setpoint", "set_pit_setpoint"),
        ("lid", "set_lid"),
        ("link", "set_link"),
        ("ambient_temperature", "set_ambient_temperature"),
        ("ambient_humidity", "set_ambient_humidity"),
        ("wind_speed", "set_wind_speed"),
    ]:
        if key in config:
            cg.add(getattr(var, setter)(await cg.get_variable(config[key])))
    amb = config.get("ambient_temperature_unit", config[CONF_TEMPERATURE_UNIT])
    cg.add(var.set_ambient_fahrenheit(amb == "F"))
    cg.add(var.set_wind_to_kmh({"mph": 1.609344, "km/h": 1.0, "m/s": 3.6}[config["wind_speed_unit"]]))
    cg.add(var.set_pit_range(config["pit_min"], config["pit_max"]))
    if "fan" in config:
        cg.add(var.set_fan(await cg.get_variable(config["fan"])))
    cg.add(var.set_hopper_capacity_kg(config["hopper_capacity"]))
    if "fuel_level" in config:
        cg.add(var.set_fuel_level_sensor(await sensor.new_sensor(config["fuel_level"])))
    if "fuel_left" in config:
        c = dict(config["fuel_left"])
        c["unit_of_measurement"] = "lb" if fahrenheit else "kg"
        cg.add(var.set_fuel_left_sensor(await sensor.new_sensor(c)))
    if "fuel_hours_left" in config:
        cg.add(var.set_fuel_hours_sensor(await sensor.new_sensor(config["fuel_hours_left"])))
    if "fuel_burn_rate" in config:
        c = dict(config["fuel_burn_rate"])
        c["unit_of_measurement"] = "lb/h" if fahrenheit else "kg/h"
        cg.add(var.set_fuel_rate_sensor(await sensor.new_sensor(c)))
    if "fuel_empty_at" in config:
        cg.add(var.set_fuel_empty_text_sensor(await text_sensor.new_text_sensor(config["fuel_empty_at"])))
    if "fuel_type" in config:
        s = await select.new_select(config["fuel_type"], options=["Briquettes", "Lump"])
        await cg.register_component(s, config["fuel_type"])
        cg.add(var.set_fuel_type_select(s))
    if "slice_at" in config:
        c = dict(config["slice_at"])
        c.setdefault("unit_of_measurement", tunit)
        lo, hi, st = (100, 200, 1) if fahrenheit else (38, 93, 0.5)
        n = await number.new_number(c, min_value=lo, max_value=hi, step=st)
        await cg.register_component(n, c)
        cg.add(n.set_initial(150 if fahrenheit else 65.5))
        cg.add(var.set_slice_number(n))
    if CONF_TIME_ID in config:
        cg.add(var.set_time(await cg.get_variable(config[CONF_TIME_ID])))

    for p in config[CONF_PROBES]:
        pv = cg.new_Pvariable(p[CONF_ID])
        cg.add(cg.RawExpression(f"{pv}->key = {cg.safe_exp(p[CONF_KEY])}"))
        cg.add(cg.RawExpression(f"{pv}->name = {cg.safe_exp(p[CONF_NAME])}"))
        t = await cg.get_variable(p["temperature"])
        cg.add(cg.RawExpression(f"{pv}->temperature = {t}"))
        if "target" in p:
            tg = await cg.get_variable(p["target"])
            cg.add(cg.RawExpression(f"{pv}->target = {tg}"))
        if "target_number" in p:
            c = dict(p["target_number"])
            c.setdefault("unit_of_measurement", tunit)
            lo, hi, st = (100, 220, 1) if fahrenheit else (38, 105, 0.5)
            n = await number.new_number(c, min_value=lo, max_value=hi, step=st)
            await cg.register_component(n, c)
            cg.add(n.set_initial(203 if fahrenheit else 95))
            cg.add(cg.RawExpression(f"{pv}->target_number = {n}"))
        if "profile" in p:
            s = await select.new_select(p["profile"], options=PROFILES)
            await cg.register_component(s, p["profile"])
            cg.add(cg.RawExpression(f"{pv}->profile = {s}"))
        if "weight" in p:
            c = dict(p["weight"])
            c.setdefault("unit_of_measurement", "lb" if fahrenheit else "kg")
            n = await number.new_number(c, min_value=0, max_value=40 if fahrenheit else 18, step=0.1)
            await cg.register_component(n, c)
            cg.add(cg.RawExpression(f"{pv}->weight = {n}"))
        if "wrapped" in p:
            s = await switch.new_switch(p["wrapped"])
            await cg.register_component(s, p["wrapped"])
            cg.add(cg.RawExpression(f"{pv}->wrapped = {s}"))
        for key, field in [
            ("time_remaining", "remaining"),
            ("time_remaining_low", "remaining_low"),
            ("time_remaining_high", "remaining_high"),
            ("estimated_total", "estimated_total"),
            ("stall_remaining", "stall_remaining"),
        ]:
            if key in p:
                s = await sensor.new_sensor(p[key])
                cg.add(cg.RawExpression(f"{pv}->{field} = {s}"))
        if "rate" in p:
            c = dict(p["rate"])
            c["unit_of_measurement"] = "°F/h" if fahrenheit else "°C/h"
            s = await sensor.new_sensor(c)
            cg.add(cg.RawExpression(f"{pv}->rate = {s}"))
        for key in ["finish_time", "phase", "estimate_info"]:
            if key in p:
                s = await text_sensor.new_text_sensor(p[key])
                cg.add(cg.RawExpression(f"{pv}->{key} = {s}"))
        for key in ["stall", "probe_warning"]:
            if key in p:
                s = await binary_sensor.new_binary_sensor(p[key])
                cg.add(cg.RawExpression(f"{pv}->{key} = {s}"))
        if "pulled" in p:
            s = await switch.new_switch(p["pulled"])
            await cg.register_component(s, p["pulled"])
            cg.add(cg.RawExpression(f"{pv}->pulled = {s}"))
        if "pull_at" in p:
            c = dict(p["pull_at"])
            c["unit_of_measurement"] = tunit
            s = await sensor.new_sensor(c)
            cg.add(cg.RawExpression(f"{pv}->pull_at = {s}"))
        if "rest_ready" in p:
            s = await sensor.new_sensor(p["rest_ready"])
            cg.add(cg.RawExpression(f"{pv}->rest_ready = {s}"))
        cg.add(var.add_probe(pv))

    for pr in config[CONF_PRESETS]:
        cg.add(var.add_preset(pr[CONF_NAME], pr[CONF_PROGRAM]))

    if "cook_active" in config:
        cg.add(var.set_cook_active_binary_sensor(await binary_sensor.new_binary_sensor(config["cook_active"])))
    if "cook_elapsed" in config:
        cg.add(var.set_cook_elapsed_sensor(await sensor.new_sensor(config["cook_elapsed"])))
    if "history_count" in config:
        cg.add(var.set_history_count_sensor(await sensor.new_sensor(config["history_count"])))
    if "grill_factor" in config:
        cg.add(var.set_grill_factor_sensor(await sensor.new_sensor(config["grill_factor"])))
    for key, setter in [
        ("program_status", "set_program_status_text_sensor"),
        ("program_state", "set_program_state_text_sensor"),
        ("program_error", "set_program_error_text_sensor"),
    ]:
        if key in config:
            cg.add(getattr(var, setter)(await text_sensor.new_text_sensor(config[key])))
    if "program_text" in config:
        t = await text.new_text(config["program_text"], max_length=255)
        await cg.register_component(t, config["program_text"])
        cg.add(var.set_program_text(t))
    if "preset" in config:
        names = [p[CONF_NAME] for p in config[CONF_PRESETS]] + ["Custom"]
        s = await select.new_select(config["preset"], options=names)
        await cg.register_component(s, config["preset"])
        cg.add(s.set_restore(False))
        cg.add(var.set_preset_select(s))
    if "alerts_enabled" in config:
        s = await switch.new_switch(config["alerts_enabled"])
        await cg.register_component(s, config["alerts_enabled"])
        cg.add(var.set_alerts_switch(s))
    for b in BUTTONS:
        if b in config:
            btn = await button.new_button(config[b])
            cg.add(btn.set_on_press(cg.RawExpression(f"[]() {{ {var}->{b}(); }}")))

    for conf in config.get("on_set_pit", []):
        trig = cg.new_Pvariable(conf[CONF_TRIGGER_ID], var)
        await automation.build_automation(trig, [(cg.float_, "x")], conf)
    for conf in config.get("on_notify", []):
        trig = cg.new_Pvariable(conf[CONF_TRIGGER_ID], var)
        await automation.build_automation(
            trig, [(cg.std_string, "title"), (cg.std_string, "message"), (cg.int_, "priority"), (cg.std_string, "tag")],
            conf,
        )
    for conf in config.get("on_cook_complete", []):
        trig = cg.new_Pvariable(conf[CONF_TRIGGER_ID], var)
        await automation.build_automation(trig, [(cg.std_string, "json")], conf)
