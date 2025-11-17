# app.py
"""
zk_bridge_events_snapshot: L1 bridge event snapshot + commitment for ZK / soundness systems.

This script:
  - Connects to an EVM-compatible network via web3.py
  - Scans logs for a given bridge / rollup / messaging contract
  - Optionally filters by a specific topic0 (event signature hash)
  - Builds a deterministic JSON snapshot and a Keccak commitment over all logs

Intended use:
  - Aztec-style rollup bridge monitoring
  - Zama / ZK research experiments on L1↔L2 messaging soundness
  - General soundness verifiers that want a compact commitment to L1 events
"""

import os
import sys
import json
import time
import argparse
from typing import List, Dict, Any
from web3 import Web3

DEFAULT_RPC = os.getenv("RPC_URL", "https://mainnet.infura.io/v3/your_api_key")
DEFAULT_BLOCKS = int(os.getenv("BRIDGE_SNAPSHOT_BLOCKS", "2000"))
DEFAULT_MAX_LOGS = int(os.getenv("BRIDGE_SNAPSHOT_MAX_LOGS", "5000"))

NETWORKS: Dict[int, str] = {
    1: "Ethereum Mainnet",
    11155111: "Sepolia Testnet",
    10: "Optimism",
    137: "Polygon",
    42161: "Arbitrum One",
    8453: "Base",
}


def network_name(cid: int) -> str:
    return NETWORKS.get(cid, f"Unknown (chain ID {cid})")


def connect(rpc: str) -> Web3:
    start = time.time()
    w3 = Web3(Web3.HTTPProvider(rpc, request_kwargs={"timeout": 25}))

    if not w3.is_connected():
        print(f"❌ Failed to connect to RPC endpoint: {rpc}", file=sys.stderr)
        sys.exit(1)

    latency = time.time() - start
    try:
        cid = int(w3.eth.chain_id)
        tip = int(w3.eth.block_number)
        print(
            f"🌐 Connected to {network_name(cid)} (chainId {cid}, tip={tip}) in {latency:.2f}s",
            file=sys.stderr,
        )
    except Exception:
        print(f"🌐 Connected to RPC (chain info unavailable) in {latency:.2f}s", file=sys.stderr)

    return w3


def normalize_address(addr: str) -> str:
    try:
        return Web3.to_checksum_address(addr.strip())
    except Exception:
        raise ValueError(f"Invalid address: {addr!r}")


def hex_or_none(value: Any) -> str | None:
    if value is None:
        return None
    try:
        return Web3.to_hex(value)
    except Exception:
        return None


def fetch_logs(
    w3: Web3,
    address: str,
    from_block: int,
    to_block: int,
    topic0: str | None,
    max_logs: int,
) -> Dict[str, Any]:
    if from_block > to_block:
        from_block, to_block = to_block, from_block

    addr = normalize_address(address)
    latest = int(w3.eth.block_number)
    to_block = min(to_block, latest)

    print(
        f"🔍 Fetching logs for {addr} from block {from_block} to {to_block}...",
        file=sys.stderr,
    )

    topics = None
    if topic0:
        t0 = topic0.strip()
        if not t0.startswith("0x") or len(t0) != 66:
            print("⚠️  topic0 does not look like a 32-byte hex value; continuing anyway.", file=sys.stderr)
        topics = [t0]

    params: Dict[str, Any] = {
        "fromBlock": from_block,
        "toBlock": to_block,
        "address": addr,
    }
    if topics is not None:
        params["topics"] = [topics[0]]

    t0 = time.time()
    try:
        logs_raw = w3.eth.get_logs(params)
    except Exception as e:
        print(f"❌ Failed to fetch logs: {e}", file=sys.stderr)
        sys.exit(1)

    elapsed = time.time() - t0
    print(f"📦 RPC returned {len(logs_raw)} logs in {elapsed:.2f}s", file=sys.stderr)

    if max_logs > 0 and len(logs_raw) > max_logs:
        print(
            f"⚠️  Truncating logs from {len(logs_raw)} to max_logs={max_logs} for commitment.",
            file=sys.stderr,
        )
        logs_raw = logs_raw[:max_logs]

    logs: List[Dict[str, Any]] = []
    tx_set: set[str] = set()
    min_block_seen = None
    max_block_seen = None

    for lg in logs_raw:
        bn = int(lg["blockNumber"])
        txh = Web3.to_hex(lg["transactionHash"])
        idx = int(lg["logIndex"])
        data_hex = Web3.to_hex(lg["data"])
        topics_hex = [Web3.to_hex(t) for t in lg["topics"]]

        tx_set.add(txh)
        if min_block_seen is None or bn < min_block_seen:
            min_block_seen = bn
        if max_block_seen is None or bn > max_block_seen:
            max_block_seen = bn

        logs.append(
            {
                "blockNumber": bn,
                "transactionHash": txh,
                "logIndex": idx,
                "data": data_hex,
                "topics": topics_hex,
            }
        )

    logs.sort(key=lambda x: (x["blockNumber"], x["transactionHash"], x["logIndex"]))

    encoded = json.dumps(logs, sort_keys=True, separators=(",", ":")).encode()
    commitment = Web3.keccak(encoded).hex()

    meta = {
        "fromBlockRequested": from_block,
        "toBlockRequested": to_block,
        "fromBlockEffective": min_block_seen if min_block_seen is not None else from_block,
        "toBlockEffective": max_block_seen if max_block_seen is not None else to_block,
        "logCount": len(logs),
        "uniqueTxCount": len(tx_set),
        "maxLogs": max_logs,
        "topic0Filter": topic0,
        "elapsedSec": round(elapsed, 3),
        "commitmentKeccak": commitment,
    }

    return {
        "meta": meta,
        "logs": logs,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Snapshot L1 bridge/rollup events into a ZK-friendly commitment.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "address",
        help="Bridge / rollup / messaging contract address.",
    )
    parser.add_argument(
        "--rpc",
        default=DEFAULT_RPC,
        help="RPC URL (default from RPC_URL env).",
    )
    parser.add_argument(
        "--from-block",
        type=int,
        help="Start block number (default: tip - BRIDGE_SNAPSHOT_BLOCKS).",
    )
    parser.add_argument(
        "--to-block",
        type=int,
        help="End block number (default: latest block).",
    )
    parser.add_argument(
        "--blocks",
        type=int,
        default=DEFAULT_BLOCKS,
        help="Number of recent blocks to cover if from/to not set.",
    )
    parser.add_argument(
        "--topic0",
        help="Optional topic0 (event signature hash) to filter logs.",
    )
    parser.add_argument(
        "--max-logs",
        type=int,
        default=DEFAULT_MAX_LOGS,
        help="Maximum logs to keep in snapshot (0 = no limit).",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print JSON instead of compact JSON.",
    )
    parser.add_argument(
        "--no-human",
        action="store_true",
        help="Disable human-readable summary (JSON only).",
    )
    return parser.parse_args()


