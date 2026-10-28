import json
import subprocess

from screening_agent.channels.admin_cli import start_from_file
from tests.conftest import FakeOutbound


def write(tmp_path, entries):
    path = tmp_path / "applicants.json"
    path.write_text(json.dumps(entries))
    return path


def test_start_from_file_opens_each_applicant_once_and_reports_duplicates(make_engine, tmp_path):
    engine, repository, _ = make_engine([])
    outbound = FakeOutbound()
    path = write(
        tmp_path,
        [
            {"name": "Ana García", "phone": "+34600111222", "language": "es"},
            {"name": "Brittany Walker", "phone": "+19034231678", "language": "en"},
        ],
    )
    first = start_from_file(path, engine, outbound)
    assert [(line.split("\t")[0], line.split("\t")[-1]) for line in first] == [
        ("+34600111222", "opened"),
        ("+19034231678", "opened"),
    ]
    assert [(phone, name) for phone, _, name in outbound.openers] == [
        ("+34600111222", "Ana"),
        ("+19034231678", "Brittany"),
    ]
    assert outbound.openers[0][1].startswith("¡Hola, Ana!")
    assert repository.get_candidate("+34600111222").applicant_name == "Ana García"
    second = start_from_file(path, engine, outbound)
    assert all(line.endswith("skipped, already exists") for line in second)
    assert len(outbound.openers) == 2


def test_start_from_file_dry_run_sends_and_stores_nothing(make_engine, tmp_path):
    engine, repository, _ = make_engine([])
    outbound = FakeOutbound()
    path = write(tmp_path, [{"name": "Ana García", "phone": "+34600111222", "language": "es"}])
    lines = start_from_file(path, engine, outbound, dry_run=True)
    assert lines == ["+34600111222\tAna García\tes\twould open"]
    assert outbound.openers == []
    assert not repository.conversation_exists("+34600111222")


def test_start_from_file_rejects_a_bad_entry_before_sending_anything(make_engine, tmp_path):
    engine, repository, _ = make_engine([])
    outbound = FakeOutbound()
    path = write(
        tmp_path,
        [
            {"name": "Ana García", "phone": "+34600111222", "language": "es"},
            {"name": "12345", "phone": "+34600111223", "language": "es"},
        ],
    )
    try:
        start_from_file(path, engine, outbound)
    except ValueError as exc:
        assert "entry 2" in str(exc)
    else:
        raise AssertionError("a bad entry must be refused")
    assert outbound.openers == []
    assert not repository.conversation_exists("+34600111222")


def test_real_applicant_file_is_ignored_by_git_and_the_example_is_valid():
    ignored = subprocess.run(
        ["git", "check-ignore", "-q", "applicants/applicants.local.json"], capture_output=True
    )
    assert ignored.returncode == 0
    tracked = subprocess.run(
        ["git", "check-ignore", "-q", "applicants/applicants.example.json"], capture_output=True
    )
    assert tracked.returncode == 1
    entries = json.loads(open("applicants/applicants.example.json").read())
    assert {tuple(sorted(entry)) for entry in entries} == {("language", "name", "phone")}
