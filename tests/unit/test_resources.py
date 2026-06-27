from tagcor_ledger.app.resources import read_text_resource, resource_exists


def test_styles_resource_is_packaged() -> None:
    assert resource_exists("styles.qss")
    assert "QLineEdit:focus" in read_text_resource("styles.qss")


def test_styles_define_dark_theme_colors_and_scoped_widgets() -> None:
    styles = read_text_resource("styles.qss")

    assert "QLineEdit," in styles
    assert "QComboBox," in styles
    assert "color: #E5E7EB;" in styles
    assert "background-color: #0F172A;" in styles
    assert "selection-background-color: #2563EB;" in styles
    assert "QTabBar::tab" in styles
    assert "QListWidget#sidebarNavigation" in styles
    assert "QListWidget#backupList" in styles
    assert "QPushButton#dangerButton" in styles
