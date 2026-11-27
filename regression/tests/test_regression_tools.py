"""The regression tooling itself: stage selection, the walkthrough's checks, and both report renderers.

Run: python3 -m pytest regression/tests (the ci stage runs it too).
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import report  # noqa: E402
import run  # noqa: E402
import walkthrough  # noqa: E402
import walkthrough_report  # noqa: E402


def test_default_runs_the_regression_stages_only():
    got = run.select_stages()
    assert "live" not in got and "walkthrough" not in got
    assert got[:3] == ["ci", "quality", "core"] and "manual" in got


def test_flags_add_live_and_the_walkthrough():
    assert "live" in run.select_stages(live=True)
    got = run.select_stages(with_walkthrough=True)
    assert got[-1] == "walkthrough" and "live" not in got


def test_stage_runs_just_that_stage_in_order():
    assert run.select_stages(stage=["walkthrough"]) == ["walkthrough"]
    assert run.select_stages(stage=["page", "ci"], with_walkthrough=True) == ["ci", "page"]


def test_every_stage_has_a_prefix_and_a_function():
    assert set(run.ORDER) == set(run.PREFIX) == set(run.STAGES)
    assert len(set(run.PREFIX.values())) == len(run.PREFIX)


def view(**over):
    d = {"nav": [{"label": "Food", "href": "#s-food"}, {"label": "Chart", "href": "#s-chart"}],
         "navHeads": [{"label": "Food", "href": "#s-food", "found": True, "heading": "Food 2 probes"},
                      {"label": "Chart", "href": "#s-chart", "found": True, "heading": "Temperatures 3h 6h"}],
         "vw": 390, "scrollW": 390, "offN": 0, "off": [], "wideN": 0, "wide": [], "smallN": 2,
         "small": ["3h (35x21)", "6h (35x21)"], "dead": []}
    d.update(over)
    return d


def test_walkthrough_checks_have_stable_keys_and_judge_each_rule():
    res = {k: (ok, det) for k, _, ok, det in walkthrough.checks_for("ha", "phone", "basic", view(), [])}
    assert res["ha phone basic › menu label matches heading: Food"][0] is True
    ok, det = res["ha phone basic › menu label matches heading: Chart"]
    assert ok is False and "Temperatures" in det
    assert res["ha phone basic › no horizontal scroll"][0] is True
    assert res["ha phone basic › tap targets at least 40x40 px"] == (False, "2 control(s) smaller: 3h (35x21); 6h (35x21)")
    assert res["ha phone basic › no console errors"][0] is True
    # (desktop: no tap-target rule; a wide page, dead links, duplicates and errors fail)
    bad = view(scrollW=500, dead=["#gone"], nav=[{"label": "Food", "href": "#a"}, {"label": "Food", "href": "#b"}], navHeads=[])
    res = {k: ok for k, _, ok, _ in walkthrough.checks_for("device", "desktop", "advanced", bad, ["TypeError: x"])}
    assert not any("tap targets" in k for k in res)
    assert res["device desktop advanced › no horizontal scroll"] is False
    assert res["device desktop advanced › no dead links"] is False
    assert res["device desktop advanced › no duplicate menu labels"] is False
    assert res["device desktop advanced › no console errors"] is False


def test_walkthrough_report_groups_findings_and_lists_checks(tmp_path):
    stage = {"results": [{"id": "WT-001", "check": "ha phone basic: no horizontal scroll", "status": "pass", "detail": ""},
                         {"id": "WT-002", "check": "ha phone basic: tap targets at least 40x40 px", "status": "fail", "detail": "3h (35x21)"}]}
    inv = {"views": [{"page": "ha", "width": "phone", "mode": "basic", "nav": [{"label": "Food"}],
                      "screens": [{"sect": "food", "heading": "Food", "buttons": ["Raise target"], "fields": []}], "screenshot": ""}]}
    fnd = {"summary": "Two things.", "findings": [
        {"id": "UX-001", "group": "rename", "title": "Chart is called Temperatures", "now": "Chart -> Temperatures",
         "proposal": "Call both Temperatures", "affects": "everyone", "effort": "S", "risk": "low", "evidence": ["shots/x.png"],
         "page": "both", "width": "both"},
        {"id": "UX-002", "group": "keep-separate", "title": "Power off stays two taps", "now": "", "proposal": "keep", "affects": "",
         "effort": "S", "risk": "", "evidence": [], "page": "device", "width": "phone"}]}
    out = walkthrough_report.page(stage, inv, fnd, when="2026-11-26 10:00", base=tmp_path)
    assert out.index("Rename (1)") < out.index("Keep separate (1)")
    assert "UX-001" in out and "Call both Temperatures" in out and "Two things." in out
    assert out.index("WT-002") < out.index("WT-001")  # failing checks first
    assert "<html" not in out.lower() and "<script" not in out.lower()


def test_walkthrough_report_loads_a_bare_findings_list(tmp_path):
    wt = tmp_path / "walkthrough"
    wt.mkdir()
    (wt / "findings.json").write_text(json.dumps([{"id": "UX-001", "group": "mobile", "title": "t"}]))
    stage, inv, fnd = walkthrough_report.load(tmp_path)
    assert fnd["findings"][0]["id"] == "UX-001" and stage["results"] == [] and inv["views"] == []


def test_regression_report_renders_stages_findings_and_coverage(tmp_path, monkeypatch):
    monkeypatch.setattr(report, "OUT", tmp_path)
    (tmp_path / "ci.json").write_text(json.dumps({"stage": "ci", "results": [
        {"id": "CI-001", "check": "versions agree", "status": "pass", "detail": ""},
        {"id": "CI-002", "check": "brand files in sync", "status": "fail", "detail": "logo differs"}]}))
    (tmp_path / "findings-security.json").write_text(json.dumps({"findings": [
        {"id": "SEC-001", "severity": "low", "area": "page", "title": "A thing", "verified": True}], "claims": []}))
    stages, findings, catalogue, notes = report.load()
    cov, unlisted = report.coverage(stages, catalogue)
    html = report.page(stages, findings, cov, unlisted, notes, "9.9.9", "2026-11-26 10:00")
    md = report.markdown(stages, findings, cov, unlisted, notes, "9.9.9", "2026-11-26 10:00")
    assert "CI-002" in html and "SEC-001" in html and "9.9.9" in html
    assert "CI-002" in md and "logo differs" in md


def test_the_walkthrough_inventory_in_the_standards_shape():
    inv = {"views": [{"page": "device", "width": "phone", "mode": "basic", "nav": [{"label": "Food"}],
                      "screens": [{"sect": "food", "heading": "Food", "buttons": ["Start"], "fields": [], "screenshot": "shots/a.png"}],
                      "setup_page": {"screens": [{"sect": "ai", "heading": "AI", "buttons": [], "fields": ["Key"], "screenshot": ""}]}}]}
    got = run.standard_inventory(inv)
    assert list(got) == ["owner"] and list(got["owner"]) == ["phone"]
    pages = got["owner"]["phone"]["pages"]
    assert [p["section"] for p in pages] == ["Food", "AI"] and pages[0]["screenshot"] == "walkthrough/shots/a.png"
    assert got["owner"]["phone"]["menu"][0]["items"] == ["Food"]


def test_the_standard_commands_are_answered():
    assert {"brief", "log", "summary", "manual", "schema", "walkthrough-due"} <= run.TOOLING
    assert run.result_file("walkthrough") == "walkthrough-checks.json" and run.result_file("ci") == "ci.json"


def test_walkthrough_report_reads_the_standards_reviewer_files(tmp_path):
    (tmp_path / "findings").mkdir()
    (tmp_path / "findings" / "walkthrough-phone.json").write_text(json.dumps({"reviewer": "phone", "status": "done", "findings": [
        {"id": "WP-001", "group": "naming", "title": "Two names", "detail": "Chart vs Temperatures", "proposal": "one name",
         "screenshots": ["walkthrough/shots/x.png"], "value": "high"}]}))
    (tmp_path / "walkthrough-checks.json").write_text(json.dumps({"results": [{"id": "WT-001", "check": "c", "status": "pass"}]}))
    stage, inv, fnd = walkthrough_report.load(tmp_path)
    f = fnd["findings"][0]
    assert f["group"] == "rename" and f["width"] == "phone" and f["evidence"] == ["shots/x.png"]
    assert stage["results"][0]["id"] == "WT-001"


def test_regression_report_reads_the_standards_findings_and_claims(tmp_path, monkeypatch):
    monkeypatch.setattr(report, "OUT", tmp_path)
    (tmp_path / "findings").mkdir()
    (tmp_path / "findings" / "claims.json").write_text(json.dumps({"reviewer": "claims", "status": "done", "findings": [
        {"id": "SEC-001", "severity": "low", "title": "t", "description": "d", "verified": True}],
        "claims": [{"id": "CLM-001", "held": True}]}))
    (tmp_path / "findings" / "walkthrough-phone.json").write_text(json.dumps({"reviewer": "phone", "findings": [{"id": "WP-001"}]}))
    stages, findings, catalogue, notes = report.load()
    assert [f["id"] for f in findings] == ["SEC-001"]
    assert notes["_claims"][0]["claim"].startswith("CLM-001: Only firmware signed")
