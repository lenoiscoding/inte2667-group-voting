"""Req 16: password fields are masked, with an optional Show/Hide button.

The button is added in the browser by static/js/password_toggle.js, so these
tests check what the server sends.
"""
import re

import pytest

PAGES_WITH_PASSWORD = ["/auth/login", "/registration/register"]


@pytest.mark.parametrize("path", PAGES_WITH_PASSWORD)
def test_password_starts_masked_and_page_loads_toggle(client, path):
    html = client.get(path).get_data(as_text=True)
    field = re.search(r'<input[^>]*name="password"[^>]*>', html).group(0)
    assert 'type="password"' in field
    assert "js/password_toggle.js" in html


def test_toggle_rehides_password_and_blocks_spellcheck(client):
    js = client.get("/static/js/password_toggle.js").get_data(as_text=True)
    assert '"submit"' in js and "setTimeout" in js  # hidden on submit and after 10 s
    assert "input.spellcheck = false" in js  # revealed text never sent to spell-check
