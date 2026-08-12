"""Tests for the Typer CLI interface.

This module covers flag override behavior and config display without
hitting live X or Raindrop APIs.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from x2raindrop_cli.cli import app, configure_logging
from x2raindrop_cli.config import create_default_config, load_settings
from x2raindrop_cli.models import SyncResult

runner = CliRunner()


def _write_config(path: Path) -> Path:
    """Create a config file with Raindrop token, collection, and override flags set.

    Args:
        path: Destination config path.

    Returns:
        Path to the written config file.
    """
    create_default_config(path)
    content = path.read_text()
    content = content.replace('token = "YOUR_RAINDROP_TOKEN"', 'token = "test-raindrop-token"')
    content = content.replace(
        'collection_title = ""\ntags = [\n    "x-bookmark"',
        'collection_id = 12345\ncollection_title = ""\ntags = [\n    "x-bookmark"',
        1,
    )
    content = content.replace("remove_from_x = false", "remove_from_x = true", 1)
    content = content.replace("dry_run = false", "dry_run = true", 1)
    path.write_text(content)
    return path


class TestConfigureLogging:
    """Tests for logging configuration."""

    def test_configure_logging_accepts_level(self) -> None:
        """Test configure_logging runs for a valid level name."""
        configure_logging("DEBUG")


class TestConfigCommands:
    """Tests for config subcommands."""

    def test_config_path(self) -> None:
        """Test config path prints the default location."""
        result = runner.invoke(app, ["config", "path"])

        assert result.exit_code == 0
        assert "config.toml" in result.stdout

    def test_config_show_without_raindrop_token(self, temp_dir: Path) -> None:
        """Test config show works when Raindrop token is unset."""
        config_path = temp_dir / "config.toml"
        create_default_config(config_path)
        content = config_path.read_text().replace(
            'token = "YOUR_RAINDROP_TOKEN"',
            'token = ""',
        )
        config_path.write_text(content)

        result = runner.invoke(app, ["config", "show", "--config", str(config_path)])

        assert result.exit_code == 0
        assert "Current Configuration" in result.stdout
        assert "Log Level" in result.stdout


class TestSyncFlagOverrides:
    """Tests for sync CLI flag override behavior."""

    def test_no_remove_from_x_clears_config_true(self, temp_dir: Path) -> None:
        """Test --no-remove-from-x overrides config remove_from_x=true."""
        config_path = _write_config(temp_dir / "config.toml")
        captured: dict[str, Any] = {}

        def fake_sync(self: Any, progress_callback: Any = None) -> SyncResult:
            del progress_callback
            captured["remove_from_x"] = self.settings.bookmarks.remove_from_x
            captured["dry_run"] = self.settings.dry_run
            return SyncResult()

        with (
            patch("x2raindrop_cli.cli._get_x_token", return_value=MagicMock()),
            patch("x2raindrop_cli.cli.XClient") as mock_x_cls,
            patch("x2raindrop_cli.cli.RaindropClient") as mock_rd_cls,
            patch("x2raindrop_cli.cli.SyncService.sync", fake_sync),
        ):
            mock_x = MagicMock()
            mock_x.request_count = 0
            mock_x_cls.return_value = mock_x
            mock_rd_cls.return_value = MagicMock()

            result = runner.invoke(
                app,
                [
                    "sync",
                    "--config",
                    str(config_path),
                    "--no-remove-from-x",
                    "--no-dry-run",
                ],
            )

        assert result.exit_code == 0, result.stdout
        assert captured["remove_from_x"] is False
        assert captured["dry_run"] is False

    def test_remove_from_x_sets_true(self, temp_dir: Path) -> None:
        """Test --remove-from-x sets remove_from_x even when config is false."""
        config_path = temp_dir / "config.toml"
        create_default_config(config_path)
        text = config_path.read_text()
        text = text.replace('token = "YOUR_RAINDROP_TOKEN"', 'token = "test-raindrop-token"')
        text = text.replace(
            'collection_title = ""\ntags = [\n    "x-bookmark"',
            'collection_id = 12345\ncollection_title = ""\ntags = [\n    "x-bookmark"',
            1,
        )
        config_path.write_text(text)
        captured: dict[str, Any] = {}

        def fake_sync(self: Any, progress_callback: Any = None) -> SyncResult:
            del progress_callback
            captured["remove_from_x"] = self.settings.bookmarks.remove_from_x
            return SyncResult()

        with (
            patch("x2raindrop_cli.cli._get_x_token", return_value=MagicMock()),
            patch("x2raindrop_cli.cli.XClient") as mock_x_cls,
            patch("x2raindrop_cli.cli.RaindropClient") as mock_rd_cls,
            patch("x2raindrop_cli.cli.SyncService.sync", fake_sync),
        ):
            mock_x = MagicMock()
            mock_x.request_count = 0
            mock_x_cls.return_value = mock_x
            mock_rd_cls.return_value = MagicMock()

            result = runner.invoke(
                app,
                ["sync", "--config", str(config_path), "--remove-from-x"],
            )

        assert result.exit_code == 0, result.stdout
        assert captured["remove_from_x"] is True

    def test_sync_requires_raindrop_token(self, temp_dir: Path) -> None:
        """Test sync fails when Raindrop token is missing."""
        config_path = temp_dir / "config.toml"
        create_default_config(config_path)
        text = config_path.read_text()
        text = text.replace('token = "YOUR_RAINDROP_TOKEN"', 'token = ""')
        text = text.replace(
            'collection_title = ""\ntags = [\n    "x-bookmark"',
            'collection_id = 12345\ncollection_title = ""\ntags = [\n    "x-bookmark"',
            1,
        )
        config_path.write_text(text)

        with patch("x2raindrop_cli.cli._get_x_token", return_value=MagicMock()):
            result = runner.invoke(app, ["sync", "--config", str(config_path)])

        assert result.exit_code == 1
        assert "Raindrop token" in result.stdout


class TestLoadSettingsOptionalRaindrop:
    """Tests for optional Raindrop token in settings loading."""

    def test_load_settings_without_raindrop_token(self, temp_dir: Path) -> None:
        """Test settings load when raindrop.token is empty."""
        config_path = temp_dir / "config.toml"
        create_default_config(config_path)
        config_path.write_text(
            config_path.read_text().replace('token = "YOUR_RAINDROP_TOKEN"', 'token = ""')
        )

        settings = load_settings(config_path)

        assert settings.raindrop.token in (None, "")
