from tagcor_ledger.app.resources import read_text_resource, resource_exists


def test_styles_resource_is_packaged() -> None:
    assert resource_exists("styles.qss")
    assert "QLineEdit:focus" in read_text_resource("styles.qss")


def test_styles_define_input_text_and_background_colors() -> None:
    styles = read_text_resource("styles.qss")

    assert "QLineEdit," in styles
    assert "QComboBox," in styles
    assert "color: #17202A;" in styles
    assert "background-color: #FFFFFF;" in styles
    assert "selection-background-color: #1F6FEB;" in styles
