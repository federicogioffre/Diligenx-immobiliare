"""Isolated job executable. Exit 75 marks a transient ingestion failure."""
import argparse
import ctypes
import logging
import os
import signal
import sys
import threading
import time


def _hard_exit(signum=None, frame=None) -> None:
    if os.name == "posix" and os.getpgrp() == os.getpid():
        os.killpg(os.getpgrp(), signal.SIGKILL)
    os._exit(124)


def _install_process_guards(parent_pid: int | None, deadline: float | None) -> None:
    """Bound child lifetime even if its Arq parent dies or loses Redis.

    Linux deployments bind child death to parent death in the kernel. The
    parent PID recheck closes the race where it dies before prctl is installed.
    The absolute deadline is passed by Arq before spawning/importing anything.
    """
    if parent_pid is not None and sys.platform.startswith("linux"):
        libc = ctypes.CDLL(None, use_errno=True)
        if libc.prctl(1, signal.SIGKILL, 0, 0, 0) != 0:  # PR_SET_PDEATHSIG
            raise OSError(ctypes.get_errno(), "Unable to bind job process lifetime to worker")
        if os.getppid() != parent_pid:
            _hard_exit()
    if deadline is None:
        return
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        _hard_exit()
    if os.name == "posix":
        signal.signal(signal.SIGALRM, _hard_exit)
        signal.setitimer(signal.ITIMER_REAL, remaining)
    else:
        timer = threading.Timer(remaining, _hard_exit)
        timer.daemon = True
        timer.start()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("kind", choices=("analysis", "ingestion"))
    parser.add_argument("entity_id", type=int)
    parser.add_argument("user_id", type=int)
    parser.add_argument("--parent-pid", type=int)
    parser.add_argument("--deadline", type=float)
    args = parser.parse_args()
    _install_process_guards(args.parent_pid, args.deadline)
    from app.worker import _is_transient, _run_ingestion, _run_pipeline

    function = _run_pipeline if args.kind == "analysis" else _run_ingestion
    try:
        function(args.entity_id, args.user_id)
    except Exception as exc:
        logging.getLogger(__name__).exception("%s job %d failed", args.kind, args.entity_id)
        return 75 if _is_transient(exc) else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
