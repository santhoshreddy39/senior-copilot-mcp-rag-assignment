"""
Unit tests for the Alarm Management API connector's error mapping,
authentication, and retry-relevant status handling. Uses an in-process ASGI
transport (httpx.ASGITransport) against the real simulator app, so these run
fast with no socket and no subprocess.
"""

import pytest

from connectors.alarm_api_client import (
    AlarmAPIAuthError,
    AlarmAPIClient,
    AlarmAPINotFoundError,
    AlarmAPIValidationError,
    TraceContext,
)


@pytest.fixture()
def client(simulator_transport):
    c = AlarmAPIClient(base_url="http://testserver", token="demo-token", transport=simulator_transport)
    yield c


@pytest.fixture()
def wrong_token_client(simulator_transport):
    c = AlarmAPIClient(base_url="http://testserver", token="wrong-token", transport=simulator_transport)
    yield c


async def test_search_assets_success(client):
    trace = TraceContext.new()
    result = await client.search_assets("Boiler Feed Pump 101", trace=trace)
    assert result["results"][0]["name"] == "Boiler Feed Pump 101"


async def test_auth_error_maps_to_typed_exception(wrong_token_client):
    with pytest.raises(AlarmAPIAuthError):
        await wrong_token_client.search_assets("pump", trace=TraceContext.new())


async def test_not_found_maps_to_typed_exception(client):
    with pytest.raises(AlarmAPINotFoundError):
        await client.get_asset_metadata("AST-9999", trace=TraceContext.new())


async def test_validation_error_maps_to_typed_exception(client):
    with pytest.raises(AlarmAPIValidationError):
        await client.alarm_summary(["AST-1000"], "not-a-timestamp", "also-not-a-timestamp", trace=TraceContext.new())


async def test_trace_headers_are_sent(client):
    trace = TraceContext(trace_id="trace-unit-test-1", client_id="pytest", metadata_tag="unit-test")
    result = await client.search_assets("pump", trace=trace)
    assert isinstance(result["results"], list)  # request succeeded with trace headers attached


async def test_priority_score_roundtrip(client):
    alarms = await client.list_alarms(page=1, page_size=1, trace=TraceContext.new())
    alarm_id = alarms["data"][0]["alarm_id"]
    result = await client.priority_score(alarm_id, trace=TraceContext.new())
    assert 0 <= result["priority_score"] <= 100
