#!/usr/bin/env python3

import itertools
import json
import os
from collections.abc import Callable
from argparse import ArgumentParser, BooleanOptionalAction
from ipaddress import IPv4Interface, IPv4Network

from mininet.cli import CLI
from mininet.link import TCLink
from mininet.log import info, output, setLogLevel
from mininet.net import Mininet
from mininet.node import Node
from mininet.topo import Topo


class Endpoint(Node):
    def config(self, **params):
        super().config(**params)

        for intf in self.intfList():
            self.cmd(f"ethtool -K {intf} tso off gso off gro off lro off")
        self.cmd(f"sysctl -w net.ipv4.tcp_ecn={3}")

    def setTcpCongestionControl(self, algorithm: str):
        self.cmd(f"sysctl -w net.ipv4.tcp_congestion_control={algorithm}")


class DualPI2Router(Node):
    def config(self, btl_bw: int, **kwargs):
        super().config(**kwargs)

        info("\n*** Setting up router interfaces")

        intf = f"{self.name}-eth2"

        self.cmd(
            f"ethtool -K {intf} tso off gso off gro off lro off"
        )
        self.cmd(
            f"tc qdisc replace dev {intf} root handle 1: htb default 10"
        )
        self.cmd(
            f"tc class add dev {intf} parent 1: classid 1:10 htb"
            f"   rate {btl_bw}mbit ceil {btl_bw}mbit"
        )
        self.cmd(
            f"tc qdisc add dev {intf} parent 1:10 handle 20: dualpi2"
            # TODO: experiment with parameters
        )

        info(f"\n{intf} (bottleneck link): {btl_bw} Mbps")

        self.cmd("sysctl -w net.ipv4.ip_forward=1")


class L4STopo(Topo):
    """
    Represents a star topology with a single router (`r0`) connecting
    several (see `n_net`) switched LAN segments. Each LAN consists of a single
    switch (`si`) connected to a handful (see `n_host`) of hosts (`hi`).
    """

    def __init__(self, n_net: int = 2, n_host: int = 1,
                 endpoint_params: dict | None = None,
                 router_params: dict | None = None, **kwargs):
        self.n_net = n_net
        self.n_host = n_host
        self.endpoint_params = endpoint_params or {}
        self.router_params = router_params or {}
        super().__init__(**kwargs)

    def build(self):
        BASE_SUBNET = IPv4Network("10.0.0.0/8")

        # make a list of `n_net` /24 subnets in the `BASE_SUBNET`
        nets = [
            tuple(
                IPv4Interface(f"{ip}/{neti.prefixlen}") for ip in neti.hosts()
            )  # a given subnet shall be immutable, hence the tuple
            for neti in itertools.islice(BASE_SUBNET.subnets(16), self.n_net)
        ]

        r0 = self.addHost(
            f"r{0}",
            cls=DualPI2Router,
            ip=nets[0][0].with_prefixlen,
            **self.router_params
        )  # specify the first subnet's first IP address in the `ip` param

        for i, (r0_i_ip, hi_ip, *_) in enumerate(nets, start=1):
            si = self.addSwitch(f"s{i}")

            self.addLink(
                si,
                r0,
                intfName2=f"r0-eth{i}",
                cls=TCLink,
                params2={"ip": r0_i_ip.with_prefixlen},
            )

            # TODO: here, we could make use of the `n_host` param, but it would
            #       require a change in the naming scheme
            hi = self.addHost(
                f"h{i}",
                cls=Endpoint,
                ip=hi_ip.with_prefixlen,
                defaultRoute=f"via {r0_i_ip.ip}",
                **self.endpoint_params
            )

            self.addLink(hi, si)  # , cls=TCLink, delay="50ms", bw=10)


def iperf(net: Mininet, algorithm: str) -> dict:
    h1, h2 = net["h1"], net["h2"]

    h1.setTcpCongestionControl(algorithm)
    h2.setTcpCongestionControl(algorithm)  # technically, this isn't necessary

    h2.cmd(
        "iperf3 --server &"
    )
    client_output = h1.cmd(
        f"iperf3 --client {h2.IP()}"
        f"       --json"
        f"       --time {5}"
        f"       --interval {1}"
    )

    return json.loads(client_output)


def quinn_perf(net: Mininet, algorithm: str) -> dict:
    h1, h2 = net["h1"], net["h2"]

    h2.cmd(
        "/home/vagrant/quinn-perf server --no-protection"
        f"       --listen {h2.IP()}:{4433}"
        f"       --congestion {algorithm} &"
    )
    client_output = h1.cmd(
        "/home/vagrant/quinn-perf client --no-protection"
        f"       --ip {h2.IP()}"
        f"       --congestion {algorithm}"
        f"       --json -"
        f"       --duration {5}"
        f"       --interval {1}"
        f"       h2:{4433} 2> /dev/null"
    ).split("\n")[-1]

    return json.loads(client_output)


def run(
    algorithm: str,
    btl_bw: int,
    out_dir: str,
    benchmark: Callable[[Mininet, ...], dict] | None = None,
    **kwargs
):
    """
    Setup the `L4STopology` with the specified parameters and benchmark the
    performance or show the interactive Mininet console.

    :param benchmark: Perform benchmarks instead of entering to CLI mode.
    """

    topo = L4STopo(
        endpoint_params=dict(),
        router_params=dict(btl_bw=btl_bw),
    )
    net = Mininet(topo=topo, waitConnected=True, autoStaticArp=True)
    net.start()

    try:
        if benchmark:
            info("*** Starting benchmark\n")

            client_result = benchmark(net, algorithm)

            r0 = net["r0"]
            r0_output = r0.cmd("tc -j -s qdisc show")
            r0_qdisc_stats = json.loads(r0_output)

            result = {
                "client": client_result,
                "router": r0_qdisc_stats,
            }

            with open(os.path.join(out_dir, "result.json"), "w") as f:
                json.dump(result, f)
                info("*** Saving results\n")
                output(f"Results saved to '{f.name}'\n")

            info("*** Stopping benchmark\n")
        else:
            CLI(net)
    finally:
        net.stop()


if __name__ == "__main__":
    parser = ArgumentParser(
        description="A Mininet-based testbench for measuring L4S's performance."
    )
    parser.add_argument(
        "--quic-benchmark",
        action=BooleanOptionalAction,
        default=False,
        help="Perform QUIC benchmarks on the topology instead of entering"
             " to interactive CLI mode.",
    )
    parser.add_argument(
        "--tcp-benchmark",
        action=BooleanOptionalAction,
        default=False,
        help="Perform TCP benchmarks on the topology instead of entering"
             " to interactive CLI mode.",
    )
    parser.add_argument(
        "--out-dir",
        type=str,
        default="/tmp",
        help="Dir to put results into / get logs from",
    )
    parser.add_argument("--algorithm", default="prague")
    parser.add_argument("--bottleneck-bandwidth", type=int, default=10)

    args = parser.parse_args()

    setLogLevel("info")

    benchmark = None
    if args.quic_benchmark:
        benchmark = quinn_perf
    elif args.tcp_benchmark:
        benchmark = iperf

    run(algorithm=args.algorithm, btl_bw=args.bottleneck_bandwidth,
        out_dir=args.out_dir, benchmark=benchmark)
