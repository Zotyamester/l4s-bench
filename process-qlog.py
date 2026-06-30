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


def proc_pkt_sent_events(events: Iterable[dict]) -> Iterable[dict]:
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
        if event.get("name") == "quic:packet_sent"  # for sanitization
    )


def proc_pkt_rcvd_events(events: Iterable[dict]) -> Iterable[dict]:
    return (
        {
            "time": event["time"],
            "id": (
                event["data"]["header"]["packet_type"],
                event["data"]["header"]["packet_number"],
            ),
        }
        for event in events
        if event.get("name") == "quic:packet_received"  # for sanitization
    )


def proc_cwnd_events(events: Iterable[dict]) -> Iterable[dict]:
    return (
        {
            "time": event["time"],
            "cwnd": event["data"]["congestion_window"],
        }
        for event in events
        if event.get("name") == "quic:recovery_metrics_updated"  # for sanitization
        and "congestion_window" in event["data"]
    )


def proc_cca_state_events(events: Iterable[dict]) -> Iterable[dict]:
    states = [{"time": 0.0, "state": "SS"}]

    for event in events:
        current_state = states[-1]["state"]
        if (name := event.get("name")) == "quic:recovery_metrics_updated":
            cwnd = event["data"].get("congestion_window")
            ssthresh = event["data"].get("ssthresh")

            if cwnd is None or ssthresh is None:
                continue

            if cwnd < ssthresh:
                # A NewReno sender is in slow start any time the congestion
                # window is below the slow start threshold.
                if current_state != "SS":
                    states.append({"time": event["time"], "state": "SS"})
            else:
                # A NewReno sender is in congestion avoidance any time the
                # congestion window is at or above the slow start threshold and
                # not in a recovery period.
                if current_state != "RECOV" and current_state != "CA":
                    states.append({"time": event["time"], "state": "CA"})
        elif name == "quic:congestion_state_updated":
            # A NewReno sender enters a recovery period when it detects the
            # loss of a packet or when the ECN-CE count reported by its peer
            # increases.  A sender that is already in a recovery period stays
            # in it and does not reenter it.
            if current_state != "RECOV":
                states.append({"time": event["time"], "state": "RECOV"})

    return states


def proc_rtt_events(events: Iterable[dict]) -> Iterable[dict]:
    return (
        {
            "time": event["time"],
            "rtt": event["data"]["latest_rtt"],
        }
        for event in events
        if event.get("name") == "quic:recovery_metrics_updated"  # for sanitization
        and "latest_rtt" in event["data"]
    )

def proc_ecn_events(events: Iterable[dict]) -> Iterable[dict]:
    return (
        {
            "time": event["time"],
            "congestion_experienced": description[1].split(",")[2].split("=")[1],
        }
        for event in events
        if event.get("name") == "quic:congestion_state_updated"  # for sanitization
        and (description := event["data"]["new"].split(":"))
        and description[0] == "ECN"
    )


def proc_loss_events(events: Iterable[dict]) -> Iterable[dict]:
    return (
        {
            "time": event["time"],
            "loss": description[1].split("=")[1],
        }
        for event in events
        if event.get("name") == "quic:congestion_state_updated"  # for sanitization
        and (description := event["data"]["new"].split(":"))
        and description[0] == "LOSS"
    )


def connect_pkt_event_pairs(
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
            # raise Exception(f"received packet that was never sent: {rcvd[j]}")
            j += 1
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
    client_events = list(get_qlog_events(client_side))
    server_events = list(get_qlog_events(server_side))

    sent_events = []
    cwnd_events = []
    cong_events = []
    rcvd_events = []
    for event in client_events:
        if (name := event.get("name")) == "quic:packet_sent":
            sent_events.append(event)
        elif name == "quic:recovery_metrics_updated":
            cwnd_events.append(event)
        elif name == "quic:congestion_state_updated":
            cong_events.append(event)
    for event in server_events:
        if (name := event.get("name")) == "quic:packet_received":
            rcvd_events.append(event)
    sent = proc_pkt_sent_events(sent_events)
    rcvd = proc_pkt_rcvd_events(rcvd_events)
    cwnds = proc_cwnd_events(cwnd_events)
    rtts = proc_rtt_events(cwnd_events)
    ecns = proc_ecn_events(cong_events)
    losses = proc_loss_events(cong_events)
    cca = proc_cca_state_events(client_events)

    connected = connect_pkt_event_pairs(sent, rcvd)
    packets = merge_pkt_event_pairs(connected)
    result = {
        "packets": list(packets),
        "rtts": list(rtts),
        "cwnds": list(cwnds),
        "ecns": list(ecns),
        "losses": list(losses),
        "cca": list(cca),
    }
    print(json.dumps(result))


if __name__ == "__main__":
    main()
