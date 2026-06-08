import threading
import time

import pytest
import yaml

from orwell_shared.config_watcher import ConfigWatcher


@pytest.fixture
def config_file(tmp_path):
    path = tmp_path / "orwell.yaml"
    path.write_text(yaml.dump({"conveyor": {"periodic_upload_interval_s": 600}}))
    return path


def test_watcher_calls_callback_on_file_change(config_file):
    calls = []

    def on_change(cfg):
        calls.append(cfg.conveyor.periodic_upload_interval_s)

    watcher = ConfigWatcher(config_file, on_change, poll_interval_s=0.05)
    watcher.start()
    time.sleep(0.1)

    config_file.write_text(yaml.dump({"conveyor": {"periodic_upload_interval_s": 120}}))
    time.sleep(0.15)
    watcher.stop()

    assert 120 in calls


def test_watcher_does_not_call_when_unchanged(config_file):
    calls = []

    def on_change(cfg):
        calls.append(cfg)

    watcher = ConfigWatcher(config_file, on_change, poll_interval_s=0.05)
    watcher.start()
    time.sleep(0.2)
    watcher.stop()

    assert calls == []
