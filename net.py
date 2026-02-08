#!/usr/bin/env python3

import itertools
import json
import os
from argparse import ArgumentParser, BooleanOptionalAction
from ipaddress import IPv4Interface, IPv4Network

from mininet.cli import CLI
from mininet.link import TCLink
from mininet.log import info, output, error, setLogLevel
from mininet.net import Mininet
from mininet.node import Node
from mininet.topo import Topo


class Endpoint(Node):
    def config(self, algo: str = "prague", **params):
        super().config(**params)

        for intf in self.intfList():
            self.cmd(f"ethtool -K {intf} tso off gso off gro off lro off")
        self.cmd(f"sysctl -w net.ipv4.tcp_ecn={3}")
        self.cmd(f"sysctl -w net.ipv4.tcp_congestion_control={algo}")


class DualPI2Router(Node):
    def config(self, delay: int = 50, bw: int = 5, **kwargs):
        super().config(**kwargs)

        info("\n*** Setting up router interfaces")

        for i, intf in enumerate(self.intfList(), start=1):
            delay_set = kwargs.get(f"delay{i}", delay)
            bw_set = kwargs.get(f"bw{i}", bw)

            self.cmd(
                f"ethtool -K {intf} tso off gso off gro off lro off"
            )
            self.cmd(
                f"tc qdisc replace dev {intf} root handle 1: htb default 10"
            )
            self.cmd(
                f"tc class add dev {intf} parent 1: classid 1:10 htb"
                f"   rate {bw_set}mbit ceil {bw_set}mbit"
            )
            self.cmd(
                f"tc qdisc add dev {intf} parent 1:10 handle 20: netem"
                f"   delay {delay_set}ms"
            )
            self.cmd(
                f"tc qdisc add dev {intf} parent 20: handle 30: dualpi2"
                f"   limit {5555} target {100}ms"
            )

            info(f"\n{intf}: bw={bw_set}mbit delay={delay_set}ms")

        self.cmd("sysctl -w net.ipv4.ip_forward=1")


class L4STopo(Topo):
    """
    Represents a star topology with a single router (`r0`) connecting
    several (see `n_net`) switched LAN segments. Each LAN consists of a single
    switch (`si`) connected to a handful (see `n_host`) of hosts (`hi`).
    """

    def __init__(self, n_net: int = 2, n_host: int = 1, endpoint_params: dict | None = None, router_params: dict | None = None, **kwargs):
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


def run(benchmark: bool = False, out_dir: str = "/tmp", algo="prague", bw1: int = 10, bw2: int = 10):
    """
    Setup the `L4STopology` with the specified parameters and benchmark the
    performance or show the interactive Mininet console.

    :param benchmark: Perform benchmarks instead of entering to CLI mode.
    """

    topo = L4STopo(
        endpoint_params=dict(algo=algo),
        router_params=dict(bw1=bw1, bw2=bw2),
    )
    net = Mininet(topo=topo, waitConnected=True, autoStaticArp=True)
    net.start()

    if benchmark:
        # Q: Shall this script perform a comprehensive benchmark with different
        # CC & AQM methods on its own? Or maybe it can rely on external tools
        # for parameterizing this script, and thus it should only be concerned
        # about conducting measurement runs for a single case (i.e., with fixed
        # CC & AQM methods).

        info("*** Starting benchmark\n")
        h1, h2, r0 = net["h1"], net["h2"], net["r0"]

        h2.cmd(
            "iperf3 --server &"
        )
        client_output = h1.cmd(
            f"iperf3 --client {h2.IP()}"
            f"       --json"
            f"       --time {5}"
            f"       --interval {5}"
        )

        try:
            info("*** Client stats:\n")

            STATS = ("bytes", "bits_per_second", "rtt", "rttvar")

            client_stats = json.loads(client_output)
            client_stats_filtered = client_stats["intervals"][0]["streams"][0]
            output(json.dumps(client_stats_filtered, indent=2) + "\n")
        except ...:
            error("*** Couldn't parse iperf3 output\n")

        try:
            info("*** Router stats:\n")

            STATS = ("bytes", "packets", "drops", "delay-c", "delay-l", "pkts-in-c", "pkts-in-l", "maxq", "ecn-mark")

            eth1_dump = json.loads(r0.cmd("tc -j -s qdisc show dev r0-eth1"))
            eth1_dualpi2_stats = next(filter(lambda qdisc: qdisc["kind"] == "dualpi2", eth1_dump))
            eth1_dualpi2_stats_filtered = {stat: eth1_dualpi2_stats[stat] for stat in STATS}
            output(f"{json.dumps(eth1_dualpi2_stats_filtered, indent=2)}\n")

            eth2_dump = json.loads(r0.cmd("tc -j -s qdisc show dev r0-eth2"))
            eth2_dualpi2_stats = next(filter(lambda qdisc: qdisc["kind"] == "dualpi2", eth2_dump))
            eth2_dualpi2_stats_filtered = {stat: eth2_dualpi2_stats[stat] for stat in STATS}
            output(f"{json.dumps(eth2_dualpi2_stats_filtered, indent=2)}\n")
        except ...:
            error("*** Couldn't parse tc xstats\n")

        result = {
            "client": client_stats,
            "router": {
                "eth1": eth1_dualpi2_stats,
                "eth2": eth2_dualpi2_stats,
            },
        }

        with open(os.path.join(out_dir, "result.json"), "w") as f:
            json.dump(result, f)
            info("*** Dumping stats\n")
            output(f"Stats saved to '{f.name}'\n")

        info("*** Stopping benchmark\n")
    else:
        CLI(net)

    net.stop()


if __name__ == "__main__":
    parser = ArgumentParser(
        description="A Mininet-based testbench for measuring L4S's performance."
    )
    parser.add_argument(
        "--benchmark",
        action=BooleanOptionalAction,
        default=False,
        help="Perform automatic benchmarks on the topology instead of entering"
             " to interactive CLI mode.",
    )
    parser.add_argument(
        "--out-dir",
        type=str,
        default="/tmp",
        help="Dir to put results into / get logs from",
    )
    parser.add_argument("--algo", default="prague")
    parser.add_argument("--bw1", default=10)
    parser.add_argument("--bw2", default=10)

    args = parser.parse_args()

    setLogLevel("info")
    run(benchmark=args.benchmark, out_dir=args.out_dir, algo=args.algo, bw1=args.bw1, bw2=args.bw2)
