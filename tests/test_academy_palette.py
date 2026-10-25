"""Colour-only regressions: contrast and protected public/status treatments."""
from pathlib import Path
import re

import cssselect2
from lxml import html
import tinycss2

CSS = Path(__file__).resolve().parents[1] / 'static/css/academy-vibrant.css'


def contrast(first, second):
    def luminance(value):
        channels = [int(value[index:index + 2], 16) / 255 for index in (1, 3, 5)]
        linear = [channel / 12.92 if channel <= .04045 else ((channel + .055) / 1.055) ** 2.4 for channel in channels]
        return sum(channel * weight for channel, weight in zip(linear, (.2126, .7152, .0722)))
    dark, light = sorted((luminance(first), luminance(second)))
    return (light + .05) / (dark + .05)


def stylesheet():
    rules = tinycss2.parse_stylesheet(CSS.read_text(), skip_comments=True, skip_whitespace=True)
    assert all(rule.type == 'qualified-rule' for rule in rules)
    result = []
    for rule in rules:
        declarations = tinycss2.parse_declaration_list(rule.content, skip_comments=True, skip_whitespace=True)
        assert all(item.type == 'declaration' for item in declarations)
        result.append((tinycss2.serialize(rule.prelude).strip(), {item.name: tinycss2.serialize(item.value).strip() for item in declarations}))
    return result


def test_text_and_primary_actions_retain_readable_contrast():
    palette = dict(stylesheet()[0][1])
    for name in ('ink', 'muted', 'olive', 'olive-hover', 'ochre', 'success', 'danger', 'terracotta'):
        assert contrast(palette['--academy-' + name], palette['--academy-card']) >= 4.5, name
    for accent in re.findall(r'--daily-accent:(#[a-f0-9]{6})', CSS.read_text()):
        assert contrast(accent, '#ffffff') >= 4.5
    assert contrast(palette['--academy-gold'], '#103d30') >= 4.5


def test_refresh_does_not_repaint_holidays_warnings_or_application_journey():
    # These representative elements must keep their own component's background.
    tree = html.fromstring('''<html><body class="academy-ui application-page" id="application-body">
      <div class="planning-event is-incomplete" id="course-warning"></div>
      <div class="planning-day-heading kind-public_holiday" id="holiday"></div>
      <article class="portal-course-card is-incomplete" id="portal-warning"></article>
      <button class="ta-day is-public-holiday" id="calendar-holiday"></button>
      <div class="application-aside" id="application-aside"></div>
      <button class="button-dark" id="application-action"></button>
    </body></html>''')
    matcher = cssselect2.Matcher()
    for selector, declarations in stylesheet():
        if '::-webkit-' in selector or '::-moz-' in selector:
            continue  # Browser-only meter pseudo-elements cannot match these nodes.
        for compiled in cssselect2.compile_selector_list(selector):
            matcher.add_selector(compiled, declarations)
    protected = {'application-body', 'course-warning', 'holiday', 'portal-warning', 'calendar-holiday', 'application-aside', 'application-action'}
    for element in cssselect2.ElementWrapper.from_html_root(tree).iter_subtree():
        if element.etree_element.get('id') not in protected:
            continue
        for _, _, pseudo, declarations in matcher.match(element):
            if pseudo is None:
                assert not {'background', 'background-color', 'background-image'} & declarations.keys(), element.etree_element.get('id')
