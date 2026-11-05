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
