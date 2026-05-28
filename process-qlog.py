#!/usr/bin/env python3

import json
from typing import Iterable, Iterable

# SENT_PKTS=`sed 's/..(.*)/$1/' h1.qlog | jq -C 'select(.name == "transport:packet_sent") | {"time": .time, "pn": .data.header.packet_number, "length": .data.header.length}'`
# RCVD_PKTS=`sed 's/..(.*)/$1/' h2.qlog | jq -C 'select(.name == "transport:packet_received") | {"time": .time, "pn": .data.header.packet_number}' 2>/dev/null`


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
        if event.get("name") == "transport:packet_sent"
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
        if event.get("name") == "transport:packet_received"
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
            raise f"received packet that was never sent: {rcvd[j]}"
        elif j == len(rcvd):
            # print(f"packet was never received (i.e., it had been dropped): {sent[i]}")
            i += 1
        elif sent[i]["id"] < rcvd[j]["id"]:
            # print(f"packet was never received (i.e., it had been dropped): {sent[i]}")
            i += 1
        elif sent[i]["id"] > rcvd[j]["id"]:
            raise f"received packet that was never sent: {rcvd[j]}"
        else:
            connected.append((sent[i], rcvd[j]))
            i += 1
            j += 1
    return connected


def merge_pkt_event_pairs(pairs: list[tuple[dict, dict]]) -> list[dict]:
    return [
        {
            # "packet_type": send["id"][0],
            # "packet_number": send["id"][1],
            # "packet_length": send["length"],
            "time": recv["time"],
            "one_way_delay_ms": recv["time"] - send["time"],
        }
        for send, recv in pairs
    ]


if __name__ == "__main__":
    client_side = "h1.qlog"
    server_side = "h2.qlog"
    client = get_qlog_events(client_side)
    server = get_qlog_events(server_side)
    sent = get_pkt_sent_events(client)
    rcvd = get_pkt_rcvd_events(server)
    connected = get_connected_pkt_event_pairs(sent, rcvd)
    packets = merge_pkt_event_pairs(connected)
    # print(json.dumps(packets))
    for packet in packets:
        print(f"One-way Delay [ms]: {packet["one_way_delay_ms"]:.2f}")
