#!/usr/bin/env python3

import argparse
import json
from pathlib import Path

DEFAULT_FIELDS = ["time", "pkts-in-l", "step-mark", "drops", "qlen", "maxq"]

# Docs for fields (from https://github.com/torvalds/linux/blob/8fde5d1d47f69db6082dfa34500c27f8485389a5/tools/include/uapi/linux/pkt_sched.h#L33-L43):
#   bytes: Number of enqueued bytes
#   packets: Number of enqueued packets
#   drops: Packets dropped because of lack of resources
#   overlimits: Number of throttle events when this flow goes out of allocated bandwidth
#   qlen: Queue length
#   backlog: Backlog size of queue
# Docs for DualPI2-specific fields (from https://github.com/torvalds/linux/blob/8fde5d1d47f69db6082dfa34500c27f8485389a5/include/uapi/linux/pkt_sched.h#L1268-L1281):
#   prob: Current base PI probability
#   delay-c: Current C-queue delay in microseconds
#   delay-l: Current L-queue delay in microseconds
#   pkts-in-c: Number of packets enqueued in the C-queue
#   pkts-in-l: Number of packets enqueued in the L-queue
#   maxq: Maximum number of packets seen by the DualPI2
#   ecn-mark: All packets marked with ECN
#   step-mark: Only packets marked with ECN due to L-queue step AQM
#   credit: Current c_protection credit
#   memory-used: Memory used by both queues
#   max-memory-used: Maximum used memory
#   memory-limit: Memory limit of both queues


def process_queues(
    file: str | Path, kind: str = "dualpi2", fields: list[str] = DEFAULT_FIELDS
) -> list[dict]:
    path = Path(file)
    with path.open(mode="r", encoding="utf-8") as f:
        objs = [json.loads(line) for line in f if line.strip()]

    effective_fields = ["time"] + [field for field in fields if field != "time"]

    try:
        flattened = [
            {
                "time": obj["time"],
                **next((queue for queue in obj["queues"] if queue["kind"] == kind)),
            }
            for obj in objs
        ]
    except StopIteration:
        raise ValueError(f"No queue of kind '{kind}' found in the input data.")

    filtered = [
        {field: flattened_obj.get(field, 0) for field in effective_fields}
        for flattened_obj in flattened
    ]

    gradients = [{**filtered[0], "time": 0}] + [
        {
            k: v2 - v1
            for k, v1, v2 in zip(prev_obj.keys(), prev_obj.values(), obj.values())
        }
        for prev_obj, obj in zip(filtered, filtered[1:])
    ]

    time_converted = [{**obj, "time": obj["time"] / 1e6} for obj in gradients]  # Convert time from nanoseconds to milliseconds

    return time_converted


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Process queue statistics from a JSONL file and emit the aggregated output as a single JSON."
    )
    parser.add_argument(
        "input",
        nargs="?",
        default="queues.jsonl",
        help="Input JSONL file with queue statistics.",
    )
    parser.add_argument(
        "-k",
        "--kind",
        default="dualpi2",
        help="Queue kind to select from each JSON object.",
    )
    parser.add_argument(
        "--fields",
        nargs="+",
        default=DEFAULT_FIELDS,
        help="Fields to include in the output. Time is always included. Possible values: Possible values: bytes, packets, drops, overlimits, requeues, backlog, qlen, prob, delay-c, delay-l, pkts-in-c, pkts-in-l, maxq, ecn-mark, step-mark, credit, memory-used, max-memory-used, memory-limit.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        logs = process_queues(args.input, kind=args.kind, fields=args.fields)
        print(json.dumps(logs))
    except Exception as e:
        print(f"Error processing queues: {e}")


if __name__ == "__main__":
    main()
