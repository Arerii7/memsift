import os
import stat

import pytest

from memsift import db


def test_index_is_private_with_permissive_umask(tmp_path):
    path = tmp_path / 'memsift.db'
    old_umask = os.umask(0o022)
    try:
        connection = db.connect(path)
        connection.execute("INSERT INTO detector_runs (started_at, finished_at, stats_json) VALUES (1, 1, '{}')")
        connection.commit()
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        for sidecar in (tmp_path / 'memsift.db-wal', tmp_path / 'memsift.db-shm'):
            if sidecar.exists():
                assert stat.S_IMODE(sidecar.stat().st_mode) & 0o077 == 0
        connection.close()
    finally:
        os.umask(old_umask)


def test_index_refuses_symlink_without_changing_target(tmp_path):
    target = tmp_path / 'other.db'
    target.write_text('unrelated')
    target.chmod(0o644)
    path = tmp_path / 'memsift.db'
    path.symlink_to(target)
    with pytest.raises(OSError):
        db.connect(path)
    assert stat.S_IMODE(target.stat().st_mode) == 0o644
