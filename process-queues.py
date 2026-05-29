#!/usr/bin/env python3

# {
#     "time": 1779997184620711242,
#     "queues": [
#         {
#             "kind": "dualpi2",
#             "handle": "20:",
#             "parent": "1:10",
#             "options": {},
#             "bytes": 836,
#             "packets": 10,
#             "drops": 0,
#             "overlimits": 0,
#             "requeues": 0,
#             "backlog": 0,
#             "qlen": 0,
#             "prob": 0,
#             "delay-c": 0,
#             "delay-l": 0,
#             "pkts-in-c": 9,
#             "pkts-in-l": 1,
#             "maxq": 0,
#             "ecn-mark": 0,
#             "step-mark": 0,
#             "credit": -121120,
#             "memory-used": 0,
#             "max-memory-used": 2304,
#             "memory-limit": 605600,
#         },
#     ],
# }

import json


def process_queues(file: str) -> list[dict]:
    with open(file, mode="r") as f:
        objs = [json.loads(line) for line in f.readlines()]

    flattened = [
        {
            "time": obj["time"],
            **next((queue for queue in obj["queues"] if queue["kind"] == "dualpi2")),
        }
        for obj in objs
    ]

    filtered = [
        {
            k: v
            for k, v in obj.items()
            if k in {"time", "pkts-in-l", "step-mark", "drops"}
        }
        for obj in flattened
    ]

    # taking the gradient of pkts-in-l, step-mark, and drops over `i`
    # note: we're filling in the missing point from derivation
    gradients = [{**filtered[0], "time": 0}] + [
        {
            k: v2 - v1
            for k, v1, v2 in zip(prev_obj.keys(), prev_obj.values(), obj.values())
        }
        for prev_obj, obj in zip(filtered, filtered[1:])
    ]

    time_converted = [{**obj, "time": obj["time"] / 1e9} for obj in gradients]

    return time_converted


if __name__ == "__main__":
    logs = process_queues("queues.jsonl")
    for log in logs:
        print(log)
