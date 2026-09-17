import io
import json
import sys
import threading
from unittest import mock

import pytest

from hart.minions import check_existing_minion
from hart.parallel import (
    STATE_CONNECTED,
    STATE_FAILED,
    STATE_RUNNING,
    MinionCreationJob,
    ThreadOutputMultiplexer,
    create_and_connect_minion,
    create_minions_in_parallel,
    tail_log,
)


def test_thread_output_multiplexer_routes_registered_threads():
    fallback = io.StringIO()
    mux = ThreadOutputMultiplexer(fallback)
    thread_target = io.StringIO()

    def write_from_thread():
        mux.register_current_thread(thread_target)
        mux.write('from thread\n')

    thread = threading.Thread(target=write_from_thread)
    thread.start()
    thread.join()
    mux.write('from main\n')

    assert thread_target.getvalue() == 'from thread\n'
    assert fallback.getvalue() == 'from main\n'


def test_create_minions_in_parallel_reports_failures(capsys):
    def create_and_connect(job):
        print('working on %s' % job.minion_id)
        if job.minion_id == 'b.example.com':
            raise ValueError('provider exploded')
        job.state = STATE_RUNNING

    specs = [{'minion_id': 'a.example.com'}, {'minion_id': 'b.example.com'}]
    failed = create_minions_in_parallel(specs, create_and_connect)

    assert [job.minion_id for job in failed] == ['b.example.com']
    assert failed[0].state == STATE_FAILED
    assert failed[0].error == 'provider exploded'

    # The workers' output went to their log files, not the terminal
    with open(failed[0].log_path) as fh:
        log = fh.read()
    assert 'working on b.example.com' in log
    assert 'ValueError' in log
    output = capsys.readouterr().out
    assert 'working on' not in output
    assert '1/2 minions created successfully' in output
    assert 'b.example.com: failed (provider exploded)' in output


def test_create_minions_in_parallel_restores_stdout():
    original_stdout, original_stderr = sys.stdout, sys.stderr

    def create_and_connect(job):
        pass

    failed = create_minions_in_parallel([{'minion_id': 'a.example.com'}],
        create_and_connect)

    assert failed == []
    assert sys.stdout is original_stdout
    assert sys.stderr is original_stderr


def test_state_transitions_are_reported(capsys):
    def create_and_connect(job):
        job.state = STATE_RUNNING

    jobs_failed = create_minions_in_parallel([{'minion_id': 'a.example.com'}],
        create_and_connect)

    assert jobs_failed == []
    output = capsys.readouterr().out
    assert 'a.example.com: connected' in output


@mock.patch('hart.parallel.connect_minion')
@mock.patch('hart.parallel.create_node')
def test_create_and_connect_runs_post_create_hook_before_connecting(
        mock_create_node, mock_connect):
    events = []
    mock_connect.side_effect = lambda node, script: events.append('connect')
    job = MinionCreationJob({'minion_id': 'a.example.com'}, create_and_connect_minion)

    create_and_connect_minion(job, post_create=lambda node: events.append('post_create'))

    assert events == ['post_create', 'connect']


@mock.patch('hart.parallel.disconnect_minion')
@mock.patch('hart.parallel.destroy_node')
@mock.patch('hart.parallel.create_node')
def test_failing_post_create_hook_destroys_the_node(
        mock_create_node, mock_destroy, mock_disconnect):
    job = MinionCreationJob({'minion_id': 'a.example.com'}, create_and_connect_minion)

    def post_create(hart_node):
        raise ValueError('firewall broke')

    with pytest.raises(ValueError):
        create_and_connect_minion(job, post_create=post_create)

    mock_destroy.assert_called_once_with(mock_create_node.return_value)
    mock_disconnect.assert_called_once_with('a.example.com')


@mock.patch('hart.minions.subprocess.check_output')
def test_check_existing_minion_non_interactive_aborts(mock_check_output):
    mock_check_output.return_value = json.dumps({
        'minions': ['minion.example.com'],
    }).encode('utf-8')

    assert check_existing_minion('minion.example.com', non_interactive=True) is False


@mock.patch('hart.minions.subprocess.check_output', return_value=b'{}')
def test_check_existing_minion_non_interactive_continues_when_new(mock_check_output):
    assert check_existing_minion('minion.example.com', non_interactive=True) is True


def test_tail_log_keeps_last_lines(tmp_path):
    log_path = tmp_path / 'minion.log'
    log_path.write_text('one\ntwo\nprogress 1\rprogress 2\rprogress 3\nthree\n')

    assert tail_log(str(log_path), 3) == ['progress 2', 'progress 3', 'three']
    assert tail_log(str(log_path), 10) == [
        'one', 'two', 'progress 1', 'progress 2', 'progress 3', 'three']
    assert tail_log('/nonexistent', 3) == []
    assert tail_log(str(log_path), 0) == []
