import copy

from liquidity_lens.ssi.redact import MASK, mask


def test_sensitive_keys_are_masked_case_insensitively():
    out = mask({"apiKey": "k1", "APISECRET": "s1", "accessToken": "a1", "refreshToken": "r1",
                "otp": "123456", "transactionId": "t1", "Authorization": "Bearer abc"})
    assert set(out.values()) == {MASK}


def test_non_sensitive_values_unchanged():
    data = {"tokenType": "Bearer", "expiresAt": 1779806203, "symbol": "SSI", "data": [{"close": "45.5"}]}
    assert mask(data) == data


def test_nested_and_lists():
    out = mask({"a": [{"accessToken": "x", "ok": 1}], "b": {"headers": {"authorization": "Bearer y"}}})
    assert out == {"a": [{"accessToken": MASK, "ok": 1}], "b": {"headers": {"authorization": MASK}}}


def test_secret_values_replaced_inside_free_text():
    out = mask({"msg": "bad key SECRETKEY123 for user", "items": ["x SECRETKEY123 y"]}, secrets=["SECRETKEY123"])
    assert "SECRETKEY123" not in str(out) and MASK in out["msg"]


def test_plain_string_input():
    assert mask("token=abcdef1234", secrets=["abcdef1234"]) == f"token={MASK}"


def test_empty_and_short_secrets_do_not_wreck_text():
    assert mask("hello", secrets=["", None]) == "hello"


def test_input_is_not_mutated():
    data = {"accessToken": "a", "n": {"apiKey": "k"}}
    before = copy.deepcopy(data)
    mask(data)
    assert data == before
