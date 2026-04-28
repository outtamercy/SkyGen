#  theme_manager.py – AttributeError & IndexError fixes (only requested changes)

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Optional, Any

from PyQt6.QtWidgets import QApplication, QWidget  # type: ignore
from PyQt6.QtGui import QColor  # type: ignore
from PyQt6.QtCore import QDir  # type: ignore
from ..utils.logger import LoggingMixin
from ..src.config import ConfigManager


class ThemeManager(LoggingMixin):
    """
    Manages theme-related functionality for the SkyGen UI.
    Detects MO2's QSS themes and applies them to the application.
    """

    def __init__(
        self,
        config_manager: ConfigManager,
        mo2_base_path: str,
        plugin_path: str,
        target_widget: QWidget,
        organizer_wrapper=None,
    ) -> None:
        super().__init__()
        self.config_manager = config_manager
        self.mo2_base_path = Path(mo2_base_path)
        self.plugin_path = Path(plugin_path)
        self.mo2_stylesheets_path = self.mo2_base_path / "stylesheets"
        self.plugin_themes_path = self.plugin_path / "themes"
        self.target_widget = target_widget
        self.organizer_wrapper = organizer_wrapper
        self.log_info(
            f"ThemeManager initialised. MO2 sheets: {self.mo2_stylesheets_path} "
            f"| plugin themes: {self.plugin_themes_path}"
        )

    # ------------------------------------------------------------------
    #  detect
    # ------------------------------------------------------------------
    def get_available_themes(self) -> List[str]:
        themes = []

        # 1. MO2 global sheets
        if self.mo2_stylesheets_path.is_dir():
            for item in self.mo2_stylesheets_path.iterdir():
                if item.is_file() and item.suffix.lower() == ".qss":
                    themes.append(item.stem)
                elif item.is_dir():
                    bundled = item / f"{item.name}.qss"
                    if bundled.is_file():
                        themes.append(item.name)

        # 2. plugin private themes
        if self.plugin_themes_path.is_dir():
            for qss in self.plugin_themes_path.glob("*.qss"):
                if qss.stem not in themes:
                    themes.append(qss.stem)

        return sorted(list(set(themes)))

    # ------------------------------------------------------------------
    #  load content  (plugin-first, MO2-second)
    # ------------------------------------------------------------------
    def _get_qss_content(self, theme_name: str) -> Optional[str]:
        if not theme_name:
            return None

        # 1️⃣  PLUGIN theme – we load ourselves (images relative to plugin/themes/)
        plugin_qss = self.plugin_themes_path / f"{theme_name}.qss"
        if plugin_qss.is_file():
            try:
                old = QDir.current()
                QDir.setCurrent(str(plugin_qss.parent))
                content = plugin_qss.read_text(encoding="utf-8")
                QDir.setCurrent(str(old))
                self.log_debug(f"Loaded plugin theme: {plugin_qss}")
                return content
            except Exception as e:
                self.log_error(f"Failed to read plugin theme {plugin_qss}: {e}")
                return None

        # 2️⃣  MO2 theme – ask MO2 to load it so images resolve relative to MO2/stylesheets/
        mo2_qss = self.mo2_stylesheets_path / f"{theme_name}.qss"
        if not mo2_qss.is_file():
            mo2_qss = self.mo2_stylesheets_path / theme_name / f"{theme_name}.qss"

        if mo2_qss.is_file():
            if self.organizer_wrapper:
                try:
                    qss_text = mo2_qss.read_text(encoding="utf-8")
                    base = mo2_qss.parent
                    qss_text = qss_text.replace('#centralWidget', 'QDialog, #centralWidget')
                    def _rewrite_urls(match):
                        path = match.group(1)
                        if path.startswith(('http://', 'https://', '/', 'data:', 'qrc:')):
                            return match.group(0)
                        abs_path = (base / path).resolve().as_posix()
                        return f"url('{abs_path}')"

                    qss_text = re.sub(r"""(?i)url\(['"]?([^'")]+)['"]?\)""", _rewrite_urls, qss_text)
                    match = re.search(r'url\([^)]+\)', qss_text)
                    if match:
                        self.log_debug(f"first rewritten url: {match.group()[:60]}…")
                    self.target_widget.setStyleSheet(qss_text)  # 🔥 FIXED – use target_widget
                    self.log_debug(f"Applied MO2 theme via MO2: {mo2_qss}")
                    return ""
                except Exception as e:
                    self.log_error(f"MO2 theme load failed: {e}", exc_info=True)
                    return None
            else:
                try:
                    qss_text = mo2_qss.read_text(encoding="utf-8")
                    base = mo2_qss.parent

                    def _rewrite_urls(match):
                        path = match.group(1)
                        if path.startswith(('http://', 'https://', '/', 'data:', 'qrc:')):
                            return match.group(0)
                        abs_path = (base / path).resolve().as_posix()
                        return f"url('{abs_path}')"

                    qss_text = re.sub(r"""(?i)url\(['"]?([^'")]+)['"]?\)""", _rewrite_urls, qss_text)
                    match = re.search(r'url\([^)]+\)', qss_text)
                    if match:
                        self.log_debug(f"first rewritten url: {match.group()[:60]}…")
                    return qss_text
                except Exception as e:
                    self.log_error(f"Failed to read MO2 theme {mo2_qss}: {e}", exc_info=True)
                    return None

        self.log_warning(f"No QSS found for theme '{theme_name}'")
        return None

    # ------------------------------------------------------------------
    #  apply & persist
    # ------------------------------------------------------------------
    def apply_theme(self, theme_name: str) -> bool:
        qss_content = self._get_qss_content(theme_name)
        if qss_content is None:
            return False

        if qss_content:
            try:
                self.target_widget.setStyleSheet(qss_content)
            except Exception as e:
                self.log_error(f"setStyleSheet failed: {e}", exc_info=True)
                return False

        app_config = self.config_manager.get_application_config()
        app_config.selected_theme = theme_name
        self.log_info(f"Theme '{theme_name}' applied and saved.")
        return True

    # ------------------------------------------------------------------
    #  helper
    # ------------------------------------------------------------------
    def get_current_theme_name(self) -> str:
        return self.config_manager.get_application_config().selected_theme