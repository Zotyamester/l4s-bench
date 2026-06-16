#!/usr/bin/env python3

import json
import argparse
from typing import Iterable


def get_qlog_events(qlog: str) -> Iterable[dict]:
    with open(qlog, mode="r") as file:
        for line in file:
            try:
                event = json.loads(line.strip())
                yield event
            except:
                return


def get_pkt_sent_events(events: Iterable[dict]) -> Iterable[dict]:
    return (
        {
            "time": event["time"],
            "id": (
                event["data"]["header"]["packet_type"],
                event["data"]["header"]["packet_number"],
            ),
            "length": event["data"]["header"]["length"],
        }
        for event in events
        if event.get("name") == "quic:packet_sent"
    )


def get_pkt_rcvd_events(events: Iterable[dict]) -> Iterable[dict]:
    return (
        {
            "time": event["time"],
            "id": (
                event["data"]["header"]["packet_type"],
                event["data"]["header"]["packet_number"],
            ),
        }
        for event in events
        if event.get("name") == "quic:packet_received"
    )


def get_connected_pkt_event_pairs(
    sent: Iterable[dict], rcvd: Iterable[dict]
) -> list[tuple[dict, dict]]:
    sent = sorted(sent, key=lambda event: event["id"])
    rcvd = sorted(rcvd, key=lambda event: event["id"])
    connected = []
    i = 0
    j = 0
    while i < len(sent) or j < len(rcvd):
        if i == len(sent):
            raise Exception(f"received packet that was never sent: {rcvd[j]}")
        elif j == len(rcvd):
            # print(f"packet was never received (i.e., it had been dropped): {sent[i]}")
            i += 1
        elif sent[i]["id"] < rcvd[j]["id"]:
            # print(f"packet was never received (i.e., it had been dropped): {sent[i]}")
            i += 1
        elif sent[i]["id"] > rcvd[j]["id"]:
            raise Exception(f"received packet that was never sent: {rcvd[j]}")
        else:
            connected.append((sent[i], rcvd[j]))
            i += 1
            j += 1
    return connected


def merge_pkt_event_pairs(pairs: list[tuple[dict, dict]]) -> list[dict]:
    return [
        {
            "time": recv["time"],
            "packet_type": send["id"][0],
            "packet_number": send["id"][1],
            "packet_length": send["length"],
            "one_way_delay_ms": recv["time"] - send["time"],
        }
        for send, recv in pairs
    ]


def estimate_bandwidth(packets: list[dict]) -> float:
    total_bytes = sum(packet["packet_length"] for packet in packets)
    total_time_ms = max(packet["time"] for packet in packets) - min(
        packet["time"] for packet in packets
    )
    if total_time_ms == 0:
        return float("inf")
    return (total_bytes * 8) / (total_time_ms / 1000)  # bits per second


def main():
    parser = argparse.ArgumentParser(
        description="Process QLOG files to calculate one-way delays between sent and received packets"
    )
    parser.add_argument(
        "--client",
        default="h1.qlog",
        help="Path to client-side QLOG file (default: h1.qlog)",
    )
    parser.add_argument(
        "--server",
        default="h2.qlog",
        help="Path to server-side QLOG file (default: h2.qlog)",
    )
    args = parser.parse_args()

    client_side = args.client
    server_side = args.server
    client = get_qlog_events(client_side)
    server = get_qlog_events(server_side)
    sent = get_pkt_sent_events(client)
    rcvd = get_pkt_rcvd_events(server)
    connected = get_connected_pkt_event_pairs(sent, rcvd)
    packets = merge_pkt_event_pairs(connected)
    bandwidth = estimate_bandwidth(packets)
    result = {
        "estimated_bandwidth_bps": bandwidth,
        "packets": packets,
    }
    print(json.dumps(result))


if __name__ == "__main__":
    main()
