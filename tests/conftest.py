import pytest


@pytest.fixture(autouse=True)
def isolated_pricing_config(tmp_path, monkeypatch):
    import coderay_utils.pricing as pricing_module
    monkeypatch.setattr(pricing_module, "CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(pricing_module, "OVERRIDE_FILE", str(tmp_path / "pricing.json"))
    yield
