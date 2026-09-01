from veriforge.explorer.browser import BrowserExplorer, _parse_aria_snapshot


def test_parses_interactive_roles_from_aria_snapshot_text():
    snapshot = '''
- heading "Projects" [level=1]
- list:
  - listitem:
    - text: proj-a
    - button "Delete"
- button "Create Project"
- link "Home"
'''
    elements = _parse_aria_snapshot(snapshot)
    roles_names = {(e.role, e.name) for e in elements}
    assert ("button", "Delete") in roles_names
    assert ("button", "Create Project") in roles_names
    assert ("link", "Home") in roles_names
    # "heading" is not an interactive role -- must not show up
    assert not any(e.role == "heading" for e in elements)


def test_destructive_names_are_flagged():
    snapshot = '- button "Delete"\n- button "Save"\n'
    elements = _parse_aria_snapshot(snapshot)
    by_name = {e.name: e for e in elements}
    assert by_name["Delete"].looks_destructive is True
    assert by_name["Save"].looks_destructive is False


def test_explore_example_app_ui_discovers_and_clicks_create_button(example_app_server):
    result = BrowserExplorer(headless=True).explore(f"{example_app_server}/ui", max_clicks=3)

    roles_names = {(e.role, e.name) for e in result.pages[0].elements}
    assert ("button", "Create Project") in roles_names
    assert any("Create Project" in step for step in result.workflow_steps)
    # Delete buttons only exist once a project has been created; either way
    # they must never be auto-clicked -- destructive names are always skipped.
    assert all("Delete" not in step or "clicked" not in step for step in result.workflow_steps)


def test_explore_skips_delete_buttons_as_destructive(example_app_server):
    import httpx

    httpx.post(f"{example_app_server}/projects", timeout=5.0)  # seed one project to delete

    result = BrowserExplorer(headless=True).explore(f"{example_app_server}/ui", max_clicks=5)

    assert any("Delete" in s and "looks destructive" in s for s in result.skipped_destructive)
    assert not any("clicked button \"Delete\"" in step for step in result.workflow_steps)


def test_explore_captures_network_and_console(example_app_server):
    result = BrowserExplorer(headless=True).explore(f"{example_app_server}/ui", max_clicks=1)

    urls = [ev.url for ev in result.network_events]
    assert any("/projects" in u for u in urls)


def test_explore_writes_screenshot_when_dir_given(example_app_server, tmp_path):
    screenshot_dir = tmp_path / "shots"
    result = BrowserExplorer(headless=True).explore(
        f"{example_app_server}/ui", max_clicks=1, screenshot_dir=screenshot_dir
    )

    assert result.pages[0].screenshot_path is not None
    assert (screenshot_dir / "page_0.png").exists()
