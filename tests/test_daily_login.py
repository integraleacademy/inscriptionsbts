from datetime import datetime, timezone

import pytest

from daily_login import DAYS, login_scene


def test_seven_unique_scenes_for_each_role_and_no_shared_images():
    students = [login_scene('student', datetime(2026, 10, 19 + day, 12, tzinfo=timezone.utc)) for day in range(7)]
    trainers = [login_scene('trainer', datetime(2026, 10, 19 + day, 12, tzinfo=timezone.utc)) for day in range(7)]
    assert [scene['day'] for scene in students] == list(DAYS)
    assert len({scene['image'] for scene in students + trainers}) == 14
    assert len({scene['tone'] for scene in students}) == len({scene['tone'] for scene in trainers}) == 7
    assert all(left['tone'] != right['tone'] for left, right in zip(students, trainers))


@pytest.mark.parametrize('before,after', [
    ('2026-07-05T21:59:59+00:00', '2026-07-05T22:00:00+00:00'),
    ('2026-12-06T22:59:59+00:00', '2026-12-06T23:00:00+00:00'),
])
def test_day_changes_at_paris_midnight_in_summer_and_winter(before, after):
    assert login_scene('student', datetime.fromisoformat(before))['day'] == 'sun'
    assert login_scene('student', datetime.fromisoformat(after))['day'] == 'mon'


def test_changing_role_does_not_change_the_calendar_day():
    now = datetime(2026, 10, 24, 23, 30, tzinfo=timezone.utc)
    assert login_scene('student', now)['day'] == login_scene('trainer', now)['day'] == 'sun'
