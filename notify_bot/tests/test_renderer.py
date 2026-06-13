"""Tests for core/renderer.py — HTML escaping, due formats, fallbacks."""

from notify_bot.core.models import Event, EventKind, TaskState
from notify_bot.core.renderer import render


def make_task(
    page_id="p1",
    title="My Task",
    status="В работе",
    assignees=("Alice",),
    reporter=(),
    due_start=None,
    due_end=None,
    url="https://notion.so/p1",
    last_edited_time="2024-01-01T00:00:00Z",
):
    return TaskState(
        page_id=page_id,
        title=title,
        status=status,
        assignees=frozenset(assignees),
        reporter=frozenset(reporter),
        project_ids=(),
        due_start=due_start,
        due_end=due_end,
        url=url,
        last_edited_time=last_edited_time,
    )


TZ = "Europe/Moscow"


def test_new_assignee_template_structure():
    task = make_task()
    event = Event("p1", EventKind.NEW_ASSIGNEE, target_name="Alice")
    text = render(event, task, "Project X", TZ)
    assert "🆕 Новая задача · All Tasks" in text
    assert "«My Task»" in text
    assert "Проект: Project X" in text
    assert "Дедлайн: —" in text
    assert "Открыть в Notion" in text


def test_status_changed_template_structure():
    task = make_task(status="В работе")
    event = Event("p1", EventKind.STATUS_CHANGED, old_status="Сделать", new_status="В работе")
    text = render(event, task, None, TZ)
    assert "🔄 Статус изменён · All Tasks" in text
    assert "Сделать → В работе" in text


def test_html_escape_title():
    task = make_task(title="<script>alert('xss')</script>")
    event = Event("p1", EventKind.NEW_ASSIGNEE, target_name="Alice")
    text = render(event, task, None, TZ)
    assert "<script>" not in text
    assert "&lt;script&gt;" in text


def test_html_escape_ampersand_in_title():
    task = make_task(title="Task & More")
    event = Event("p1", EventKind.NEW_ASSIGNEE, target_name="Alice")
    text = render(event, task, None, TZ)
    assert "Task &amp; More" in text


def test_html_escape_project_name():
    task = make_task()
    event = Event("p1", EventKind.NEW_ASSIGNEE, target_name="Alice")
    text = render(event, task, "Proj <b>X</b>", TZ)
    assert "Proj &lt;b&gt;X&lt;/b&gt;" in text


def test_html_escape_status_in_status_changed():
    task = make_task()
    event = Event("p1", EventKind.STATUS_CHANGED, old_status="<bad>", new_status="<also bad>")
    text = render(event, task, None, TZ)
    assert "<bad>" not in text
    assert "&lt;bad&gt;" in text


def test_empty_title_fallback():
    task = make_task(title="")
    event = Event("p1", EventKind.NEW_ASSIGNEE, target_name="Alice")
    text = render(event, task, None, TZ)
    assert "(без названия)" in text


def test_no_project_dash_fallback():
    task = make_task()
    event = Event("p1", EventKind.NEW_ASSIGNEE, target_name="Alice")
    text = render(event, task, None, TZ)
    assert "Проект: —" in text


def test_due_none_fallback():
    task = make_task(due_start=None)
    event = Event("p1", EventKind.NEW_ASSIGNEE, target_name="Alice")
    text = render(event, task, None, TZ)
    assert "Дедлайн: —" in text


def test_due_start_only():
    task = make_task(due_start="2024-03-15")
    event = Event("p1", EventKind.NEW_ASSIGNEE, target_name="Alice")
    text = render(event, task, None, TZ)
    assert "15.03" in text


def test_due_range():
    task = make_task(due_start="2024-03-15", due_end="2024-03-20")
    event = Event("p1", EventKind.NEW_ASSIGNEE, target_name="Alice")
    text = render(event, task, None, TZ)
    assert "15.03 → 20.03" in text


def test_url_in_link():
    task = make_task(url="https://notion.so/page123")
    event = Event("p1", EventKind.NEW_ASSIGNEE, target_name="Alice")
    text = render(event, task, None, TZ)
    assert 'href="https://notion.so/page123"' in text


def test_url_html_escaped():
    task = make_task(url="https://notion.so/page?a=1&b=2")
    event = Event("p1", EventKind.NEW_ASSIGNEE, target_name="Alice")
    text = render(event, task, None, TZ)
    assert "a=1&amp;b=2" in text
