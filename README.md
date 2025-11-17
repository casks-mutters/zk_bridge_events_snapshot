# README.md
# zk_bridge_events_snapshot

## Overview
zk_bridge_events_snapshot is a small command-line tool that connects to an EVM-compatible network via web3.py and takes a snapshot of logs emitted by a bridge, rollup, or generic messaging contract. It is oriented toward zero-knowledge and soundness applications, where a deterministic commitment over L1 events is required.

The script:
- Connects to an RPC endpoint
- Scans a configurable range of blocks for logs from a given contract
- Optionally filters logs by a topic0 (event signature hash)
- Collects block, transaction, and topic data for each log
- Sorts the logs deterministically and computes a Keccak-256 commitment over them
- Outputs a JSON payload that can be used as a public input to ZK or soundness circuits, such as in Aztec-style rollups, Zama experiments, or other L1↔L2 verification flows

## Files
This repository contains exactly two files:
1. app.py — the main script implementing the snapshot and commitment logic.
2. README.md — this documentation file.

## Requirements
- Python 3.10 or newer
- A working EVM-compatible JSON-RPC endpoint (Ethereum, Polygon, Optimism, Arbitrum, Base, etc.)
- Internet access to reach the RPC endpoint
- Installed Python package:
  - web3

## Installation
1) Install Python 3.10 or newer.

2) Install the dependency:
   pip install web3

3) Configure an RPC endpoint:
   Option A: set the environment variable RPC_URL, for example:
   export RPC_URL="https://mainnet.infura.io/v3/your_real_key"
   Option B: provide the RPC endpoint explicitly via the --rpc flag when running the script.

If RPC_URL is not set and the default URL still contains your_api_key, the script will warn you and will likely fail to connect until you provide a valid endpoint.

## Usage
Basic run with a bridge contract address, scanning recent blocks:
   python app.py 0xYourBridgeAddress

Specify an explicit RPC endpoint:
   python app.py 0xYourBridgeAddress --rpc https://your-rpc-url

Control the block window indirectly by number of recent blocks (when from/to are not set):
   python app.py 0xYourBridgeAddress --blocks 5000

Provide an explicit block range:
   python app.py 0xYourBridgeAddress --from-block 18000000 --to-block 18005000

Filter by topic0 (e.g., a particular event signature hash):
   python app.py 0xYourBridgeAddress --topic0 0x1234...abcd

Limit the maximum number of logs kept in the snapshot (0 means no limit):
   python app.py 0xYourBridgeAddress --max-logs 2000

Pretty-print the JSON output:
   python app.py 0xYourBridgeAddress --pretty

Disable human-readable summary (JSON-only output for scripts or ZK pipelines):
   python app.py 0xYourBridgeAddress --no-human

You can combine flags, for example:
   python app.py 0xYourBridgeAddress --rpc https://your-rpc --blocks 4000 --topic0 0x1234... --pretty

## Output Format
The script prints a single JSON object to stdout with the following high-level structure:

- mode: string, always "zk_bridge_events_snapshot"
- network: human-readable network name when available
- chainId: numeric chain ID
- bridgeAddress: normalized checksummed address of the contract
- generatedAtUtc: UTC timestamp of snapshot generation
- data:
  - meta:
    - fromBlockRequested: starting block requested by the user or derived from --blocks
    - toBlockRequested: ending block requested or derived
    - fromBlockEffective: smallest block number actually seen in logs
    - toBlockEffective: largest block number actually seen in logs
    - logCount: number of logs included in the snapshot
    - uniqueTxCount: number of distinct transactions that emitted those logs
    - maxLogs: maximum logs allowed (from configuration)
    - topic0Filter: topic0 string if a filter was used, otherwise null
    - elapsedSec: time spent fetching logs via RPC
    - commitmentKeccak: hex string, Keccak-256 over the deterministically serialized logs array
  - logs: array of log objects, each with:
    - blockNumber
    - transactionHash
    - logIndex
    - data (hex-encoded)
    - topics (array of hex-encoded topics)

The logs are sorted by (blockNumber, transactionHash, logIndex) before building the commitment and emitting JSON, ensuring deterministic output for the same underlying data and configuration.

## ZK / Aztec / Zama / Soundness Context
The goal of this tool is to provide a ZK-friendly snapshot of L1 bridge events:

- Deterministic ordering makes it easy to reproduce the commitmentKeccak given the same chain state and parameters.
- Minimal, generic structure means the output can be consumed by a variety of proving stacks (Plonk-like, STARKs, Aztec’s stack, Zama-style frameworks, and others).
- The commitmentKeccak can serve as a public input in a ZK circuit that enforces consistency between:
  - An L2 state transition
  - The actual L1 events emitted by a bridge or rollup contract

Example scenarios:
- An Aztec-style rollup circuit can take commitmentKeccak as a public input and prove that its internal message queue is consistent with the L1 bridge logs.
- Zama-based research or soundness experiments can use the snapshot to fix a particular window of L1 activity and study encrypted or ZK-based derivatives of those logs.
- Cross-domain soundness pipelines can store and compare commitments across time to detect inconsistencies or missing events.

## Notes and Limitations
- The script does not fetch storage or Merkle proofs. It only commits to raw logs (topics and data). For deeper integration, you may extend the script to fetch state roots or Merkle proofs separately.
- The trust model is that the RPC endpoint is honest about the logs. For strong guarantees, use your own node or multiple independent endpoints and cross-check results.
- Truncation via --max-logs is helpful for keeping JSON and commitments small but means that not all events in a given window are represented. For full coverage, increase or disable the limit.
- Topic filtering via --topic0 is optional. Without it, all logs from the contract address are included in the snapshot.
- The tool is focused on simplicity and deterministic behavior rather than maximum performance. For extremely large windows or mainnet archival workloads, consider batching or parallelization around this script.

## Expected Result
When you run the tool with a valid RPC endpoint and a bridge contract address, you should see:
- Logging on stderr describing network, block range, number of logs, and the final Keccak commitment.
- A JSON payload on stdout containing:
  - Metadata about the snapshot and commitment
  - The list of logs included in the commitment

This JSON can be stored, versioned, or passed directly into:
- ZK proof generators
- Aztec-like rollup tooling
- Zama or other cryptographic research frameworks
- Internal soundness-verification and audit pipelines that require a compact but precise description of L1 bridge activity.
