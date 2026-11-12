"""Tests for configuration loader."""

from pathlib import Path
from agent.config import AppConfig, PreferencesConfig, load_config


def test_default_config_fallback(tmp_path: Path) -> None:
    """Ensure non-existent config path falls back safely to default AppConfig."""
    non_existent = tmp_path / "non_existent.yaml"
    cfg = load_config(str(non_existent))
    assert isinstance(cfg, AppConfig)
    assert isinstance(cfg.preferences, PreferencesConfig)
    assert any("Backend" in r or "Intern" in r for r in cfg.preferences.target_roles)


def test_load_config_valid(tmp_path: Path) -> None:
    """Verify loading and parsing custom config.yaml."""
    yaml_content = """
preferences:
  target_roles: ["Senior Python Developer"]
  experience_level: "5 years"
  locations: ["Remote"]
  core_skills: ["Python", "AsyncIO", "Docker"]
  github_username: "testuser"
llm:
  model: "claude-3-5-haiku-20241022"
  temperature: 0.5
  max_retries: 2
"""
    test_yaml = tmp_path / "test_config.yaml"
    test_yaml.write_text(yaml_content, encoding="utf-8")

    cfg = load_config(str(test_yaml))
    assert cfg.preferences.target_roles == ["Senior Python Developer"]
    assert cfg.preferences.github_username == "testuser"
    assert cfg.llm.model == "claude-3-5-haiku-20241022"
    assert cfg.llm.temperature == 0.5
    assert cfg.llm.max_retries == 2
