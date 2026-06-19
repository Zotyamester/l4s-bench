#!/usr/bin/env python3

import matplotlib.pyplot as plt
import json
import sys


def plot_qlog_rtt_cwnd(endpoint_files: list[tuple[str, str]], queue_files: list[tuple[str, str]], output_file: str):
    fig, ax = plt.subplots(5, 1, figsize=(30, 18), sharex=True)

    rtt_values = []

    for json_file, label in endpoint_files:
        with open(json_file, "r") as f:
            data = json.load(f)

        time, rtt = zip(*((obj["time"], obj["rtt"]) for obj in data["rtts"]))
        rtt_values.extend(rtt)

        ax[0].plot(time, rtt, label=label)

        time, cwnd = zip(*((obj["time"], obj["cwnd"])
                         for obj in data["cwnds"]))

        ax[1].plot(time, cwnd, label=label)

        if len(data["ecns"]) > 0:
            time, ecns = zip(*((obj["time"], obj["congestion_experienced"])
                             for obj in data["ecns"]))

            ax[3].scatter(time, ecns, label=label)
        else:
            ax[3].scatter([0], [0], label=label)

        if len(data["losses"]) > 0:
            time, losses = zip(*((obj["time"], obj["loss"])
                             for obj in data["losses"]))

            ax[4].scatter(time, losses, label=label)
        else:
            ax[4].scatter([0], [0], label=label)

    rtt_values.sort()
    rtt_p95 = rtt_values[int(len(rtt_values) * 0.95)]
    rtt_avg = sum(rtt_values) / len(rtt_values)

    #for queue_file, label in queue_files:
    #    with open(queue_file, "r") as f:
    #        data = json.load(f)

    #    time, qlen = zip(*((obj["time"], obj["qlen"]) for obj in data))

    #    ax[2].plot(time, qlen, label=label)

    ax[0].set_ylabel("Round-Trip Time [ms]")
    # set y-axis to ignore outliers, calculate the 95th percentile of the RTT values and set the y-axis limit to that value
    ax[0].set_ylim(bottom=0, top=rtt_p95 + (rtt_avg - 0))
    ax[1].set_ylabel("Congestion Window Size [byte]")
    ax[2].set_ylabel("Queue Length [packet]")
    ax[3].set_ylabel("ECN CE Count")
    ax[4].set_ylabel("Size of Lost Packets [byte]")
    ax[4].set_xlabel("Time [ms]")

    handles, labels = ax[0].get_legend_handles_labels()
    fig.legend(
        handles,
        labels,
        loc="upper center",
        bbox_to_anchor=(0.5, 1.001),
        ncol=len(labels),
    )

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

    args = parser.parse_args()

    if args.qlogs and args.queues:
        plot_qlog_rtt_cwnd(args.qlogs, args.queues, args.output_file)
        sys.exit(0)

    if args.json_file is None:
        parser.error(
            "both --qlog and --queue must be provided, or a JSON file path must be given"
        )
        sys.exit(1)
