#!/usr/bin/env python3

import itertools
from csv import DictReader
from argparse import ArgumentParser, BooleanOptionalAction
from ipaddress import IPv4Interface, IPv4Network
from tempfile import NamedTemporaryFile

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
        self.cmd("sysctl -w net.ipv4.tcp_ecn=3")
        self.cmd("sysctl -w net.ipv4.tcp_congestion_control=prague")


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
                # f"   limit {10000} target {100}ms"
            )

            info(f"\n{intf}: bw={bw_set}mbit delay={delay_set}ms")

        self.cmd("sysctl -w net.ipv4.ip_forward=1")


class L4STopo(Topo):
    """
    Represents a star topology with a single router (`r0`) connecting
    several (see `n_net`) switched LAN segments. Each LAN consists of a single
    switch (`si`) connected to a handful (see `n_host`) of hosts (`hi`).
    """

    def build(self, n_net: int = 2, _n_host: int = 1):
        BASE_SUBNET = IPv4Network("10.0.0.0/8")

        # make a list of `n_net` /24 subnets in the `BASE_SUBNET`
        nets = [
            tuple(
                IPv4Interface(f"{ip}/{neti.prefixlen}") for ip in neti.hosts()
            )  # a given subnet shall be immutable, hence the tuple
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

            # TODO: here, we could make use of the `n_host` param, but it would
            #       require a change in the naming scheme
            hi = self.addHost(
                f"h{i}",
                cls=PragueHost,
                ip=hi_ip.with_prefixlen,
                defaultRoute=f"via {r0_i_ip.ip}",
            )

            self.addLink(hi, si)  # , cls=TCLink, delay="50ms", bw=10)


def run(benchmark: bool = False):
    """
    Setup the `L4STopology` with the specified parameters and benchmark the
    performance or show the interactive Mininet console.

    :param benchmark: Perform benchmarks instead of entering to CLI mode.
    """

    topo = L4STopo()
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

        tf = NamedTemporaryFile()
        h2.cmd(f"iperf --trip-times --reportstyle C --output {tf.name} --server &")
        client_output = h1.cmd(f"iperf --trip-times --reportstyle C --client {h2.IP()}")
        server_output = tf.read().decode("utf-8")

        FIELDS = ("timestamp", "src_ip", "src_port", "dst_ip", "dst_port", "id", "interval", "transferred_bytes", "bits_per_second")
        client_table = DictReader([client_output], fieldnames=FIELDS)
        server_table = DictReader([server_output], fieldnames=FIELDS)

        info("*** Client stats:\n")
        output("\n".join((str(row) for row in client_table)) + "\n")
        info("*** Server stats:\n")
        output("\n".join((str(row) for row in server_table)) + "\n")
        info("*** Router stats:\n")
        output(r0.cmd("tc -s qdisc show dev r0-eth1"))
        output(r0.cmd("tc -s qdisc show dev r0-eth2"))

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

    args = parser.parse_args()

    setLogLevel("info")
    run(benchmark=args.benchmark)
