"""The Plugins page says what enabling a plugin with renderer.js gives it."""
import shutil
from pathlib import Path

import pytest
from conftest import REPO


@pytest.fixture
def plugin_with_renderer():
    from services import plugin_loader
    folder = Path("plugins/renderer_test")
    folder.mkdir()
    shutil.copy(REPO / "plugins/crtsh/plugin.yaml", folder / "plugin.yaml")
    (folder / "renderer.js").write_text("registerPluginRenderer('renderer_test', () => null);\n")
    plugin_loader.refresh(force=True)
    yield "renderer_test"
    shutil.rmtree(folder)
    plugin_loader.refresh(force=True)


def test_review_dialog_warns_about_renderer_js(client, plugin_with_renderer):
    files = client.get(f"/api/plugins/{plugin_with_renderer}/files").json()
    assert files["plugin"]["has_renderer"] is True
    assert "JavaScript" in files["plugin"]["blocked"]  # from another source: off until reviewed
    page = client.get("/plugins").text
    assert 'id="reviewRenderer"' in page and "same access as you" in page
