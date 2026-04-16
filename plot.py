#!/usr/bin/env python3

import matplotlib.pyplot as plt
import json
import sys


def plot_cwnd_goodput_rtt(json_file: str, output_file: str):
    with open(json_file, "r") as f:
        data = json.load(f)

    time, cwnd, goodput, rtt = zip(*(obj.values() for obj in data))

    fig, ax = plt.subplots(3, 1, figsize=(10, 18), sharex=True)

    ax[0].plot(time, cwnd, label="Prague", color="blue")
    ax[0].set_ylabel("Congestion Window Size [byte]")

    ax[1].plot(time, goodput, label="Prague", color="blue")
    ax[1].set_ylabel("Goodput [bps]")

    ax[2].plot(time, rtt, label="Prague", color="blue")
    ax[2].set_xlabel("Time [s]")
    ax[2].set_ylabel("RTT [us]")

    fig.tight_layout()
    fig.savefig(output_file)


def plot_bpf(log_file: str, output_file: str):
    with open(log_file, "r") as f:
        data = [line.split() for line in f.readlines()]

    timestamp, cwnd, srtt = zip(
        *((int(row[0]) / 1e9, int(row[1]), int(row[2]) / 1e3) for row in data)
    )

    # normalize timestamps to start from the first one
    timestamp = [ts - timestamp[0] for ts in timestamp]

    fig, ax = plt.subplots(2, 1, figsize=(10, 6), sharex=True)

    ax[0].plot(timestamp, cwnd, label="Prague", color="blue")
    ax[0].set_ylabel("Congestion Window Size [packet]")
    ax[0].set_ylim(0, 900)

    ax[1].plot(timestamp, srtt, label="Prague", color="blue")
    ax[1].set_xlabel("Time [s]")
    ax[1].set_xlim(0, 60)
    ax[1].set_ylabel("RTT [ms]")
    ax[1].set_ylim(0, 450)

    fig.tight_layout()
    fig.savefig(output_file)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Plot congestion window size from a data set."
    )
    parser.add_argument(
        "file",
        type=str,
        help="Path to the JSON/log file containing various metrics as a function of time.",
    )
    parser.add_argument(
        "output_file",
        type=str,
        help="Path to save the PNG output plot.",
    )

    args = parser.parse_args()
    file_ext = args.file.split(".")[-1].lower()
    match file_ext:
        case "json":
            plot_cwnd_goodput_rtt(args.file, args.output_file)
        case "txt":
            plot_bpf(args.file, args.output_file)
        case _:
            print("error: invalid input file format")
            parser.print_usage()
            sys.exit(1)
