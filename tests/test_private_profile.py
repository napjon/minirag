from __future__ import annotations

import pytest
from pydantic import SecretStr

from backend.config import Settings
from backend.model_gateway.base import FixtureGateway, OpenAICompatGateway, get_gateway


def test_private_egress_blocked_forbids_hosted_gateway():
    settings = Settings(
        deployment_profile="private",
        private_egress_blocked=True,
        model_provider="hosted",
    )
    with pytest.raises(RuntimeError, match="hosted provider is forbidden in the private profile"):
        get_gateway(settings)


def test_private_egress_blocked_allows_fixture_gateway():
    settings = Settings(
        deployment_profile="private",
        private_egress_blocked=True,
        model_provider="fixture",
    )
    gateway = get_gateway(settings)
    assert isinstance(gateway, FixtureGateway)


def test_hosted_gateway_requires_api_key():
    settings = Settings(model_provider="hosted", hosted_model_api_key=None)
    with pytest.raises(RuntimeError, match="HOSTED_MODEL_API_KEY"):
        get_gateway(settings)


def test_hosted_gateway_constructs_when_key_present():
    settings = Settings(
        deployment_profile="hosted",
        private_egress_blocked=False,
        model_provider="hosted",
        hosted_model_api_key=SecretStr("sk-test-eval"),
    )
    gateway = get_gateway(settings)
    assert isinstance(gateway, OpenAICompatGateway)
    assert gateway.provider == "hosted"
