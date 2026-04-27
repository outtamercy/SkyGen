from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QCheckBox, 
    QPushButton, QScrollArea, QFrame, QSizePolicy
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QFont


class WelcomePanel(QWidget):
    """
    Gate 0: Acknowledgment screen with two-gate security.
    Gate 1: Scroll to bottom (30px threshold).
    Gate 2: Controller panels_ready signal.
    """
    continue_clicked = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._gate_1_open = False
        self._gate_2_open = False
        self._setup_ui()
        
    def _setup_ui(self):
        # Tighter margins (was 50,40,50,40)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)  # Tighter spacing (was 25)
        
        # Header 
        header = QLabel("Welcome to SkyGen®")
        header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header.setStyleSheet("""
            QLabel {
                color: #d4af37;
                font-size: 32px;
                font-weight: bold;
                margin-bottom: 5px;  /* <-- CHANGED: was 10px */
            }
        """)
        if hasattr(self.parent(), '_eagle_font'):
            header.setFont(self.parent()._eagle_font)
        layout.addWidget(header)
        
        # Subtitle
        sub = QLabel("Advanced Plugin Generation Environment")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setStyleSheet("color: #aaaaaa; font-size: 14px; margin-bottom: 10px;")  # <--  was 20px
        if hasattr(self.parent(), '_almendra_font'):
            sub.setFont(self.parent()._almendra_font)
        layout.addWidget(sub)
        
        # ===== SCROLL AREA =====
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setStyleSheet("""
            QScrollArea {
                border: 1px solid #444444;
                background-color: #1a1a1a;
            }
        """)
        
        # Content container - reduced forced height
        content = QWidget()
        content.setMinimumWidth(650)
        content.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding
        )
        content.setStyleSheet("background-color: #1a1a1a;")
        
        content_layout = QVBoxLayout(content)
        content_layout.setSpacing(12)  # <-- was 15
        content_layout.setContentsMargins(15, 15, 15, 15)  # <-- was 20,20,20,20
        
        # Body text - larger font, no max-width constraint (uses available space)
        welcome_html = """<div style='font-family: "EagleLake","Almendra", "Segoe UI", sans-serif; 
                            font-size: 18px; line-height: 1.5; color: #cccccc;'>
                    <p style='font-size: 28px; color: #d4af37; font-weight: bold; margin-bottom: 8px;'>
                        SkyGen® v.0.9 beta - The Future of Skypatcher and BOS Generation is Here!
                    </p>
                    <p style='font-style: regular; color: #aaaaaa; margin-bottom: 15px;'>
                        Look, I know the drill—you just want to click 'Generate' and get back into Skyrim. 
                    </p>
                    <p style='font-size: 16px; color: #888888; font-style: italic; margin-bottom: 15px;'>
                        Read to the bottom to let me know you've got the gist of it. Snoopy is almost done.
                    </p>
                    <p><b>What's actually happening:</b></p>
                    <p>SkyGen is an automation tool for Skypatcher and BOS. It finds your weapons, armor, and any other patchable records, then writes the output that is correct for SkyPatcher or BOS. 
                    No plugin slots used, no manual FormID hunting. no XEdit.</p>
                    <p style='margin-top: 12px;'><b>The "Cold Boot" (Why it's slow right now):</b></p>
                    <p>Since this is a fresh install or a modlist change, <b>Snoopy</b> (the extractor) is deep-scanning your modlist. On a large modlist such as Mayhem's Madness or Truth, that's a lot of math. 
                    <span style='color: #ff6b6b;'>Don't panic if it feels stuck</span>—it's just crunching data so the actual UI is snappy once you're in.</p>
                    <p style='margin-top: 12px;'><b>A few rules to live by:</b></p>
                    <ul>
                        <li><b>Trust the Blacklist:</b> If a mod is missing, it's probably a framework and as such is blacklisted. Check Audit for details.</li>
                        <li><b>Runtime Magic:</b> These patches use Skypatcher or Bos to run when you play the game. You can add or remove them mid-save without "Missing Plugin" warnings - no harm no foul.</li>
                        <li><b>Output:</b> You MUST choose an output folder. Move files to your mod folder after if needed.</li>
                    </ul>
                </div>"""
        
        body = QLabel(welcome_html)
        body.setWordWrap(True)
        body.setAlignment(Qt.AlignmentFlag.AlignTop)
        body.setOpenExternalLinks(False)
        content_layout.addWidget(body)
        
        # Checkbox moved inside scroll (forces Gate 1 compliance)
        self.ack_cb = QCheckBox("I have read the readme and understand")
        self.ack_cb.setStyleSheet("""
            QCheckBox {
                color: #ffffff;
                font-size: 14px;  /* <--  was 13px */
                spacing: 10px;
                padding: 8px;
                margin-top: 15px;
            }
            QCheckBox::indicator {
                width: 20px;
                height: 20px;
                border: 2px solid #555555;
                border-radius: 4px;
            }
            QCheckBox::indicator:checked {
                background-color: #d4af37;
                border-color: #d4af37;
            }
        """)
        self.ack_cb.stateChanged.connect(self._update_continue_state)
        content_layout.addWidget(self.ack_cb)
        
        # Finalize scroll - smaller minimum height
        self.scroll.setWidget(content)
        self.scroll.setMinimumHeight(200)
        self.scroll.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding
        )
        layout.addWidget(self.scroll, 1)
        
        # Gate status indicators
        status_layout = QHBoxLayout()
        self.gate1_label = QLabel("📜 Scroll to bottom")
        self.gate2_label = QLabel("⚙️ System ready")
        for lbl in (self.gate1_label, self.gate2_label):
            lbl.setStyleSheet("color: #666666; font-size: 11px;")
            status_layout.addWidget(lbl)
        status_layout.addStretch()
        layout.addLayout(status_layout)
        
        # Continue button
        self.continue_btn = QPushButton("Continue to Workspace")
        self.continue_btn.setEnabled(False)
        self.continue_btn.setMinimumHeight(40)  # <-- CHANGED: was 45
        self.continue_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.continue_btn.setStyleSheet("""
            QPushButton {
                background-color: #1a1a1a;
                color: #666666;
                border: 2px solid #444444;
                border-radius: 8px;
                font-size: 16px;
                font-weight: bold;
                padding: 0 20px;
            }
            QPushButton:enabled {
                background-color: #2d5016;
                color: #d4af37;
                border-color: #d4af37;
            }
            QPushButton:enabled:hover {
                background-color: #3d6820;
            }
        """)
        self.continue_btn.clicked.connect(self.continue_clicked.emit)
        layout.addWidget(self.continue_btn, alignment=Qt.AlignmentFlag.AlignCenter)
        
        # Scroll detection
        self.scroll.verticalScrollBar().valueChanged.connect(self._check_scroll)
        QTimer.singleShot(200, self._check_scroll)

    def showEvent(self, event):
            """KISS: When Welcome is showing, the workspace buttons are gone."""
            super().showEvent(event)
        
            # Access the Main Dialog (the root window)
            main_win = self.window()
        
            if main_win:
                # Match the variable names in your main_dialog.py exactly
                if hasattr(main_win, 'btn_generate_sp'):
                    main_win.btn_generate_sp.hide()
                
                if hasattr(main_win, 'btn_generate_bos'):
                    main_win.btn_generate_bos.hide()
                
                if hasattr(main_win, 'btn_stop_gen'):
                    main_win.btn_stop_gen.hide()
        
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
        """Gate 2: Controller signals UI/backend is fully initialized."""
        self._gate_2_open = True
        self.gate2_label.setStyleSheet("color: #4caf50; font-size: 11px;")
        self.gate2_label.setText("✓ System ready")
        self._update_continue_state()
        
    def _update_continue_state(self):
        enabled = self._gate_1_open and self._gate_2_open and self.ack_cb.isChecked()
        self.continue_btn.setEnabled(enabled)