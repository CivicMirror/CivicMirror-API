import pytest
from django.core.exceptions import ImproperlyConfigured

from cm2_core.isolation import require_database_name, require_task_queue


@pytest.mark.parametrize("configured", ["", "civicmirror", "civicmirror_test", "civicmirror_2_0_test"])
def test_database_guard_rejects_every_name_except_the_expected_name(configured):
    with pytest.raises(ImproperlyConfigured, match="expected 'civicmirror_2_0'"):
        require_database_name(configured, "civicmirror_2_0")


def test_database_guard_accepts_exact_expected_name():
    require_database_name("civicmirror_2_0", "civicmirror_2_0")


@pytest.mark.parametrize("configured", ["", "celery", "civicmirror", "civicmirror_2_0_test"])
def test_queue_guard_rejects_every_name_except_the_v2_queue(configured):
    with pytest.raises(ImproperlyConfigured, match="expected 'civicmirror_2_0'"):
        require_task_queue(configured)


def test_queue_guard_accepts_exact_v2_queue():
    require_task_queue("civicmirror_2_0")
