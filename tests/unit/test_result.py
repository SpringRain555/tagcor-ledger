from tagcor_ledger.application.result import Result


def test_result_factories_create_correlation_ids() -> None:
    ok = Result.ok()
    failed = Result.fail("VALIDATION_INVALID_AMOUNT", "Amount is invalid.")

    assert ok.success is True
    assert ok.correlation_id.startswith("corr_")
    assert failed.success is False
    assert failed.error_code == "VALIDATION_INVALID_AMOUNT"
    assert failed.correlation_id.startswith("corr_")
