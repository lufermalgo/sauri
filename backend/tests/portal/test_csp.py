"""Parity with the inline-script hash used by the nginx build."""

import shutil
import subprocess
from pathlib import Path

import pytest

from app.portal.csp import inline_script_hash

HASH_SCRIPT = Path(__file__).resolve().parents[3] / "scripts/platform/inline-script-hash.mjs"


@pytest.mark.parametrize(
    "html",
    [
        '<script>window.theme = "dark";</script>',
        '<script src="/assets/app.js"></script><script>\r\n  // theme\r\n  var theme = "í🌙";\r\n</script>',
        '<script type="module" src="/assets/app.js"></script><script data-theme="true">\n\t theme();\n</script>',
        '<script src ="/assets/app.js">theme();</script>',
        '<script></script>',
    ],
)
def test_hash_matches_node(tmp_path: Path, html: str) -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    index = tmp_path / "index.html"
    index.write_bytes(html.encode("utf-8"))
    expected = subprocess.run([node, str(HASH_SCRIPT), str(index)], check=True, capture_output=True, text=True)
    assert inline_script_hash(index) == expected.stdout


@pytest.mark.parametrize(
    "html", ["<html></html>", '<script src="/app.js"></script>', '<script>a()</script><script>b()</script>']
)
def test_requires_exactly_one_inline_script(tmp_path: Path, html: str) -> None:
    index = tmp_path / "index.html"
    index.write_text(html)
    with pytest.raises(ValueError, match="expected exactly one inline script"):
        inline_script_hash(index)
