"""An empty provider account is not "busy".

A 429 with `insufficient_quota` will not pass by itself; telling people to
retry shortly sent them back to something that could not succeed.
"""

from backend.ai.client import _rate_limit_message


def test_an_account_with_no_credit_says_so() -> None:
    message = _rate_limit_message(
        Exception("Error code: 429 - {'error': {'type': 'insufficient_quota', 'code': 'credit_balance_exhausted'}}")
    )
    assert "no credit" in message and "retry shortly" not in message


def test_a_real_rate_limit_still_says_retry() -> None:
    assert "retry shortly" in _rate_limit_message(Exception("Rate limit reached for gpt in organization"))
