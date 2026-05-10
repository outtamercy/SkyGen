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
                # only SkyGenBlue gets the frame swapper
                if "skygenblue" in theme_name.lower():
                    content = self._swap_skygenblue_bg(content)
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
                    self.log_debug(f"Loaded MO2 theme: {mo2_qss}")
                    return qss_text
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

    def _swap_skygenblue_bg(self, qss_text: str) -> str:
        """SkyGenBlue only — cycles Frame-X.jpg and forces stretch-to-fit."""
        # find the image line (background-image or border-image)
        m = re.search(r'(background-image|border-image):\s*url\([^)]+\)[^;]*;', qss_text)
        if not m:
            return qss_text

        # sniff folder from the matched line
        path_m = re.search(r'url\(([^)]+)\)', m.group(0))
        if not path_m:
            return qss_text

        raw = path_m.group(1).strip("'\"").replace("\\", "/")
        folder = raw.split("/")[0] if "/" in raw else "SkyGenBlue"
        img_dir = self.plugin_themes_path / folder

        if not img_dir.is_dir():
            return qss_text

        # grab Frame-1.jpg, Frame-2.jpg, etc.
        exts = ('.png', '.jpg', '.jpeg', '.bmp', '.gif')
        frames = sorted([
            p for p in img_dir.iterdir()
            if p.name.startswith("Frame-") and p.suffix.lower() in exts and p.is_file()
        ])
        if len(frames) < 2:
            return qss_text

        # read counter from config
        ac = self.config_manager.get_application_config()
        idx = ac.theme_bg_index

        # pick next frame
        selected = frames[idx % len(frames)]
        rel = selected.relative_to(self.plugin_themes_path).as_posix()

        # replace with border-image so Qt stretches to fit instead of 1:1 cropping
        new_line = f"border-image: url('{rel}') 0 0 0 0 stretch stretch;"
        new_qss = qss_text.replace(m.group(0), new_line, 1)

        # bump and save
        ac.theme_bg_index = (idx + 1) % len(frames)
        self.config_manager.save_application_config(ac)
        self.log_info(f"SkyGenBlue backdrop: {selected.name}")

        return new_qss

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

    @property
    def accent_color(self) -> str:
        """Gold accent — centralized so QSS and widgets share one source of truth."""
        return "#d4af37"