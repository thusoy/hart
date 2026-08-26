'''
Create multiple minions in parallel.

Each minion gets its full creation log written to a separate log file, while
the terminal shows each minion's state as it transitions from creating
(waiting for the provider) to running (node is up, bootstrapping salt) to
connected (verified reachable through salt). When the terminal has room the
last few lines of each minion's log are shown below its status line.
'''

import datetime
import os
import shutil
import sys
import tempfile
import threading
import time
import traceback

from .minions import (
    connect_minion,
    create_node,
    destroy_node,
    disconnect_minion,
)
from .utils import log_error

MAX_LOG_TAIL_LINES = 10
RENDER_INTERVAL_SECONDS = 1

STATE_CREATING = 'creating'
STATE_RUNNING = 'running'
STATE_CONNECTED = 'connected'
STATE_FAILED = 'failed'


def create_minions_in_parallel(specs, create_and_connect=None):
    '''
    Create all the minions given by the list of create_minion kwarg specs.
    Returns the jobs that failed, ie an empty list if everything succeeded.
    '''
    if create_and_connect is None:
        create_and_connect = create_and_connect_minion

    jobs = [MinionCreationJob(spec, create_and_connect) for spec in specs]

    stdout_mux = ThreadOutputMultiplexer(sys.stdout)
    stderr_mux = ThreadOutputMultiplexer(sys.stderr)
    sys.stdout = stdout_mux
    sys.stderr = stderr_mux
    try:
        for job in jobs:
            job.thread = threading.Thread(target=job.run_with_log,
                args=(stdout_mux, stderr_mux), name=job.minion_id)
            job.thread.start()
        try:
            watch_jobs(jobs, stdout_mux.fallback)
        except KeyboardInterrupt:
            stdout_mux.fallback.write('\nGot interrupt, but minion creation '
                'cannot be aborted safely, waiting for the minions to finish\n')
            for job in jobs:
                job.thread.join()
    finally:
        sys.stdout = stdout_mux.fallback
        sys.stderr = stderr_mux.fallback

    failed = [job for job in jobs if job.state != STATE_CONNECTED]
    print('\n%d/%d minions created successfully' % (
        len(jobs) - len(failed), len(jobs)))
    for job in jobs:
        print('%s: %s (full log: %s)' % (
            job.minion_id, job.describe_state(), job.log_path))
    return failed


class MinionCreationJob:
    def __init__(self, spec, create_and_connect):
        self.spec = dict(spec)
        self.minion_id = self.spec['minion_id']
        self.create_and_connect = create_and_connect
        self.state = STATE_CREATING
        self.error = None
        self.thread = None
        timestamp = datetime.datetime.now().strftime('%Y-%m-%dT%H-%M-%S')
        self.log_path = os.path.join(tempfile.gettempdir(),
            'hart-%s-%s.log' % (self.minion_id, timestamp))

    def describe_state(self):
        if self.error:
            return '%s (%s)' % (self.state, self.error)
        return self.state

    def run_with_log(self, stdout_mux, stderr_mux):
        # Line buffered so the log can be tailed while the job is running
        with open(self.log_path, 'w', buffering=1) as log_fh:
            stdout_mux.register_current_thread(log_fh)
            stderr_mux.register_current_thread(log_fh)
            try:
                self.create_and_connect(self)
                self.state = STATE_CONNECTED
            except BaseException as error:
                traceback.print_exc()
                self.error = str(error) or error.__class__.__name__
                self.state = STATE_FAILED


def create_and_connect_minion(job):
    kwargs = dict(job.spec)
    script = kwargs.pop('script', None)
    hart_node = create_node(non_interactive=True, **kwargs)
    if hart_node is None:
        raise ValueError('a minion with this id already exists')
    job.state = STATE_RUNNING
    try:
        connect_minion(hart_node, script)
    except BaseException:
        log_error('Destroying node since it failed to connect')
        destroy_node(hart_node)
        disconnect_minion(job.minion_id)
        raise


class ThreadOutputMultiplexer:
    '''
    A sys.stdout/stderr replacement that routes output from registered
    threads to their own file, keeping the original stream for all other
    threads (like the main thread).
    '''
    def __init__(self, fallback):
        self.fallback = fallback
        self.targets = {}

    def register_current_thread(self, target):
        self.targets[threading.get_ident()] = target

    def _get_target(self):
        return self.targets.get(threading.get_ident(), self.fallback)

    def write(self, data):
        return self._get_target().write(data)

    def flush(self):
        self._get_target().flush()

    def isatty(self):
        target = self._get_target()
        return target is self.fallback and target.isatty()


def watch_jobs(jobs, out):
    is_tty = out.isatty()
    reported_states = {}
    rendered_lines = 0
    while True:
        still_running = any(job.thread.is_alive() for job in jobs)
        if is_tty:
            rendered_lines = render_job_status(jobs, out, rendered_lines)
        else:
            for job in jobs:
                if reported_states.get(job.minion_id) != job.state:
                    reported_states[job.minion_id] = job.state
                    out.write('%s: %s\n' % (job.minion_id, job.describe_state()))
                    out.flush()
        if not still_running:
            return
        time.sleep(RENDER_INTERVAL_SECONDS)


def render_job_status(jobs, out, previous_render_lines):
    size = shutil.get_terminal_size()
    # Show as much of each minion's log as there's room for, up to the max
    tail_lines = min(MAX_LOG_TAIL_LINES, max(0, (size.lines - 1) // len(jobs) - 1))
    lines = []
    for job in jobs:
        lines.append('%s: %s' % (job.minion_id, job.describe_state()))
        for log_line in tail_log(job.log_path, tail_lines):
            lines.append('    %s' % log_line)
    if previous_render_lines:
        # Move the cursor back up to the start of the previous render and
        # clear the rest of the screen before re-rendering
        out.write('\x1b[%dF\x1b[0J' % previous_render_lines)
    for line in lines:
        out.write(line[:size.columns - 1])
        out.write('\n')
    out.flush()
    return len(lines)


def tail_log(log_path, max_lines):
    if not max_lines:
        return []
    try:
        with open(log_path) as fh:
            lines = fh.readlines()
    except OSError:
        return []
    cleaned = []
    # Progress lines using \r are already split into separate lines by
    # universal newline handling, so the tail shows the latest update
    for line in lines:
        line = line.rstrip()
        if line:
            cleaned.append(line)
    return cleaned[-max_lines:]
