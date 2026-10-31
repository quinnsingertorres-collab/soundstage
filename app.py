"""Soundstage entry point."""
import sys


def main():
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    if sys.platform == "win32":
        try:  # own taskbar icon/grouping instead of python.exe's
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Soundstage.Mixer")
        except Exception:
            pass

    from soundstage import APP_NAME
    from soundstage.config import Settings
    from soundstage.engine import AudioEngine
    from soundstage.sessions import SessionManager
    from soundstage.ui.main_window import MainWindow
    from soundstage.ui.theme import STYLESHEET

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setQuitOnLastWindowClosed(False)
    app.setStyle("Fusion")
    app.setStyleSheet(STYLESHEET)

    settings = Settings()
    window = MainWindow(settings, AudioEngine(), SessionManager())
    if "--minimized" in sys.argv and window.tray:
        window.hide()
    else:
        window.show()
    QTimer.singleShot(150, window.start_engine)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
