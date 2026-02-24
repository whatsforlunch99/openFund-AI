#!/usr/bin/env python3
"""Reproduce ACLMessage JSON serialization for persistence (D2)."""
import json
import os
from dataclasses import asdict

# Project root
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from a2a.acl_message import ACLMessage, Performative

LOG_PATH = os.path.join(os.path.dirname(__file__), "..", ".cursor", "debug-d6550e.log")

def log(hypothesis_id: str, message: str, data: dict, run_id: str = "initial") -> None:
    import time
    # Keep data JSON-serializable (strings, ints, lists of strings)
    payload = {
        "sessionId": "d6550e",
        "runId": run_id,
        "hypothesisId": hypothesis_id,
        "location": "repro_acl_json_serialize.py",
        "message": message,
        "data": {k: str(v) for k, v in data.items()},
        "timestamp": int(time.time() * 1000),
    }
    with open(LOG_PATH, "a") as f:
        f.write(json.dumps(payload) + "\n")

def main() -> None:
    msg = ACLMessage(
        performative=Performative.INFORM,
        sender="responder",
        receiver="api",
        content={"final_response": "test"},
    )
    # H1/H2: type of performative and whether asdict preserves it as enum
    log("H1", "Before asdict", {"performative_type": type(msg.performative).__name__, "performative_value": str(msg.performative)})
    d = asdict(msg)
    log("H2", "After asdict", {"performative_type": type(d.get("performative")).__name__, "keys": list(d.keys())})
    # H3/H4: attempt json.dumps
    try:
        out = json.dumps(d)
        log("H3", "json.dumps succeeded", {"output_len": len(out)})
    except Exception as e:
        log("H4", "json.dumps failed", {"exception_type": type(e).__name__, "exception_msg": str(e)})
    # H5: check timestamp type (datetime not JSON-serializable by default)
    log("H5", "timestamp in dict", {"timestamp_type": type(d.get("timestamp")).__name__})

    # Post-fix: use to_dict() for JSON persistence (D2)
    safe = msg.to_dict()
    try:
        out = json.dumps(safe)
        log("post-fix", "json.dumps(to_dict()) succeeded", {"output_len": len(out)}, run_id="post-fix")
    except Exception as e:
        log("post-fix", "json.dumps(to_dict()) failed", {"exception_type": type(e).__name__, "exception_msg": str(e)}, run_id="post-fix")

if __name__ == "__main__":
    main()
