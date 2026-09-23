# Pytest configuration and shared fixtures


# Pytest markers for test layer categorization
def pytest_configure(config):
    config.addinivalue_line("markers", "unit: Pure function tests with no I/O")
    config.addinivalue_line("markers", "contract: Skill contract validation tests")
    config.addinivalue_line("markers", "integration: Multi-component tests with fakes")
    config.addinivalue_line("markers", "e2e: Full system tests with real HTTP/process")
    config.addinivalue_line("markers", "fault: Fault injection and recovery tests")
    config.addinivalue_line("markers", "security: Authorization and authentication tests")
    config.addinivalue_line("markers", "smoke: Quick sanity checks")
    config.addinivalue_line("markers", "slow: Long-running tests")
