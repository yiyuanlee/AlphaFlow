from alphaflow.options.unattended.broker import _normalise_status
from alphaflow.options.unattended.types import OrderLifecycle


def test_broker_order_status_mapping_covers_partial_reject_and_cancel():
    assert _normalise_status("Submitted", 0, 1) == OrderLifecycle.SUBMITTED.value
    assert _normalise_status("Submitted", 1, 1) == OrderLifecycle.PARTIALLY_FILLED.value
    assert _normalise_status("Filled", 1, 0) == OrderLifecycle.FILLED.value
    assert _normalise_status("Inactive", 0, 1) == OrderLifecycle.REJECTED.value
    assert _normalise_status("ApiCancelled", 0, 1) == OrderLifecycle.CANCELLED.value
