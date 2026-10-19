"""Run a three-company supply chain on this machine: Tier-2 → Tier-1 → OEM, without EDCs.

Each company gets its own mock DTR (``mock_participant.py``), its own app instance and database,
in development mode (``CXS_DEV_DIRECT``): partner twins are read straight from the partners'
mock registries and notifications are posted straight to the partners' apps. It shows the
application's behavior; it proves nothing about dataspace connectivity.

    cd web && npm run build && cd ../backend
    uv run python devtools/demo_network.py

Then open Tier-2 (cell maker), Tier-1 (module maker) and OEM side by side; Ctrl-C stops all.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
WEB_DIST = HERE.parent.parent / "web" / "dist"
API_KEY = "demo-network"

COMPANIES = {
    # key: (BPNL, name, app port, mock port)
    "tier2": ("BPNL000000000T2A", "Cell maker (Tier-2)", 8002, 8102),
    "tier1": ("BPNL000000000T1A", "Module maker (Tier-1)", 8001, 8101),
    "oem": ("BPNL000000000OEM", "Vehicle maker (OEM)", 8003, 8103),
}


def _env(key: str, data_dir: Path, host: str) -> dict[str, str]:
    bpnl, _, _, mock_port = COMPANIES[key]
    others = {k: v for k, v in COMPANIES.items() if k != key}
    env = {
        **os.environ,
        "CXS_OWN_BPNL": bpnl,
        "CXS_DATABASE_URL": f"sqlite:///{data_dir / key}.db",
        "CXS_DTR_BASE_URL": f"http://127.0.0.1:{mock_port}",
        "CXS_DEV_DIRECT": "true",
        "CXS_NOTIFICATION_API_KEY": API_KEY,
        "CXS_PARTNER_CONNECTORS": json.dumps(
            {b: f"http://127.0.0.1:{port}" for b, _, port, _ in others.values()}
        ),
        "CXS_DEV_PARTNER_DTRS": json.dumps(
            {b: f"http://127.0.0.1:{mport}/api/v3" for b, _, _, mport in others.values()}
        ),
        "CXS_SYNC_INTERVAL_SECONDS": "0",
        # No admin login in the demo, even if backend/.env sets one: the script names the
        # partners through the API.
        "CXS_ADMIN_PASSWORD_HASH": "",
    }
    if WEB_DIST.is_dir():
        env["CXS_WEB_DIST_DIR"] = str(WEB_DIST)
    return env


def _wait(url: str, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if requests.get(url, timeout=2).ok:
                return
        except requests.RequestException:
            pass
        time.sleep(0.3)
    raise SystemExit(f"{url} did not come up")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--host", default="127.0.0.1", help="interface the apps listen on")
    parser.add_argument("--data-dir", help="keep the databases here (default: a temp dir)")
    parser.add_argument(
        "--latency",
        type=float,
        default=0.0,
        help="seconds each mock registry takes to answer, to watch a partner sync run",
    )
    args = parser.parse_args()

    data_dir = Path(args.data_dir or tempfile.mkdtemp(prefix="cxs-demo-"))
    data_dir.mkdir(parents=True, exist_ok=True)
    if not WEB_DIST.is_dir():
        print(f"note: {WEB_DIST} not found — run `npm run build` in web/ to get the UI")

    processes: list[subprocess.Popen] = []
    try:
        for key, (_, _, port, mock_port) in COMPANIES.items():
            processes.append(
                subprocess.Popen(
                    [
                        sys.executable,
                        str(HERE / "mock_participant.py"),
                        "--port",
                        str(mock_port),
                        "--participant",
                        key,
                        "--latency",
                        str(args.latency),
                    ],
                    stdout=subprocess.DEVNULL,
                )
            )
            processes.append(
                subprocess.Popen(
                    [
                        sys.executable,
                        "-m",
                        "uvicorn",
                        "catenax_simplified.main:app",
                        "--host",
                        args.host,
                        "--port",
                        str(port),
                        "--log-level",
                        "warning",
                    ],
                    env=_env(key, data_dir, args.host),
                )
            )

        names = {bpnl: name for bpnl, name, _, _ in COMPANIES.values()}
        for _, (_, _, port, _) in COMPANIES.items():
            base = f"http://127.0.0.1:{port}"
            _wait(f"{base}/api/health")
            requests.post(f"{base}/api/sync", timeout=60).raise_for_status()
            # Partners come from the company's own BoM/usage data; give them readable names.
            for partner in requests.get(f"{base}/api/partners", timeout=10).json():
                requests.put(
                    f"{base}/api/partners/{partner['bpnl']}",
                    json={"name": names.get(partner["bpnl"])},
                    timeout=10,
                ).raise_for_status()
        # Partner twins after every company has synced its own.
        for _, (_, _, port, _) in COMPANIES.items():
            requests.post(f"http://127.0.0.1:{port}/api/partners/sync", timeout=60)

        print("\nDemo network running (development mode, no EDCs):\n")
        for _, (bpnl, name, port, _) in COMPANIES.items():
            print(f"  {name:24} {bpnl}  http://{args.host}:{port}/")
        print(f"\n  databases in {data_dir}\n  Ctrl-C stops everything.\n")
        while all(p.poll() is None for p in processes):
            time.sleep(1)
        print("a process exited; stopping")
    except KeyboardInterrupt:
        pass
    finally:
        for process in processes:
            process.terminate()
        for process in processes:
            process.wait(timeout=10)


if __name__ == "__main__":
    main()
