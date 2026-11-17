"""Exercise both TV entry points with a real browser and the authenticated Flask views."""
from datetime import datetime, timezone
import os
from unittest.mock import patch
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright

from test_planning_integration import connected


DAY = '2027-01-04'
INSTANT = datetime(2027, 1, 4, 10, 59, 20, tzinfo=timezone.utc)
INSIDE = """() => {
    const bounds = document.querySelector('.tv-body').getBoundingClientRect();
    const spans = [...document.querySelectorAll('#tv-entries li span')];
    return spans.length > 0 && spans.every(span => {
        const range = document.createRange();
        range.selectNodeContents(span);
        return [...range.getClientRects()].every(rect => rect.top >= bounds.top - 1 &&
            rect.left >= bounds.left - 1 && rect.right <= bounds.right + 1 && rect.bottom <= bounds.bottom + 1);
    });
}"""


def test_half_days_share_one_screen_and_switch_even_offline(connected):
    client, db, _, _ = connected
    morning = [f'Cours du matin {i} · Management opérationnel de la sécurité' for i in range(24)]
    afternoon = [f'Cours de l’après-midi {i} · Prévention des risques professionnels' for i in range(16)]
    shared = ['Journée entière', 'Cours qui traverse midi']
    with db() as conn:
        conn.execute('DELETE FROM planning_courses')
        for i, title in enumerate(morning + afternoon + shared + ['Cours PARIS']):
            room = 'Salle Paris' if title == 'Cours PARIS' else f'Salle Méditerranée {i}'
            conn.execute('INSERT INTO planning_rooms VALUES(?,?,1)', (str(i), room))
            start, end = ((480, 720) if title in morning else (720, 1020) if title in afternoon
                          else (0, 1440) if title == shared[0] else (660, 780))
            conn.execute("""INSERT INTO planning_room_reservations
                (id,room_id,date,start_min,end_min,title,trainer_names,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,'now','now')""",
                (str(i), str(i), DAY, start, end, title, 'Lou Martin-Dupont, Camille de Saint-Étienne'))
    offline = False
    def respond(route):
        url = urlsplit(route.request.url)
        if url.hostname != 'localhost':
            return route.abort()
        if url.path.endswith('/api/rooms/affichage-tv') and offline:
            return route.abort()
        with patch('planning_room_calendar.datetime') as now:
            now.now.side_effect = INSTANT.astimezone
            response = client.get(url.path + ('?' + url.query if url.query else ''))
        route.fulfill(status=response.status_code, content_type=response.content_type, body=response.data)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=os.environ.get('CHROMIUM_EXECUTABLE_PATH'))
        context = browser.new_context(viewport={'width': 1280, 'height': 720}, timezone_id='America/Los_Angeles')
        context.route('**/*', respond)
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.clock.install(time=INSTANT)
        page.goto('http://localhost/admin/salles', wait_until='domcontentloaded')
        page.locator('#room-tv-open').click()
        page.wait_for_function("document.fullscreenElement?.id === 'room-tv'")
        titles = page.locator('#tv-entries .tv-title')
        expect(titles).to_have_count(len(morning + shared))
        assert set(titles.all_text_contents()) == set(morning + shared)
        expect(page.locator('.tv-trainers').first).to_have_text('Avec Lou Martin-Dupont et Camille de Saint-Étienne')
        page.wait_for_function(INSIDE)
        page.clock.fast_forward(15000)
        assert set(titles.all_text_contents()) == set(morning + shared)
        offline = True
        page.clock.fast_forward(31000)
        expect(page.locator('#room-tv-heading')).to_have_text('Cours de l’après-midi')
        assert set(titles.all_text_contents()) == set(afternoon + shared)
        page.wait_for_function(INSIDE)
        page.locator('#tv-close').click()
        expect(page.locator('#room-tv-dialog')).not_to_be_visible()
        page.wait_for_function('!document.fullscreenElement')
        offline = False
        page.goto('http://localhost/admin/salles/affichage-tv')
        expect(titles).to_have_count(len(morning + shared))
        for width, height in [(1920, 1080), (1024, 576), (390, 844)]:
            page.set_viewport_size({'width': width, 'height': height})
            page.wait_for_function(INSIDE)
            assert set(titles.all_text_contents()) == set(morning + shared)
        assert not errors
        browser.close()
