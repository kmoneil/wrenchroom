"""OCCT's thread pool as the suite sets it: tests/conftest.py's ``pytest_configure``.

The pool's size is fixed by whoever asks for it first. Were a module to ask before
the suite does, a parallel lane would go back to every worker running every boolean
on every core, slower by half and with nothing failing. So the size is a test.
"""

import os

from OCP.OSD import OSD_Parallel, OSD_ThreadPool


def test_occt_s_pool_is_one_thread_to_a_worker_and_every_core_s_in_one_process():
    threads = OSD_ThreadPool.DefaultPool_s().NbThreads()
    if os.environ.get("PYTEST_XDIST_WORKER"):
        assert threads == 1
    else:
        assert threads == OSD_Parallel.NbLogicalProcessors_s()
