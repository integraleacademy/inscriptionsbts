"""Render the actual import page with synthetic records for browser checks."""
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from test_planning_integration import connected


if __name__ == '__main__':
    output = ROOT / 'tmp' / 'import-qa'
    output.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory() as directory:
        client, *_ = connected.__wrapped__(Path(directory))
        page = client.get('/admin/planning/import?promotion_id=demo&period_id=demo:1')
        assert page.status_code == 200, page.text
        (output / 'import.html').write_text(page.text, encoding='utf-8')