def main() -> None:
    if "your_api_key" in DEFAULT_RPC:
        print(
            "⚠️  RPC_URL is not set and DEFAULT_RPC still uses a placeholder key. "
            "Set RPC_URL or pass --rpc.",
            file=sys.stderr,
        )

    args = parse_args()

    if args.blocks <= 0:
        print("❌ --blocks must be > 0", file=sys.stderr)
        sys.exit(1)

    w3 = connect(args.rpc)
    tip = int(w3.eth.block_number)

    if args.from_block is None and args.to_block is None:
        to_block = tip
        from_block = max(0, tip - args.blocks + 1)
    else:
        to_block = args.to_block if args.to_block is not None else tip
        from_block = args.from_block if args.from_block is not None else max(
            0, to_block - args.blocks + 1
        )

    print(
        f"📅 zk_bridge_events_snapshot at UTC {time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime())}",
        file=sys.stderr,
    )
    print(
        f"🔗 Using RPC endpoint: {args.rpc}",
        file=sys.stderr,
    )
    print(
        f"📚 Block range resolved to [{from_block}, {to_block}] (tip={tip})",
        file=sys.stderr,
    )

    t0 = time.time()
    snapshot = fetch_logs(
        w3=w3,
        address=args.address,
        from_block=int(from_block),
        to_block=int(to_block),
        topic0=args.topic0,
        max_logs=int(args.max_logs),
    )
    elapsed_total = time.time() - t0

    chain_id = int(w3.eth.chain_id)
    payload = {
        "mode": "zk_bridge_events_snapshot",
        "network": network_name(chain_id),
        "chainId": chain_id,
        "bridgeAddress": normalize_address(args.address),
        "generatedAtUtc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
        "data": snapshot,
    }

    if not args.no_human:
        meta = snapshot["meta"]
        print(
            f"🌐 {payload['network']} (chainId {payload['chainId']}) "
            f"bridge={payload['bridgeAddress']}",
            file=sys.stderr,
        )
        print(
            f"📦 Logs: {meta['logCount']} (unique tx={meta['uniqueTxCount']}) "
            f"blocks [{meta['fromBlockEffective']}, {meta['toBlockEffective']}] "
            f"commitment={meta['commitmentKeccak']}",
            file=sys.stderr,
        )
        print(
            f"⏱️  Total elapsed: {elapsed_total:.2f}s",
            file=sys.stderr,
        )
        print(
            "ℹ️  The commitmentKeccak can be used as a public input in Aztec/Zama-style "
            "ZK or soundness circuits to bind L2 logic to specific L1 bridge events.",
            file=sys.stderr,
        )

    if args.pretty:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(json.dumps(payload, separators=(",", ":"), sort_keys=True))


if __name__ == "__main__":
    main()
