import json

from station.settings import StationSettings


def test_out_of_range_values_are_clamped(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"drive_sensitivity": -50, "turn_deadzone": 99, "robot_host": "  "}))
    settings = StationSettings.load(path)
    assert settings.drive_sensitivity == 0.0
    assert settings.turn_deadzone == 50.0
    assert settings.robot_host == "orangepi.local"


def test_unreadable_file_gives_defaults(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{not json")
    assert StationSettings.load(path) == StationSettings()
