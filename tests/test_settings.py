import json

from station.settings import StationSettings


def test_out_of_range_values_are_clamped(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"drive_sensitivity": -50, "turn_deadzone": 99, "robot_host": "  "}))
    settings = StationSettings.load(path)
    assert settings.drive_sensitivity == 0.0
    assert settings.turn_deadzone == 50.0
    assert settings.robot_host == "orangepi4pro.local"


def test_unreadable_file_gives_defaults(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{not json")
    assert StationSettings.load(path) == StationSettings()


def test_save_then_load_round_trips(tmp_path):
    path = tmp_path / "nested" / "settings.json"     # the AppData folder may not exist yet
    StationSettings(robot_host="10.0.0.5", turn_sensitivity=42.5).save(path)
    loaded = StationSettings.load(path)
    assert (loaded.robot_host, loaded.turn_sensitivity) == ("10.0.0.5", 42.5)
    assert not path.with_suffix(".json.tmp").exists()


def test_keyboard_and_connection_are_saved_and_validated(tmp_path):
    path = tmp_path / "settings.json"
    StationSettings(keyboard_control=True, connection="simulator").save(path)
    loaded = StationSettings.load(path)
    assert (loaded.keyboard_control, loaded.connection) == (True, "simulator")

    path.write_text(json.dumps({"keyboard_control": "yes", "connection": "moon"}))
    loaded = StationSettings.load(path)
    assert (loaded.keyboard_control, loaded.connection) == (False, "robot")
