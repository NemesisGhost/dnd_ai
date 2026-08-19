from setup_demo_data import DEMO_ISSUER, DEMO_SLUG


def test_demo_identity_namespace_is_explicitly_non_production() -> None:
    assert DEMO_SLUG == "portal-demo"
    assert DEMO_ISSUER.endswith(".invalid")
