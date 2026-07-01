#!/usr/bin/env python3

import matplotlib.pyplot as plt
import json
import sys


def calculate_throughput_windows(packets: list[dict], time_window_ms: float) -> list[float]:
    tputs = []

    window_start = 0
    window_byte_sum = 0
    window_end = 0
    while window_end < len(packets):
        window_byte_sum += packets[window_end]["packet_length"]
        while window_start < window_end and packets[window_end]["time"] - packets[window_start]["time"] > time_window_ms:
            window_byte_sum -= packets[window_start]["packet_length"]
            window_start += 1
        tput = window_byte_sum * 8 / (time_window_ms / 1000)
        tputs.append(tput)
        window_end += 1

    return tputs


def plot_qlog_rtt_cwnd(endpoint_files: list[tuple[str, str]], queue_files: list[tuple[str, str]], queue_length_factor: float, bandwidth: int, round_trip_time: int, output_file: str):
    fig, ax = plt.subplots(7, 1, figsize=(30, 18), sharex=True)

    rtt_values = []

    for json_file, label in endpoint_files:
        with open(json_file, "r") as f:
            data = json.load(f)

        time, owd = zip(*((obj["time"], obj["one_way_delay_ms"]) for obj in data["packets"] if obj["packet_type"] == "1RTT"))
        ax[0].plot(time, owd, label=label)

        time, rtt = zip(*((obj["time"], obj["rtt"]) for obj in data["rtts"]))
        rtt_values.extend(rtt)

        ax[1].plot(time, rtt, label=label)

        time, cwnd = zip(*((obj["time"], obj["cwnd"])
                         for obj in data["cwnds"]))

        ax[2].plot(time, cwnd, label=label)

        if len(data["ecns"]) > 0:
            time, ecns = zip(*((obj["time"], obj["congestion_experienced"])
                             for obj in data["ecns"]))

            ax[4].scatter(time, ecns, label=label, s=10)
        else:
            ax[4].scatter([0], [0], label=label, s=10)

        if len(data["losses"]) > 0:
            time, losses = zip(*((obj["time"], obj["loss"])
                             for obj in data["losses"]))

            ax[5].scatter(time, losses, label=label, s=10)
        else:
            ax[5].scatter([0], [0], label=label, s=10)

        time, packets = zip(*((obj["time"], obj) for obj in data["packets"] if obj["packet_type"] == "1RTT"))
        throughputs = calculate_throughput_windows(packets, 10000)
        ax[6].plot(time, throughputs, label=label)

    rtt_values.sort()
    rtt_p95 = rtt_values[int(len(rtt_values) * 0.95)]
    rtt_avg = sum(rtt_values) / len(rtt_values)

    for queue_file, label in queue_files:
        with open(queue_file, "r") as f:
            data = json.load(f)

        time, qlen = zip(*((obj["time"], obj["qlen"]) for obj in data))

        ax[3].plot(time, qlen, label=label)

        bw_in_Bps = bandwidth * 1e6 / 8  # Mbps to Bps conversion
        rtt_in_s = round_trip_time / 1e3  # ms to s conversion

        # BDP [B] = BW [Bps] * RTT [s]
        bdp = bw_in_Bps * rtt_in_s
        queue_length_limit = int(queue_length_factor * bdp)
        MTU = 1500
        ax[3].axhline(queue_length_limit // MTU, color="red", linestyle="--", label="BDP (in packets)")

    # set y-axis for delays to ignore outliers, calculate the 95th percentile
    # of the RTT (and the OWD estimate) values and set the y-axis limit to that
    ax[0].set_ylabel("One-Way Delay [ms]")
    ax[0].set_ylim(bottom=0, top=rtt_p95 / 2 + (rtt_avg / 2 - 0))
    ax[1].set_ylabel("Round-Trip Time [ms]")
    ax[1].set_ylim(bottom=0, top=rtt_p95 + (rtt_avg - 0))

    ax[2].set_ylabel("Congestion Window Size [byte]")
    ax[2].set_ylim(bottom=0)
    ax[3].set_ylabel("Queue Length [packet]")
    ax[3].set_ylim(bottom=0)
    ax[4].set_ylabel("ECN CE Count")
    ax[4].set_ylim(bottom=0)
    ax[5].set_ylabel("Size of Lost Packets [byte]")
    ax[5].set_ylim(bottom=0)
    ax[6].set_ylabel("Estimated Throughputs [bps]")
    ax[6].set_ylim(bottom=0)
    ax[6].set_xlabel("Time [ms]")

    handles, labels = ax[0].get_legend_handles_labels()
    fig.legend(
        handles,
        labels,
        loc="upper center",
        bbox_to_anchor=(0.5, 1.001),
        ncol=len(labels),
    )

    fig.suptitle(f"Congestion Window Size and Queue Length\nBandwidth: {bandwidth} Mbps, Round-Trip Time: {round_trip_time} ms", fontsize=16)

    fig.tight_layout(pad=1.1, rect=(0, 0, 1, 0.95))
    fig.savefig(output_file)


def parse_path_label_pair(text: str):
    if ":" not in text:
        raise argparse.ArgumentTypeError(
            "entries must be provided as 'PATH:LABEL'"
        )
    path, label = text.split(":", 1)
    return path, label


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Plot congestion window size from a data set."
    )
    parser.add_argument(
        "output_file",
        type=str,
        help="Path to save the PNG output plot.",
    )
    parser.add_argument(
        "--qlog",
        dest="qlogs",
        action="append",
        type=parse_path_label_pair,
        metavar="PATH:LABEL",
        help=(
            "QLOG file path. Repeat for each qlog file to plot."
            " The label will be derived from the file name."
        ),
    )
    parser.add_argument(
        "--queue",
        dest="queues",
        action="append",
        type=parse_path_label_pair,
        metavar="PATH:LABEL",
        help=(
            "Queue file path. Repeat for each queue file to plot."
            " The label will be derived from the file name."
        ),
    )
    parser.add_argument("--queue-length-factor", type=float)
    parser.add_argument("--bandwidth", type=int)
    parser.add_argument("--round-trip-time", type=int)

    args = parser.parse_args()

    if args.qlogs and args.queues:
        plot_qlog_rtt_cwnd(args.qlogs, args.queues, args.queue_length_factor, args.bandwidth, args.round_trip_time, args.output_file)
        sys.exit(0)
    else:
        parser.error(
            "--qlog, --queue, --bandwidth, and --round-trip-time must be given"
        )
        sys.exit(1)
