import pytest

from common.config import ConfigError, default_config, merge_config, validate_config


def test_default_config_is_valid():
    assert validate_config(default_config()) == []


def test_default_mapping_uses_every_motor_and_encoder_once():
    modules = default_config()["modules"].values()
    motors = [m[slot] for m in modules for slot in ("motor_a", "motor_b")]
    assert sorted(motors) == [f"M{n}" for n in range(1, 9)]
    assert sorted(m["encoder"] for m in modules) == ["E1", "E2", "E3", "E4"]


def test_each_hbridge_drives_two_different_modules():
    # From the BOM: an H-bridge's two motors are on neighboring sides of distinct modules.
    config = default_config()
    module_of = {m[slot]: name for name, m in config["modules"].items() for slot in ("motor_a", "motor_b")}
    for hb in ("HB1", "HB2", "HB3", "HB4"):
        motors = [motor for motor, entry in config["motors"].items() if entry["hbridge"] == hb]
        assert len({module_of[motor] for motor in motors}) == 2


def test_duplicate_motor_is_rejected():
    config = merge_config(default_config(), {"modules": {"FL": {"motor_a": "M4"}}})
    assert any("M4" in error for error in validate_config(config))


def test_shared_hbridge_channel_is_rejected():
    config = merge_config(default_config(), {"motors": {"M1": {"hbridge": "HB1", "channel": "B"}}})
    assert any("HB1 channel B" in error for error in validate_config(config))


def test_tuning_out_of_range_is_rejected():
    config = merge_config(default_config(), {"tuning": {"steer_kp": 99.0}})
    assert any("Steer kP" in error for error in validate_config(config))


def test_wheel_centers_are_110_mm_from_the_robot_center():
    assert default_config()["geometry"]["module_offset_m"] == 0.11


def test_top_speed_may_be_set_up_to_10_mps():
    assert validate_config(merge_config(default_config(), {"tuning": {"max_speed_mps": 10.0}})) == []
    too_fast = merge_config(default_config(), {"tuning": {"max_speed_mps": 10.5}})
    assert any("Max wheel speed" in error for error in validate_config(too_fast))


def test_a_config_saved_before_the_turn_rate_limit_existed_still_loads(tmp_path):
    import json

    from robot.config_store import ConfigStore

    old = default_config()
    del old["tuning"]["max_turn_dps"]
    path = tmp_path / "robot_config.json"
    path.write_text(json.dumps(old), encoding="utf-8")
    assert ConfigStore(path).load()["tuning"]["max_turn_dps"] == 360.0


def test_hardware_wiring_cannot_be_changed_remotely():
    with pytest.raises(ConfigError):
        merge_config(default_config(), {"hbridges": {}})


def test_merge_keeps_untouched_keys():
    base = default_config()
    base["modules"]["FL"]["offset"] = 1234
    merged = merge_config(base, {"modules": {"FL": {"invert_a": True}}})
    assert merged["modules"]["FL"]["offset"] == 1234
    assert merged["modules"]["FL"]["invert_a"] is True
    assert base["modules"]["FL"]["invert_a"] is False  # base not modified


@pytest.mark.parametrize("update", [
    {"modules": {"FL": {"offset": 5}}},          # only Swerve Set Zero writes offsets
    {"tuning": {"not_a_setting": 1.0}},
    {"encoders": {"E1": {"sda_pin": 9}}},
    {"modules": "FL"},
])
def test_remote_update_rejects_keys_it_may_not_set(update):
    with pytest.raises(ConfigError):
        merge_config(default_config(), update)


def test_imu_bus_and_direction_are_editable_but_not_its_address():
    merged = merge_config(default_config(), {"imu": {"bus": "/dev/i2c-5", "invert_yaw": True}})
    assert validate_config(merged) == []
    with pytest.raises(ConfigError):
        merge_config(default_config(), {"imu": {"address": 0x69}})


def test_a_motor_can_have_its_own_power_bands():
    from common.config import motor_band
    config = default_config()
    config["tuning"].update(forward_start=0.6, forward_max=0.78, reverse_start=0.15, reverse_max=0.4)
    config["motor_bands"] = {"M4": {"reverse": [0.1, 0.3]}}
    assert validate_config(config) == []
    assert motor_band(config, "M4", "reverse") == (0.1, 0.3)       # its own
    assert motor_band(config, "M4", "forward") == (0.6, 0.78)      # not set: the shared one
    assert motor_band(config, "M1", "reverse") == (0.15, 0.4)


def test_bad_motor_bands_are_rejected():
    for bands in ({"M9": {"forward": [0.1, 0.5]}}, {"M1": {"sideways": [0.1, 0.5]}},
                  {"M1": {"forward": [0.6, 0.5]}}, {"M1": {"forward": [0.1]}}, {"M1": {"forward": [0.1, 1.5]}}):
        config = default_config()
        config["motor_bands"] = bands
        assert any("motor_bands" in e for e in validate_config(config)), bands
