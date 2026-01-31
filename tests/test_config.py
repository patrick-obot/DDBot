"""Tests for ddbot.config."""

import os

import pytest

from ddbot.config import Config


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Ensure environment is clean before each test."""
    env_vars = [
        "DD_SERVICES", "DD_THRESHOLD", "DD_POLL_INTERVAL",
        "DD_ALERT_COOLDOWN", "GREENAPI_INSTANCE_ID", "GREENAPI_API_TOKEN",
        "WHATSAPP_RECIPIENTS", "LOG_LEVEL",
    ]
    for var in env_vars:
        monkeypatch.delenv(var, raising=False)


class TestConfigDefaults:
    def test_default_services(self):
        config = Config()
        assert config.services == ["mtn"]

    def test_default_threshold(self):
        config = Config()
        assert config.threshold == 10

    def test_default_poll_interval(self):
        config = Config()
        assert config.poll_interval == 300

    def test_default_cooldown(self):
        config = Config()
        assert config.alert_cooldown == 1800


class TestConfigFromEnv:
    def test_loads_services(self, monkeypatch):
        monkeypatch.setenv("DD_SERVICES", "mtn,vodacom,telkom")
        monkeypatch.setenv("GREENAPI_INSTANCE_ID", "test")
        monkeypatch.setenv("GREENAPI_API_TOKEN", "test")
        monkeypatch.setenv("WHATSAPP_RECIPIENTS", "27000000000")
        config = Config.from_env(env_path="/dev/null")
        assert config.services == ["mtn", "vodacom", "telkom"]

    def test_strips_whitespace(self, monkeypatch):
        monkeypatch.setenv("DD_SERVICES", " mtn , vodacom ")
        config = Config.from_env(env_path="/dev/null")
        assert config.services == ["mtn", "vodacom"]

    def test_loads_threshold(self, monkeypatch):
        monkeypatch.setenv("DD_THRESHOLD", "25")
        config = Config.from_env(env_path="/dev/null")
        assert config.threshold == 25

    def test_loads_recipients(self, monkeypatch):
        monkeypatch.setenv("WHATSAPP_RECIPIENTS", "27111,27222")
        config = Config.from_env(env_path="/dev/null")
        assert config.whatsapp_recipients == ["27111", "27222"]


class TestConfigValidation:
    def test_valid_config_passes(self):
        config = Config(
            services=["mtn"],
            threshold=10,
            poll_interval=60,
            alert_cooldown=300,
            greenapi_instance_id="123",
            greenapi_api_token="abc",
            whatsapp_recipients=["27000000000"],
        )
        assert config.validate() == []

    def test_empty_services_fails(self):
        config = Config(
            services=[],
            greenapi_instance_id="123",
            greenapi_api_token="abc",
            whatsapp_recipients=["27000000000"],
        )
        errors = config.validate()
        assert any("DD_SERVICES" in e for e in errors)

    def test_zero_threshold_fails(self):
        config = Config(
            threshold=0,
            greenapi_instance_id="123",
            greenapi_api_token="abc",
            whatsapp_recipients=["27000000000"],
        )
        errors = config.validate()
        assert any("DD_THRESHOLD" in e for e in errors)

    def test_missing_api_creds_fails(self):
        config = Config(
            greenapi_instance_id="",
            greenapi_api_token="",
            whatsapp_recipients=["27000000000"],
        )
        errors = config.validate()
        assert any("GREENAPI" in e for e in errors)

    def test_no_recipients_fails(self):
        config = Config(
            greenapi_instance_id="123",
            greenapi_api_token="abc",
            whatsapp_recipients=[],
        )
        errors = config.validate()
        assert any("WHATSAPP_RECIPIENTS" in e for e in errors)

    def test_invalid_log_level_fails(self):
        config = Config(
            greenapi_instance_id="123",
            greenapi_api_token="abc",
            whatsapp_recipients=["27000000000"],
            log_level="VERBOSE",
        )
        errors = config.validate()
        assert any("LOG_LEVEL" in e for e in errors)

    def test_low_poll_interval_fails(self):
        config = Config(
            poll_interval=5,
            greenapi_instance_id="123",
            greenapi_api_token="abc",
            whatsapp_recipients=["27000000000"],
        )
        errors = config.validate()
        assert any("DD_POLL_INTERVAL" in e for e in errors)
