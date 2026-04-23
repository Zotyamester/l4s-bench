#!/usr/bin/env python3

import matplotlib.pyplot as plt
import json
import sys
from pathlib import Path


def plot_cwnd_goodput_rtt(json_files: list[tuple[str, str]], output_file: str):
    fig, ax = plt.subplots(3, 1, figsize=(10, 9), sharex=True)

    for json_file, label in json_files:
        with open(json_file, "r") as f:
            data = json.load(f)

        time, cwnd, goodput, rtt = zip(*(obj.values() for obj in data))

        ax[0].plot(time, cwnd, label=label)
        ax[1].plot(time, goodput, label=label)
        ax[2].plot(time, rtt, label=label)

    ax[0].set_ylabel("Congestion Window Size [byte]")

    ax[1].set_ylabel("Goodput [bps]")

    ax[2].set_xlabel("Time [s]")
    ax[2].set_ylabel("RTT [us]")

    handles, labels = ax[0].get_legend_handles_labels()
    fig.legend(
        handles,
        labels,
        loc="upper center",
        bbox_to_anchor=(0.5, 1.001),
        ncol=len(labels),
    )

    fig.tight_layout(pad=1.1, rect=[0, 0, 1, 0.95])
    fig.savefig(output_file)


def plot_bpf(log_files: list[tuple[str, str]], output_file: str):
    fig, ax = plt.subplots(2, 1, figsize=(10, 6), sharex=True)

    for log_file, label in log_files:
        with open(log_file, "r") as f:
            data = [line.split() for line in f.readlines()]

        timestamp, cwnd, inflight, srtt = zip(
            *(
                (
                    int(row[0]) / 1e9,
                    int(row[1]),
                    (int(row[2]) - int(row[3])) / 1500,
                    int(row[4]) / 1e3,
                )
                for row in data
            )
        )

        # normalize timestamps to start from the first one
        timestamp = [ts - timestamp[0] for ts in timestamp]

        ax[0].plot(timestamp, cwnd, label=f"{label}-cwnd")
        ax[0].plot(timestamp, inflight, label=f"{label}-inflight")
        ax[1].plot(timestamp, srtt, label=label)

    ax[0].set_ylabel("Congestion Window Size [packet]")
    ax[0].set_ylim(0, 900)

    ax[1].set_xlabel("Time [s]")
    ax[1].set_xlim(0, 60)
    ax[1].set_ylabel("RTT [ms]")
    ax[1].set_ylim(0, 450)

    handles, labels = ax[0].get_legend_handles_labels()
    fig.legend(
        handles,
        labels,
        loc="upper center",
        bbox_to_anchor=(0.5, 1.001),
        ncol=len(labels),
    )

    fig.tight_layout(pad=1.1, rect=[0, 0, 1, 0.95])
    fig.savefig(output_file)


def parse_log_with_label(value: str):
    if ":" not in value:
        raise argparse.ArgumentTypeError("Log entries must be provided as 'PATH:LABEL'")
    path, label = value.split(":", 1)
    if Path(path).suffix.lower() != ".txt":
        raise argparse.ArgumentTypeError("BPF log file must have a .txt extension")
    return path, label


def parse_json_with_label(value: str):
    if ":" not in value:
        raise argparse.ArgumentTypeError(
            "JSON entries must be provided as 'PATH:LABEL'"
        )
    path, label = value.split(":", 1)
    if Path(path).suffix.lower() != ".json":
        raise argparse.ArgumentTypeError("JSON file must have a .json extension")
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
        "json_file",
        nargs="?",
        help="Path to the JSON input file for JSON-based plotting.",
    )
    parser.add_argument(
        "--log",
        dest="logs",
        action="append",
        type=parse_log_with_label,
        metavar="PATH:LABEL",
        help=(
            "BPF log file and label pair in the form PATH:LABEL."
            " Repeat for each algorithm to plot."
        ),
    )
    parser.add_argument(
        "--json",
        dest="jsons",
        action="append",
        type=parse_json_with_label,
        metavar="PATH:LABEL",
        help=(
            "JSON file and label pair in the form PATH:LABEL."
            " Repeat for each algorithm to plot."
        ),
    )

    args = parser.parse_args()

    if args.logs:
        plot_bpf(args.logs, args.output_file)
        sys.exit(0)

    if args.jsons:
        plot_cwnd_goodput_rtt(args.jsons, args.output_file)
        sys.exit(0)

    if args.json_file is None:
        parser.error(
            "either --log or --json must be provided, or a JSON file path must be given"
        )

    file_ext = args.json_file.split(".")[-1].lower()
    match file_ext:
        case "json":
            plot_cwnd_goodput_rtt(
                [(args.json_file, Path(args.json_file).stem)], args.output_file
            )
        case _:
            parser.error("invalid input file format; use a JSON file for JSON plotting")
