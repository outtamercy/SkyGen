#  feedback.py  – complete replacement (markdown formatted)
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal, QCoreApplication, QObject # type: ignore
from PyQt6.QtGui import QTextCharFormat, QColor, QTextCursor, QMovie # type: ignore
from PyQt6.QtWidgets import ( # type: ignore
    QGroupBox, QVBoxLayout, QHBoxLayout, QLabel,
    QPlainTextEdit, QSizePolicy, QMessageBox
)
from pathlib import Path
from typing import Optional

from ..utils.logger import (
    LoggingMixin, SkyGenLogger,
    MO2_LOG_DEBUG, MO2_LOG_INFO, MO2_LOG_WARNING,
    MO2_LOG_ERROR, MO2_LOG_CRITICAL, MO2_LOG_TRACE
)


class StatusLogWidget(QGroupBox, LoggingMixin):
    """
    Central log viewer for SkyGen.
    NEW:  append_line(msg, lvl)  – level-aware colour + prefix.
    All legacy helpers kept for compatibility.
    """

    def __init__(self, plugin_path: str, parent: Optional[object] = None):
        super().__init__(parent)
        self.setTitle("")
        self.plugin_path = Path(plugin_path)
        self._build_ui()
        self.log_debug("StatusLogWidget initialised.")

    # ------------------------------------------------------------------
    #  UI build – identical to your original
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        main_layout = QVBoxLayout(self)

        # header row (title + spinner)
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        self.title_label = QLabel(self.tr("Status Log"))
        self.title_label.setObjectName("statusLogTitle")
        header.addWidget(self.title_label)

        self.activity_indicator_label = QLabel(self)
        self.activity_movie: Optional[QMovie] = None
        self._setup_activity_indicator()
        header.addWidget(self.activity_indicator_label)
        header.addStretch(1)
        main_layout.addLayout(header)

        # log viewer
        self.log_display = QPlainTextEdit()
        self.log_display.setReadOnly(True)
        self.log_display.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.log_display.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.log_display.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.log_display.setPlaceholderText("Log messages will appear here …")
        self.log_display.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse |
            Qt.TextInteractionFlag.TextSelectableByKeyboard |
            Qt.TextInteractionFlag.LinksAccessibleByMouse
        )
        main_layout.addWidget(self.log_display)
        self._max_lines = 1000  # Prevent unbounded growth during long generations
    # ------------------------------------------------------------------
    #  NEW – single public entry point
    # ------------------------------------------------------------------
    def append_line(self, message: str, level: int = MO2_LOG_INFO) -> None:
        """Level-aware prefix + colour; append one line with timestamp."""
        from datetime import datetime
        
        timestamp = datetime.now().strftime("%H:%M:%S")
        prefix = {
            MO2_LOG_TRACE:   "[TRACE  ]",
            MO2_LOG_DEBUG:   "[DEBUG  ]",
            MO2_LOG_INFO:    "[INFO   ]",
            MO2_LOG_WARNING: "[WARNING]",
            MO2_LOG_ERROR:   "[ERROR  ]",
            MO2_LOG_CRITICAL: "[CRIT   ]"
        }.get(level, "[INFO   ]")

        fmt = QTextCharFormat()
        fmt.setForeground(self._colour_for_level(level))
        
        # Format: [HH:MM:SS] [LEVEL   ] Message
        full_line = f"[{timestamp}] {prefix} {message}"

        cursor = self.log_display.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        
        # Handle multiline messages (indent continuation)
        lines = full_line.split('\n')
        cursor.insertBlock()
        cursor.insertText(lines[0], fmt)
        
        # Indent subsequent lines for readability
        if len(lines) > 1:
            indent_fmt = QTextCharFormat()
            indent_fmt.setForeground(self._colour_for_level(level))
            indent_fmt.setFontItalic(True)
            for line in lines[1:]:
                cursor.insertBlock()
                cursor.insertText(f"           ↳ {line}", indent_fmt)  # Indent under timestamp/prefix

        self.log_display.setTextCursor(cursor)
        self.log_display.verticalScrollBar().setValue(
            self.log_display.verticalScrollBar().maximum()
        )
        
        # Prevent memory bloat: max 1000 lines
        doc = self.log_display.document()
        if doc.blockCount() > 1000:
            cursor.movePosition(QTextCursor.MoveOperation.Start)
            cursor.select(QTextCursor.SelectionType.BlockUnderCursor)
            cursor.removeSelectedText()
            cursor.deleteChar()  # Remove newline

    # ------------------------------------------------------------------
    #  Colour helper
    # ------------------------------------------------------------------
    def _colour_for_level(self, level: int) -> QColor:
        return {
            MO2_LOG_TRACE:   QColor("darkgray"),
            MO2_LOG_DEBUG:   QColor("lightgray"),
            MO2_LOG_INFO:    QColor("white"),
            MO2_LOG_WARNING: QColor("orange"),
            MO2_LOG_ERROR:   QColor("red"),
            MO2_LOG_CRITICAL:QColor("darkred")
        }.get(level, QColor("white"))

    # ------------------------------------------------------------------
    #  Activity spinner – keep your existing implementation
    # ------------------------------------------------------------------
    def _setup_activity_indicator(self) -> None:
        gif_path = Path(self.plugin_path) / "icons" / "loading.gif"
        if not gif_path.is_file():
            self.log_warning(f"GIF missing: {gif_path}")
            self.activity_indicator_label.setText("…")
            self.activity_movie = None
            return

        movie = QMovie(str(gif_path))
        if movie.isValid():
            self.activity_movie = movie
            self.activity_indicator_label.setMovie(self.activity_movie)
            self.activity_indicator_label.setFixedSize(24, 24)
            self.activity_indicator_label.hide()
        else:
            self.activity_indicator_label.setText("…")
            self.activity_movie = None

    def set_activity_indicator_state(self, is_active: bool) -> None:
        if self.activity_movie and self.activity_movie.isValid():
            if is_active:
                self.activity_indicator_label.show()
                self.activity_movie.start()
            else:
                self.activity_movie.stop()
                self.activity_indicator_label.hide()
        else:
            self.activity_indicator_label.setVisible(is_active)


# --------------------------------------------------------------------------
#  Utility message-box helper (unchanged)
# --------------------------------------------------------------------------
class MessageBoxes(QObject):
    def __init__(self, parent: Optional[object] = None):
        super().__init__(parent)
        self.parent = parent

    def showInformation(self, title: str, message: str) -> None:
        QMessageBox.information(self.parent, title, message)

    def showWarning(self, title: str, message: str) -> None:
        QMessageBox.warning(self.parent, title, message)

    def showCritical(self, title: str, message: str) -> None:
        QMessageBox.critical(self.parent, title, message)

    def showQuestion(self, title: str, message: str,
                     default: QMessageBox.StandardButton = QMessageBox.StandardButton.No) -> QMessageBox.StandardButton:
        return QMessageBox.question(
            self.parent, title, message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            default
        )