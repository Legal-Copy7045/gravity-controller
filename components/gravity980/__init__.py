"""Bridge to the stock Char-Griller Gravity 980 controller (Wi-Fi TCP and/or Bluetooth LE)."""

import esphome.codegen as cg
import esphome.config_validation as cv
from esphome.const import CONF_ID, CONF_MAC_ADDRESS, CONF_PORT

CONF_HOST = "host"

CODEOWNERS = []
DEPENDENCIES = ["network"]

CONF_GRAVITY980_ID = "gravity980_id"
CONF_TEMPERATURE_UNIT = "temperature_unit"
CONF_READ_ONLY = "read_only"
CONF_LOG_RAW = "log_raw"
CONF_RECONNECT_INTERVAL = "reconnect_interval"
CONF_STALE_TIMEOUT = "stale_timeout"
CONF_BLUETOOTH = "bluetooth"
CONF_NAME_PREFIX = "name_prefix"
CONF_WRITES = "writes"


def AUTO_LOAD(config=None):
    if not config or CONF_BLUETOOTH in config:
        return ["esp32_ble_client", "esp32_ble_tracker"]
    return []


gravity980_ns = cg.esphome_ns.namespace("gravity980")
Gravity980Component = gravity980_ns.class_("Gravity980Component", cg.Component)
Probe = gravity980_ns.enum("Probe")
PROBES = {
    "pit": Probe.PROBE_PIT,
    "food1": Probe.PROBE_FOOD1,
    "food2": Probe.PROBE_FOOD2,
}


def _ble_schema(value):
    from esphome.components import esp32_ble_client, esp32_ble_tracker

    Gravity980BLE = gravity980_ns.class_("Gravity980BLE", esp32_ble_client.BLEClientBase)
    schema = cv.Schema(
        {
            cv.GenerateID(): cv.declare_id(Gravity980BLE),
            cv.Optional(CONF_MAC_ADDRESS): cv.mac_address,
            cv.Optional(CONF_NAME_PREFIX, default="Gravity980"): cv.string,
            # Sending setpoints over BLE is unverified on the 980: off by default.
            cv.Optional(CONF_WRITES, default=False): cv.boolean,
        }
    ).extend(esp32_ble_tracker.ESP_BLE_DEVICE_SCHEMA)
    return schema(value)


CONFIG_SCHEMA = cv.All(
    cv.Schema(
        {
            cv.GenerateID(): cv.declare_id(Gravity980Component),
            cv.Optional(CONF_HOST, default=""): cv.string,
            cv.Optional(CONF_PORT, default=3333): cv.port,
            cv.Optional(CONF_TEMPERATURE_UNIT, default="F"): cv.one_of("F", "C", upper=True),
            cv.Optional(CONF_READ_ONLY, default=False): cv.boolean,
            cv.Optional(CONF_LOG_RAW, default=False): cv.boolean,
            cv.Optional(CONF_RECONNECT_INTERVAL, default="10s"): cv.positive_time_period_milliseconds,
            cv.Optional(CONF_STALE_TIMEOUT, default="15s"): cv.positive_time_period_milliseconds,
            cv.Optional(CONF_BLUETOOTH): _ble_schema,
        }
    ).extend(cv.COMPONENT_SCHEMA),
    cv.only_on(["esp32", "host"]),
)

GRAVITY980_CHILD_SCHEMA = cv.Schema({cv.GenerateID(CONF_GRAVITY980_ID): cv.use_id(Gravity980Component)})


async def to_code(config):
    var = cg.new_Pvariable(config[CONF_ID])
    await cg.register_component(var, config)
    cg.add(var.set_host(config[CONF_HOST]))
    cg.add(var.set_port(config[CONF_PORT]))
    cg.add(var.set_fahrenheit(config[CONF_TEMPERATURE_UNIT] == "F"))
    cg.add(var.set_read_only(config[CONF_READ_ONLY]))
    cg.add(var.set_log_raw(config[CONF_LOG_RAW]))
    cg.add(var.set_reconnect_interval(config[CONF_RECONNECT_INTERVAL]))
    cg.add(var.set_stale_timeout(config[CONF_STALE_TIMEOUT]))
    if ble := config.get(CONF_BLUETOOTH):
        from esphome.components import esp32_ble_tracker

        cg.add_define("USE_GRAVITY980_BLE")
        cg.add_define("USE_ESP32_BLE_UUID")
        b = cg.new_Pvariable(ble[CONF_ID])
        await cg.register_component(b, ble)
        await esp32_ble_tracker.register_client(b, ble)
        cg.add(b.set_parent(var))
        cg.add(b.set_name_prefix(ble[CONF_NAME_PREFIX]))
        cg.add(b.set_auto_connect(True))
        if CONF_MAC_ADDRESS in ble:
            cg.add(b.set_fixed_address(ble[CONF_MAC_ADDRESS].as_hex))
        cg.add(var.set_ble(b))
        cg.add(var.set_ble_writes(ble[CONF_WRITES]))
