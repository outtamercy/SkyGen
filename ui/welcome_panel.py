from PyQt6.QtWidgets import (  # type: ignore
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QCheckBox,
    QPushButton, QScrollArea, QFrame, QStackedWidget, QSizePolicy
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer  # type: ignore
from PyQt6.QtGui import QMovie, QPalette  # type: ignore
from pathlib import Path
from ..core.constants import DEBUG_FORCE_WELCOME_GIF


class WelcomePanel(QWidget):
    continue_clicked = pyqtSignal()

    def __init__(self, plugin_path: Path, config_manager=None, parent=None):
        super().__init__(parent)
        self.plugin_root = plugin_path
        self._config = config_manager
        self._gate_1_open = False
        self._gate_2_open = False
        self._gif_label = None
        self._gif_movie = None
        self._gif_paths = [
            self.plugin_root / "icons" / "SkyGenforge-optimize.gif",
            self.plugin_root / "icons" / "Septim-optimize.gif",
            self.plugin_root / "icons" / "video3-optimize.gif",
        ]
        self._gif_index = 0
        self._setup_ui()

    def _setup_ui(self):
        # root layout — Qt handles sizing, we stop fighting it
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        
        self._content = QWidget()
        root_layout.addWidget(self._content, stretch=1)
        
        content_layout = QVBoxLayout(self._content)
        content_layout.setContentsMargins(20, 15, 20, 15)
        content_layout.setSpacing(10)

        # header above the carousel
        self._header_label = QLabel("")
        self._header_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        win = self.window()
        tm = getattr(win, 'theme_manager', None)
        accent = tm.accent_color if tm else "#d4af37"
        self._header_label.setStyleSheet(
            f"font-size: 26px; font-weight: bold; color: {accent}; margin-bottom: 8px;"
        )
        content_layout.addWidget(self._header_label)

        # ---- carousel: one thing visible at a time ----
        self._carousel = QStackedWidget()
        self._carousel.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )

        # page 0: gif — give it a layout so it can't collapse to 1px
        self._video_page = QWidget()
        self._video_page.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self._video_page.setMinimumHeight(360)
        self._video_page.setStyleSheet("background-color: #000000;")
        video_layout = QVBoxLayout(self._video_page)
        video_layout.setContentsMargins(0, 0, 0, 0)
        video_layout.setSpacing(0)
        self._carousel.addWidget(self._video_page)

        # page 1: text
        self._text_page = QWidget()
        self._text_page.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        text_layout = QVBoxLayout(self._text_page)
        text_layout.setContentsMargins(0, 0, 0, 0)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        self.scroll.viewport().setAutoFillBackground(False)

        scroll_content = QWidget()
        scroll_content.setMinimumWidth(600)
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setContentsMargins(15, 15, 15, 15)
        scroll_layout.setSpacing(12)

        # body text — one file only
        self._body_label = QLabel("")
        self._body_label.setWordWrap(True)
        self._body_label.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._body_label.setOpenExternalLinks(True)
        self._body_label.setTextFormat(Qt.TextFormat.RichText)
        scroll_layout.addWidget(self._body_label, stretch=1)

        # checkbox stays at bottom of scrollable area
        self.ack_cb = QCheckBox("I have read the readme and understand")
        self.ack_cb.stateChanged.connect(self._update_continue_state)
        scroll_layout.addWidget(self.ack_cb)

        self.scroll.setWidget(scroll_content)
        text_layout.addWidget(self.scroll)
        self._carousel.addWidget(self._text_page)
        self._carousel.setCurrentIndex(1)

        content_layout.addWidget(self._carousel, stretch=1)

        # gate indicators
        status_layout = QHBoxLayout()
        self.gate1_label = QLabel("📜 Scroll to bottom")
        self.gate2_label = QLabel("⚙️ System ready")
        for lbl in (self.gate1_label, self.gate2_label):
            lbl.setStyleSheet("color: #666666; font-size: 11px;")
            status_layout.addWidget(lbl)
        status_layout.addStretch()
        content_layout.addLayout(status_layout)

        # continue button
        self.continue_btn = QPushButton("Continue to Workspace")
        self.continue_btn.setEnabled(False)
        self.continue_btn.setMinimumHeight(40)
        self.continue_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        gold = accent

        self.continue_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: #1a1a1a;
                color: #666666;
                border: 2px solid #444444;
                border-radius: 8px;
                font-size: 16px;
                font-weight: bold;
                padding: 0 20px;
            }}
            QPushButton:enabled {{
                background-color: #2d5016;
                color: {gold};
                border-color: {gold};
            }}
            QPushButton:enabled:hover {{
                background-color: #3d6820;
            }}
        """)
        self.continue_btn.clicked.connect(self.continue_clicked.emit)
        content_layout.addWidget(self.continue_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        # scroll detection
        self.scroll.verticalScrollBar().valueChanged.connect(self._check_scroll)
        QTimer.singleShot(200, self._check_scroll)

    def showEvent(self, event):
        super().showEvent(event)
        # hide workspace buttons while welcome is up
        main_win = self.window()
        if main_win:
            for attr in ('btn_generate_sp', 'btn_generate_bos', 'btn_stop_gen'):
                if hasattr(main_win, attr):
                    getattr(main_win, attr).hide()
        # check scroll after layout settles
        QTimer.singleShot(100, self._check_scroll)

    def _get_run_count(self) -> int:
        """Pull view count from existing config — no standalone counter file."""
        if not self._config:
            return 0
        try:
            ac = self._config.get_application_config()
            return getattr(ac, 'welcome_view_count', 0)
        except Exception:
            return 0

    def _increment_run_count(self) -> None:
        """Bump the count inside skygen_config.ini where it looks like normal settings."""
        if not self._config:
            return
        try:
            ac = self._config.get_application_config()
            ac.welcome_view_count = getattr(ac, 'welcome_view_count', 0) + 1
            self._config.save_application_config(ac)
        except Exception:
            pass

    def _purge_media(self) -> None:
        """Nuke GIF from RAM. No hiding — destruction."""
        if self._gif_movie:
            self._gif_movie.stop()
            self._gif_movie.deleteLater()
            self._gif_movie = None
        if self._gif_label and self._video_page.layout():
            self._video_page.layout().removeWidget(self._gif_label)
            self._gif_label.deleteLater()
            self._gif_label = None

    def _load_gif(self, gif_path: Path) -> bool:
        """Load an animated GIF without using Qt Multimedia codecs."""
        if not gif_path.exists():
            return False

        label = QLabel(self._video_page)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        label.setMinimumSize(1, 1)
        label.setScaledContents(True)
        label.setStyleSheet("background-color: #000000;")

        movie = QMovie(str(gif_path))
        if not movie.isValid():
            label.deleteLater()
            print(f"GIF invalid: {gif_path}")
            return False

        movie.setCacheMode(QMovie.CacheMode.CacheAll)
        label.setMovie(movie)
        self._video_page.layout().addWidget(label, stretch=1)
        self._gif_label = label
        self._gif_movie = movie

        self._carousel.setCurrentIndex(0)
        label.show()
        movie.start()
        print(f"starting GIF: {gif_path}")
        return True

    def _setup_text_content(self, situation: str, forced_file: str | None = None) -> None:
        """Load text file into body label. Assumes carousel is already on text page."""
        header_map = {
            "fresh": "Welcome to SkyGen®",
            "bat_complete": "SkyGen® Updated",
            "ml_change": "Load Order Changed",
            "logic_change": "System Logic Changed",
        }
        self._header_label.setText(header_map.get(situation, "SkyGen®"))

        welcome_dir = self.plugin_root / "welcome"

        if forced_file:
            filename = forced_file
        else:
            mapping = {
                "fresh": "first_launch.txt",
                "bat_complete": "changelog.txt",
                "ml_change": "changelog.txt",
                "logic_change": "changelog.txt",
            }
            filename = mapping.get(situation, "readme.txt")

        target = welcome_dir / filename

        if not target.exists():
            target = welcome_dir / "readme.txt"
        if not target.exists():
            target = welcome_dir / "first_launch.txt"

        try:
            text = target.read_text(encoding='utf-8')
        except OSError:
            text = "<p style='color: #ff6b6b;'>Failed to load welcome text.</p>"

        text_color = self.palette().color(QPalette.ColorRole.Text).name()
        html = f"""<div style='font-family: "EagleLake", "Almendra", "Segoe UI", sans-serif;
                    font-size: 20px; line-height: 1.6; color: {text_color};'>
                {text.replace(chr(10), '<br>')}
                </div>"""
        self._body_label.setText(html)

    def load_asset(self, situation: str) -> None:
        """Master Loader: ONE decision, ONE load, no flip-flopping."""
        # clear the stage — always nuke old media first
        self._purge_media()

        # reset gates for fresh evaluation
        self._gate_1_open = False
        self.gate1_label.setStyleSheet("color: #666666; font-size: 11px;")
        self.gate1_label.setText("📜 Scroll to bottom")

        run_count = self._get_run_count()

        # GIF mode: debug override always wins, otherwise starts after 3 text runs
        if DEBUG_FORCE_WELCOME_GIF or run_count >= 3:
            self._gif_index = (self._gif_index + 1) % len(self._gif_paths)
            gif_path = self._gif_paths[self._gif_index]

            if gif_path.exists():
                try:
                    if self._load_gif(gif_path):
                        self._gate_1_open = True
                        self.gate1_label.setStyleSheet("color: #4caf50; font-size: 11px;")
                        self.gate1_label.setText("✓ Animation active")
                        self._increment_run_count()
                        self._update_continue_state()
                        return
                except Exception as e:
                    print(f"GIF LOAD FAILED: {e}")
            # GIF failed, fall through to text as last resort

        # Text mode: first 3 runs rotate through the educational files
        self._carousel.setCurrentIndex(1)
        self._body_label.setVisible(True)

        # light dusting for readability, nebula breathes through
        scroll_widget = self.scroll.widget()
        if scroll_widget:
            scroll_widget.setStyleSheet(
                "background-color: rgba(10, 10, 10, 0.15); border-radius: 8px;"
            )

        try:
            if not DEBUG_FORCE_WELCOME_GIF and run_count < 3:
                forced_files = ["first_launch.txt", "readme.txt", "changelog.txt"]
                self._setup_text_content(situation, forced_file=forced_files[run_count])
            else:
                self._setup_text_content(situation)
        except Exception as e:
            self._body_label.setText(f"<p style='color: #ff6b6b;'>Error: {e}</p>")

        self._increment_run_count()
        self._update_continue_state()

    def load_situation_text(self, situation: str) -> None:
        self.load_asset(situation)

    def _check_scroll(self):
        sb = self.scroll.verticalScrollBar()
        current = sb.value()
        maximum = sb.maximum()
        threshold = 30

        was_open = self._gate_1_open
        self._gate_1_open = (maximum - current) <= threshold

        if self._gate_1_open:
            self.gate1_label.setStyleSheet("color: #4caf50; font-size: 11px;")
            self.gate1_label.setText("✓ Scrolled to bottom")
        else:
            self.gate1_label.setStyleSheet("color: #666666; font-size: 11px;")
            self.gate1_label.setText("📜 Scroll to bottom")

        if self._gate_1_open != was_open:
            self._update_continue_state()

    def on_panels_ready(self):
        self._gate_2_open = True
        self.gate2_label.setStyleSheet("color: #4caf50; font-size: 11px;")
        self.gate2_label.setText("✓ System ready")
        self._update_continue_state()

    def _update_continue_state(self):
        # gif is the checkbox — no manual ack when animation is playing
        if self._carousel.currentIndex() == 0:
            enabled = self._gate_1_open and self._gate_2_open
        else:
            enabled = self._gate_1_open and self._gate_2_open and self.ack_cb.isChecked()
        self.continue_btn.setEnabled(enabled)

    def _on_dismissed(self) -> None:
        """Guard says welcome phase is over — purge everything from RAM."""
        self._purge_media()