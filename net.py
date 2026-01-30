#!/usr/bin/env python3

import itertools
from argparse import ArgumentParser, BooleanOptionalAction
from ipaddress import IPv4Interface, IPv4Network

from mininet.cli import CLI
from mininet.link import TCLink
from mininet.log import info, output, setLogLevel
from mininet.net import Mininet
from mininet.node import Node
from mininet.topo import Topo


class PragueHost(Node):
    def config(self, **params):
        super().config(**params)

        for intf in self.intfList():
            self.cmd(f"ethtool -K {intf} tso off gso off gro off lro off")
            self.cmd(
                f"tc qdisc replace dev {intf} root handle 1: fq limit 20480 flow_limit 10240"
            )
        self.cmd("sysctl -w net.ipv4.tcp_ecn=3")
        self.cmd("sysctl -w net.ipv4.tcp_congestion_control=prague")


class DualPI2Router(Node):
    def config(self, **params):
        super().config(**params)

        for intf in self.intfList():
            self.cmd(f"ethtool -K {intf} tso off gso off gro off lro off")
            self.cmd(f"tc qdisc replace dev {intf} root dualpi2")
        self.cmd("sysctl -w net.ipv4.ip_forward=1")


class L4STopo(Topo):
    """
    Represents a star topology with a single router (`r0`) connecting several (see `n_net`) switched LAN segments.
    Each LAN consists of a single switch (`si`) connected to a handful (see `n_host`) of hosts (`hi`).
    """

    def build(self, n_net: int = 2, _n_host: int = 1):
        BASE_SUBNET = IPv4Network("10.0.0.0/8")

        # make a list of `n_net` /24 subnets in the `BASE_SUBNET`
        nets = [
            tuple(
                IPv4Interface(f"{ip}/{neti.prefixlen}") for ip in neti.hosts()
            )  # a given subnet shall be immutable, hence the tuple
            #    (How on Earth would you add new addresses belonging to the specified range anyway?)
            for neti in itertools.islice(BASE_SUBNET.subnets(16), n_net)
        ]

        r0 = self.addHost(
            "r0", cls=DualPI2Router, ip=nets[0][0].with_prefixlen
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

            # TODO: here, we could make use of the `n_host` param, but it would require
            #       a change in the naming scheme
            hi = self.addHost(
                f"h{i}",
                cls=PragueHost,
                ip=hi_ip.with_prefixlen,
                defaultRoute=f"via {r0_i_ip.ip}",
            )

            self.addLink(hi, si)


def run(benchmark: bool = False):
    """
    Setup the `L4STopology` with the specified parameters and benchmark the performance or show the interactive
    Mininet console.

    :param benchmark: Perform benchmarks instead of entering to CLI mode.
    """
    topo = L4STopo()
    net = Mininet(topo=topo, waitConnected=True)
    net.start()

    info("*** Routing Table on Router (r0) ***\n")
    info(net["r0"].cmd("ip route"))

    if benchmark:
        # Q: Shall this script perform a comprehensive benchmark with different CC & AQM methods on its own?
        #    Or maybe it can rely on external tools for parameterizing this script, and thus it should only be
        #    concerned about conducting measurement runs for a single case (i.e., with fixed CC & AQM methods).

        info("*** Starting benchmark ***\n")
        h1, h2 = net["h1"], net["h2"]

        h2.cmd("iperf --trip-times --server &")
        output(h1.cmd(f"iperf --trip-times --client {h2.IP()}"))

        info("*** Stopping benchmark ***\n")
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
        help="Perform automatic benchmarks on the topology instead of entering to interactive CLI mode.",
    )

    args = parser.parse_args()

    setLogLevel("info")
    run(benchmark=args.benchmark)
