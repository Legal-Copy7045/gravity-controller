import pytest


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture(autouse=True)
def community_averages_offline(aioclient_mock):
    """The integration fetches the community averages at start: no network in tests."""
    from custom_components.smoker.sharing import AGGREGATES_URL

    aioclient_mock.get(AGGREGATES_URL, status=404)
    yield
