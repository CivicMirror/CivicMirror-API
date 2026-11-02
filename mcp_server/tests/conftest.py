import pytest


@pytest.fixture
def anyio_backend():
    """Run ``@pytest.mark.anyio`` tests on asyncio only (trio is not a dependency)."""
    return "asyncio"
