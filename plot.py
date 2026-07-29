#!/usr/bin/env python3

import argparse
import bisect
import colorsys
import json
import sys
import math
import matplotlib.colors as mcolors
import matplotlib.pyplot as plt
import matplotlib.transforms as transforms


def adjust_lightness(color, amount):
    """Adjust the lightness of a matplotlib-compatible color.

    amount > 1.0 makes the color lighter, < 1.0 makes it darker.
    """
    rgb = mcolors.to_rgb(color)
    h, l, s = colorsys.rgb_to_hls(*rgb)
    l_adjusted = max(0.0, min(1.0, l * amount))
    return colorsys.hls_to_rgb(h, l_adjusted, s)


def get_dispersion_in_seconds(pkt1: dict, pkt2: dict) -> float:
    # Convert ms to seconds
    return (pkt2["recv_time"] - pkt1["recv_time"]) / 1e3


def calculate_throughput_estimates(
    packets: list[dict],
    tau: float = 1.0
) -> list[float]:
    """Calculate exponentially weighted moving average throughput in bps."""
    throughputs = []

    def instant_throughput(pkt1: dict, pkt2: dict) -> float | None:
        """Calculate instantaneous throughput based on the difference in the
        reception of two adjacent packets."""

        pkt2_size = pkt2["packet_length"] * 8  # in bits

        dispersion = get_dispersion_in_seconds(pkt1, pkt2)

        if dispersion < 1e-9:
            # Refuse to calculate throughput when it's unrealistic (< 1 ns)
            return None
        throughput = pkt2_size / dispersion
        return throughput

    packets = sorted(
        filter(
            lambda pkt: pkt["packet_type"] == "1RTT",
            packets
        ),
        key=lambda pkt: pkt["recv_time"]
    )
    adjacent_packets = zip(packets, packets[1:])

    # Handle the initial value separately
    throughput = 0.0
    throughput_average = throughput
    throughputs.append(throughput_average)

    # Handle the rest uniformly
    for pkt1, pkt2 in adjacent_packets:
        throughput = instant_throughput(pkt1, pkt2)
        if throughput is not None:
            # alpha_i = 1 - e^{-dt_i/tau}
            # Dynamic alpha based on time difference
            alpha = 1 - \
                math.exp(-(pkt2["recv_time"] - pkt1["recv_time"] +
                         sys.float_info.epsilon) / tau)
            throughput_average += (throughput - throughput_average) * alpha
            throughputs.append(throughput_average)
        else:
            throughputs.append(throughput_average)

    return throughputs


def get_cwnd_at_time(cwnds: list[dict], target_time: float) -> float:
    """Find the active cwnd value at target_time using binary search."""
    if len(cwnds) == 0:
        return 0.0
    times = [obj["time"] for obj in cwnds]
    idx = bisect.bisect_left(times, target_time)
    if idx == 0:
        return cwnds[0]["cwnd"]
    return cwnds[idx - 1]["cwnd"]


def get_label_color(label: str, index: int) -> str:
    """Get a consistent, visually pleasing color for a given protocol label."""
    lbl = label.lower()
    if "prague" in lbl:
        return "#1b9e77"  # Professional Teal
    elif "reno" in lbl:
        return "#d95f02"  # Professional Orange
    elif "cubic" in lbl:
        return "#7570b3"  # Slate Blue
    elif "bbr" in lbl:
        return "#e7298a"  # Magenta

    # Qualitative Set2 palette from ColorBrewer
    set2 = ["#66c2a5", "#fc8d62", "#8da0cb", "#e78ac3",
            "#a6d854", "#ffd92f", "#e5c494", "#b3b3b3"]
    return set2[index % len(set2)]


