"""Render real Flask templates with synthetic data for the jsdom journey test."""
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from test_planning_integration import connected


def render():
    output = ROOT / 'tmp' / 'reference-qa'
    output.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory() as directory:
        client, _, *_ = connected.__wrapped__(Path(directory))
        page = client.get('/admin/matieres?promotion_id=demo')
        assert page.status_code == 200
        (output / 'matieres.html').write_text(page.text)
        settings = client.get('/admin/parametres')
        assert settings.status_code == 200
        (output / 'settings.html').write_text(settings.text)
        (output / 'catalog.json').write_text(client.get('/admin/planning/api/catalog').text)


if __name__ == '__main__':
    render()
