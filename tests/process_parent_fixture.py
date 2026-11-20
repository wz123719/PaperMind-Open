"""Disposable Worker-like owner for external force-kill tests."""
import json
import sys
from backend.parse_subprocess import run_conversion

run_conversion(json.loads(sys.argv[1]),lambda data:None,timeout=100,
    command=[sys.executable,'-u','-m','tests.process_child_fixture'])