def plot(
    endpoint_files: list[tuple[str, str]],
    queue_files: list[tuple[str, str]],
    queue_length_factor: float,
    bandwidth: int,
    round_trip_time: int,
    output_file: str
):
    plt.style.use("seaborn-v0_8-whitegrid")

    fig, axes = plt.subplots(6, 1, figsize=(24, 16), sharex=True)
    ax_rcvlen, ax_rtt, ax_cwnd, ax_queue, ax_alpha, ax_tput = axes

    rtt_values = []

    # Process and plot endpoint data
    for idx, (json_file, label) in enumerate(endpoint_files):
        with open(json_file, "r") as f:
            data = json.load(f)

        color = get_label_color(label, idx)

        # Received Packet Length
        if packets := data.get("packets"):
            time, pktlen = zip(
                *((obj["recv_time"], obj["packet_length"]) for obj in packets))
            ax_rcvlen.scatter(time, pktlen, label=label,
                              color=color, alpha=0.9, s=0.15)
            ax_rcvlen.vlines(time, 0, 600, label=label,
                             color=color, alpha=0.6, linewidth=0.075)

        # Round-Trip Time
        if rtts := data.get("rtts"):
            time_rtt, rtt = zip(*((obj["time"], obj["rtt"]) for obj in rtts))
            rtt_values.extend(rtt)
            ax_rtt.plot(time_rtt, rtt, label=label,
                        color=color, alpha=0.85, linewidth=1.5)

        # Get distinct shades dynamically from the primary protocol color
        inflight_color = adjust_lightness(color, 1.3)  # 30% lighter
        ssthresh_color = adjust_lightness(color, 0.6)  # 40% darker

        # Congestion Window Size
        if (cwnds := data.get("cwnds")):
            time, cwnd = zip(*((obj["time"], obj["cwnd"]) for obj in cwnds))
            ax_cwnd.plot(time, cwnd, label=label, color=color,
                         alpha=0.9, linewidth=2.0)

        # In-flight Bytes
        if inflights := data.get("inflight"):
            time, inflight = zip(
                *((obj["time"], obj["inflight"]) for obj in inflights))
            ax_cwnd.plot(time, inflight, label=label, color=inflight_color,
                         alpha=0.7, linewidth=1.2, linestyle="--")

        # Slow Start Thresholds
        if ssthreshs := data.get("ssthreshs"):
            # Replace ULONG_MAX with NaN to avoid plotting
            time, ssthresh = zip(*(
                (
                    obj["time"],
                    (
                        obj["ssthresh"]
                        if obj["ssthresh"] < 2**64-1
                        else
                        float("nan")
                    )
                )
                for obj in ssthreshs
            ))
            ax_cwnd.step(time, ssthresh, where="post", label=label,
                         color=ssthresh_color, alpha=0.85, linewidth=1.5,
                         linestyle="-.")

        # Losses marked on the CWND axis
        if losses := data.get("losses"):
            loss_times = []
            loss_cwnds = []
            loss_vols = []
            for obj in losses:
                time = obj["time"]
                vol = int(obj["loss"])  # Volume of lost data in bytes

                cwnd = get_cwnd_at_time(data["cwnds"], time)
                loss_times.append(time)
                loss_cwnds.append(cwnd)
                loss_vols.append(vol)

            # Marking loss events on the cwnd line
            ax_cwnd.scatter(
                loss_times,
                loss_cwnds,
                marker="v",
                color="#d62728",  # Highlight losses in red
                edgecolors="black",
                s=80,
                zorder=5,
                label=label
            )

            # Volume labels next to each marker
            for time, cwnd, volume in zip(loss_times, loss_cwnds, loss_vols):
                ax_cwnd.annotate(
                    f"{volume} B",
                    xy=(time, cwnd),
                    xytext=(6, 3),
                    textcoords="offset points",
                    fontsize=8.5,
                    color="#d62728",
                    weight="bold",
                    bbox=dict(boxstyle="round,pad=0.15", fc="white",
                              ec="#d62728", alpha=0.8, lw=0.5)
                )

        # ECN Congestion Experienced
        if ecns := data.get("ecns"):
            ecn_times, ect0, ce = zip(
                *((obj["time"], obj["ect0"], obj["ce"]) for obj in ecns))
            if any(ect0):
                ecn_cwnds = [
                    get_cwnd_at_time(data["cwnds"], time)
                    for time, ce in zip(ecn_times, ce)
                    if ce > 0
                ]
                ax_cwnd.scatter(ecn_times, ecn_cwnds, label=label,
                                color=color, s=12, alpha=0.7)

                # Marking ECN events on the cwnd line
                ax_cwnd.scatter(
                    ecn_times,
                    ecn_cwnds,
                    marker="v",
                    color="#1f77b4",  # Highlight ECNs in blue
                    edgecolors="black",
                    s=80,
                    zorder=5,
                    label=label
                )

        # L4S Alpha Values
        if l4s := data.get("l4s"):
            time, alphas = zip(*((obj["time"], obj["alpha"]) for obj in l4s))
            ax_alpha.plot(time, alphas, label=label, color=color, alpha=0.85,
                          linewidth=1.5)

            # Find when alpha got to 1.0 (or first alpha == 1.0)
            target_l4s = next(
                (obj for obj in l4s if obj["alpha"] >= 1.0 - 1e-6), l4s[0])
            t_alpha_1 = target_l4s["time"]
            alpha_val = target_l4s["alpha"]

            if packets := data.get("packets"):
                recv_until = [
                    p for p in packets if p["recv_time"] <= t_alpha_1]
                cum_pkts = len(recv_until)
                cum_bytes = sum(p["packet_length"] for p in recv_until)

                # Plot cumulative received bytes behind the alpha plot
                sorted_pkts = sorted(packets, key=lambda p: p["recv_time"])
                pkt_times = [p["recv_time"] for p in sorted_pkts]
                cum_bytes_list = []
                running_bytes = 0
                for p in sorted_pkts:
                    running_bytes += p["packet_length"]
                    cum_bytes_list.append(running_bytes / 1024.0)  # KiB

                if not hasattr(ax_alpha, "twin_bytes"):
                    ax_alpha.twin_bytes = ax_alpha.twinx()
                    ax_alpha.twin_bytes.set_ylabel(
                        "Cumulative Recv [KiB]", color="#666666", fontsize=11,
                        fontweight="bold")
                    ax_alpha.twin_bytes.tick_params(
                        colors="#444444", labelsize=10)
                    ax_alpha.twin_bytes.grid(False)

                cum_color = adjust_lightness(color, 1.2)
                ax_alpha.twin_bytes.plot(
                    pkt_times, cum_bytes_list,
                    color=cum_color, linestyle="--", linewidth=1.2, alpha=0.5,
                    label=f"{label} (cum. KiB)"
                )
                ax_alpha.twin_bytes.set_ylim(bottom=0)

                # Text note drawn right next to the first appearance of alpha
                if cum_bytes >= 1024 * 1024:
                    bytes_str = f"{cum_bytes /
                                   (1024 * 1024):.2f} MiB ({cum_bytes:,} B)"
                elif cum_bytes >= 1024:
                    bytes_str = f"{cum_bytes / 1024:.1f} KiB ({cum_bytes:,} B)"
                else:
                    bytes_str = f"{cum_bytes:,} B"

                note_text = (
                    f"alpha={alpha_val:.1f} at {t_alpha_1:.1f} ms\n"
                    f"Cumulative Recv:\n"
                    f"- {cum_pkts:,} packets\n"
                    f"- {bytes_str}"
                )

                ax_alpha.scatter([t_alpha_1], [alpha_val],
                                 color=color, s=50, zorder=5)
                ax_alpha.axvline(t_alpha_1, color=color,
                                 linestyle=":", alpha=0.6, linewidth=1.2)

                ax_alpha.annotate(
                    note_text,
                    xy=(t_alpha_1, alpha_val),
                    xytext=(25, -20 if idx % 2 == 0 else 10),
                    textcoords="offset points",
                    fontsize=8.5,
                    fontweight="bold",
                    color="#222222",
                    bbox=dict(boxstyle="round,pad=0.35", fc="#ffffff",
                              ec=color, alpha=0.9, lw=1.2),
                    arrowprops=dict(
                        arrowstyle="->", connectionstyle="arc3,rad=0.15",
                        color=color, lw=1.2),
                    zorder=6
                )

        # Estimated Throughput (in Mbps)
        pkt_data = [(obj["recv_time"], obj)
                    for obj in data["packets"] if obj["packet_type"] == "1RTT"]
        if pkt_data:
            time_pkt, packets = zip(*pkt_data)

            # Using 4 RTT as tau for smoothing
            throughputs = calculate_throughput_estimates(
                packets,
                tau=round_trip_time * 4.0
            )

            throughputs_mbps = [t / 1e6 for t in throughputs]
            ax_tput.plot(time_pkt, throughputs_mbps, label=label,
                         color=color, alpha=0.85, linewidth=1.5)

    # Calculate RTT limits
    if rtt_values:
        rtt_values.sort()
        rtt_p95 = rtt_values[int(len(rtt_values) * 0.95)]
        rtt_avg = sum(rtt_values) / len(rtt_values)
    else:
        rtt_p95 = round_trip_time if round_trip_time else 10.0
        rtt_avg = round_trip_time if round_trip_time else 10.0

    # Process and plot queue data
    if queue_files:
        for idx, (queue_file, label) in enumerate(queue_files):
            with open(queue_file, "r") as f:
                data = json.load(f)

            color = get_label_color(label, idx)

            time, qlen = zip(*((obj["time"], obj["backlog"]) for obj in data))
            ax_queue.plot(time, qlen, label=label, color=color,
                          alpha=0.8, linewidth=1.5)

    # Line denoting the queue length limit
    bw_in_Bps = bandwidth * 1e6 / 8  # Mbps to Bps conversion
    rtt_in_s = round_trip_time / 1e3  # ms to s conversion
    bdp = bw_in_Bps * rtt_in_s
    bdp_truncated = int(bdp)
    queue_length_limit = int(queue_length_factor * bdp)

    ax_queue.axhline(
        queue_length_limit,
        color="#555555",
        linestyle="--",
        linewidth=1
    )

    # Text label above the queue length limit line
    trans_queue = transforms.blended_transform_factory(
        ax_queue.transAxes, ax_queue.transData)
    ax_queue.text(
        0.02,
        queue_length_limit,
        f"Queue Length Limit ({queue_length_factor} x BDP = {
            queue_length_limit} B)",
        transform=trans_queue,
        va="bottom",
        ha="left",
        fontsize=9,
        color="#555555",
        weight=700,
        bbox=dict(boxstyle="round,pad=0.1", fc="#ffffff",
                  ec="none", alpha=0.75, zorder=4)
    )

    ax_cwnd.axhline(
        bdp_truncated,
        color="#555555",
        linestyle="--",
        linewidth=1
    )

    # Text label above the CWND line
    trans_bdp = transforms.blended_transform_factory(
        ax_cwnd.transAxes, ax_cwnd.transData)
    ax_cwnd.text(
        0.02,
        bdp_truncated,
        f"Bandwidth-Delay Product {bdp_truncated} B)",
        transform=trans_bdp,
        va="bottom",
        ha="left",
        fontsize=9,
        color="#555555",
        weight=700,
        bbox=dict(boxstyle="round,pad=0.1", fc="#ffffff",
                  ec="none", alpha=0.75, zorder=4)
    )

    # Line denoting the link capacity limit on throughput axis once
    ax_tput.axhline(
        bandwidth,
        color="#555555",
        linestyle="--",
        linewidth=1
    )

    # Text label above the link capacity line
    trans_tput = transforms.blended_transform_factory(
        ax_tput.transAxes, ax_tput.transData)
    ax_tput.text(
        0.02,
        bandwidth,
        f"Bandwidth Limit ({bandwidth} Mbps)",
        transform=trans_tput,
        va="bottom",
        ha="left",
        fontsize=9,
        color="#555555",
        weight=700,
        bbox=dict(boxstyle="round,pad=0.1", fc="#ffffff",
                  ec="none", alpha=0.75, zorder=4)
    )

    # Line denoting the base round-trip time on round-trip-time axis once
    ax_rtt.axhline(
        round_trip_time,
        color="#555555",
        linestyle="--",
        linewidth=1
    )

    # Text label above the round-trip time line
    trans_rtt = transforms.blended_transform_factory(
        ax_rtt.transAxes, ax_rtt.transData)
    ax_rtt.text(
        0.02,
        round_trip_time,
        f"Base Round-Trip Time ({round_trip_time} ms)",
        transform=trans_rtt,
        va="top",
        ha="left",
        fontsize=9,
        color="#555555",
        weight=700,
        bbox=dict(boxstyle="round,pad=0.1", fc="#ffffff",
                  ec="none", alpha=0.75, zorder=4)
    )

    # Apply uniform formatting to all subplots
    for ax in axes:
        ax.grid(True, which="both", linestyle=":", alpha=0.5, color="#cccccc")
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.spines["left"].set_color("#888888")
        ax.spines["bottom"].set_color("#888888")
        ax.tick_params(colors="#444444", labelsize=10)
        ax.yaxis.label.set_color("#222222")
        ax.yaxis.label.set_size(11)
        ax.yaxis.label.set_weight("bold")

    # Set specific labels and limits
    ax_rcvlen.set_ylabel("Received Packet Length [B]")
    ax_rcvlen.set_ylim(bottom=0)

    ax_rtt.set_ylabel("Round-Trip Time [ms]")
    ax_rtt.set_ylim(bottom=0, top=max(10.0, rtt_p95 + rtt_avg))

    ax_cwnd.set_ylabel("Congestion Window [byte]")
    ax_cwnd.set_ylim(bottom=0)

    ax_queue.set_ylabel("Queue Length [byte]")
    ax_queue.set_ylim(bottom=0)

    ax_alpha.set_ylabel("Prague Alpha")
    ax_alpha.set_ylim(bottom=0, top=1)

    ax_tput.set_ylabel("Throughput [Mbps]")
    ax_tput.set_ylim(bottom=0, top=bandwidth * 1.25)
    ax_tput.set_xlabel("Time [ms]", fontweight="bold", fontsize=11)

    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(
        handles,
        labels,
        loc="upper center",
        bbox_to_anchor=(0.5, 0.94),
        ncol=min(6, len(labels)),
        frameon=True,
        facecolor="#fcfcfc",
        edgecolor="#dddddd",
        fontsize=10
    )

    fig.suptitle(
        f"QUIC L4S Performance Comparison\nBandwidth: {
            bandwidth} Mbps, Base RTT: {round_trip_time} ms",
        fontsize=16,
        fontweight="bold",
        y=0.98
    )

    fig.tight_layout(pad=1.2, rect=(0, 0, 1, 0.91))
    fig.savefig(output_file, dpi=240, bbox_inches="tight")


def parse_path_label_pair(text: str):
    if ":" not in text:
        raise argparse.ArgumentTypeError(
            "entries must be provided as 'PATH:LABEL'"
        )
    path, label = text.split(":", 1)
    return path, label


if __name__ == "__main__":
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

    if args.qlogs:
        plot(
            args.qlogs,
            args.queues,
            args.queue_length_factor,
            args.bandwidth,
            args.round_trip_time,
            args.output_file
        )
        sys.exit(0)
    else:
        parser.error(
            "--qlog, --bandwidth, --round-trip-time, and --queue-length-factor"
            " must be given"
        )
        sys.exit(1)
