"""The launcher must never serve against or shut down a different MongoDB process."""
import sys
from unittest.mock import Mock
import pytest
import run_local


@pytest.mark.parametrize('server_pid', [43210, 98765])
def test_mongo_process_ownership(monkeypatch, tmp_path, server_pid):
    (tmp_path / '.env').write_text('APP_SECRET=fixture-only\n', encoding='utf-8')
    monkeypatch.setattr(run_local, '__file__', str(tmp_path / 'run_local.py'))
    monkeypatch.setattr(sys, 'argv', ['run_local.py', '--data-dir', str(tmp_path / 'mongo')])
    process = Mock(pid=43210)
    process.poll.return_value = None
    client = Mock()
    client.admin.command.side_effect = lambda name, **kw: {'pid': server_pid} if name == 'serverStatus' else {'ok': 1}
    web = Mock()
    monkeypatch.setattr(run_local.subprocess, 'Popen', lambda *a, **kw: process)
    monkeypatch.setattr(run_local, 'MongoClient', lambda *a, **kw: client)
    monkeypatch.setattr(run_local.uvicorn, 'run', web)
    if server_pid != process.pid:
        with pytest.raises(RuntimeError, match='进程'):
            run_local.main()
        web.assert_not_called()
        assert not any(c.args[0] == 'shutdown' for c in client.admin.command.call_args_list)
        process.terminate.assert_called_once()
    else:
        run_local.main()
        web.assert_called_once()
        assert any(c.args[0] == 'shutdown' for c in client.admin.command.call_args_list)
    client.close.assert_called_once()
