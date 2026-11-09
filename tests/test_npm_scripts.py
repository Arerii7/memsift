from pathlib import Path

from memsift import db
from memsift.anchor import add_anchors
from memsift.detect import run_detectors
from memsift.export import export_markdown
from memsift.ingest.markdown import ingest_markdown


def test_missing_npm_script_is_reported_with_source(conn, cfg, tmp_path: Path) -> None:
    (tmp_path / 'package.json').write_text('{"scripts":{"test":"pytest"}}')
    source = tmp_path / 'AGENTS.md'
    source.write_text('# Instructions\n\n```bash\nnpm run test:unit\n```\n')
    ingest_markdown(conn, [tmp_path], cfg)
    report = run_detectors(conn, cfg)
    finding = next(item for item in report.findings if item.kind == 'stale_script')
    record = db.get_memory(conn, finding.memory_id)
    assert record.source_ref == f'{source}:4'
    assert 'test:unit' in finding.title
    assert 'package.json' in finding.detail


def test_existing_npm_script_is_not_reported(conn, cfg, tmp_path: Path) -> None:
    (tmp_path / 'package.json').write_text('{"scripts":{"test:unit":"pytest"}}')
    (tmp_path / 'AGENTS.md').write_text('- Run `npm run test:unit`\n')
    ingest_markdown(conn, [tmp_path], cfg)
    assert not [f for f in run_detectors(conn, cfg).findings if f.kind == 'stale_script']


def test_fenced_commands_are_not_anchored_or_exported(conn, cfg, tmp_path: Path) -> None:
    source = tmp_path / 'AGENTS.md'
    original = '# Instructions\n\n```bash\nnpm run test:unit\n```\n'
    source.write_text(original)
    ingest_markdown(conn, [tmp_path], cfg)
    assert add_anchors(source, config=cfg).count == 0
    assert 'npm run test:unit' not in export_markdown(conn)


def test_missing_script_finding_redacts_secret(conn, cfg, tmp_path: Path) -> None:
    secret = 'sk-proj-abcdefghijklmnop1234'
    (tmp_path / 'package.json').write_text('{"scripts":{}}')
    (tmp_path / 'AGENTS.md').write_text(f'- Run `npm run {secret}`\n')
    ingest_markdown(conn, [tmp_path], cfg)
    finding = next(f for f in run_detectors(conn, cfg).findings if f.kind == 'stale_script')
    assert secret not in finding.title + finding.detail


def test_manifest_without_scripts_reports_missing_command(conn, cfg, tmp_path: Path) -> None:
    (tmp_path / 'package.json').write_text('{}')
    (tmp_path / 'AGENTS.md').write_text('- Run `npm run test`\n')
    ingest_markdown(conn, [tmp_path], cfg)
    assert any(f.kind == 'stale_script' for f in run_detectors(conn, cfg).findings)


def test_finding_points_to_command_line_in_multiline_item(conn, cfg, tmp_path: Path) -> None:
    (tmp_path / 'package.json').write_text('{}')
    source = tmp_path / 'AGENTS.md'
    source.write_text('- Run tests:\n  npm run test:unit\n')
    ingest_markdown(conn, [tmp_path], cfg)
    finding = next(f for f in run_detectors(conn, cfg).findings if f.kind == 'stale_script')
    assert f'{source}:2' in finding.detail


def test_command_with_cd_is_not_checked_against_wrong_manifest(conn, cfg, tmp_path: Path) -> None:
    (tmp_path / 'package.json').write_text('{}')
    (tmp_path / 'AGENTS.md').write_text('```bash\ncd frontend && npm run build\n```\n')
    ingest_markdown(conn, [tmp_path], cfg)
    assert not [f for f in run_detectors(conn, cfg).findings if f.kind == 'stale_script']


def test_sentence_ending_after_script_is_not_part_of_name(conn, cfg, tmp_path: Path) -> None:
    (tmp_path / 'package.json').write_text('{"scripts":{"test":"pytest"}}')
    (tmp_path / 'AGENTS.md').write_text('- Run npm run test.\n')
    ingest_markdown(conn, [tmp_path], cfg)
    assert not [f for f in run_detectors(conn, cfg).findings if f.kind == 'stale_script']
