#!/usr/bin/env python3

from ipaddress import IPv4Interface, IPv4Network
from mininet.topo import Topo
from mininet.net import Mininet
from mininet.cli import CLI
from mininet.node import Node
from mininet.link import TCLink
from mininet.log import setLogLevel, info


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
            # self.cmd(f"tc qdisc replace dev {intf} root dualpi2")
        self.cmd("sysctl -w net.ipv4.ip_forward=1")


class L4STopo(Topo):
    def build(self):
        net192 = IPv4Network("192.168.0.0/24")
        (r0_ip192, h1_ip, *_) = (
            IPv4Interface(f"{ip}/{net192.prefixlen}") for ip in net192.hosts()
        )

        net172 = IPv4Network("172.16.0.0/24")
        (r0_ip172, h2_ip, *_) = (
            IPv4Interface(f"{ip}/{net192.prefixlen}") for ip in net172.hosts()
        )

        router = self.addHost("r0", cls=DualPI2Router, ip=r0_ip192.with_prefixlen)

        h1 = self.addHost(
            "h1",
            cls=PragueHost,
            ip=h1_ip.with_prefixlen,
            defaultRoute=f"via {r0_ip192.ip}",
        )
        h2 = self.addHost(
            "h2",
            cls=PragueHost,
            ip=h2_ip.with_prefixlen,
            defaultRoute=f"via {r0_ip172.ip}",
        )

        s1, s2, *_ = (self.addSwitch(f"s{i}") for i in range(1, 2 + 1))

        self.addLink(
            s1,
            router,
            intfName2="r0-eth1",
            cls=TCLink,
            params2={"ip": r0_ip192.with_prefixlen},
        )
        self.addLink(
            s2,
            router,
            intfName2="r0-eth2",
            cls=TCLink,
            params2={"ip": r0_ip172.with_prefixlen},
        )

        for h, s in ((h1, s1), (h2, s2)):
            self.addLink(h, s)


def run():
    topo = L4STopo()
    net = Mininet(topo=topo, waitConnected=True)
    net.start()

    info("*** Routing Table on Router (r0) ***\n")
    info(net["r0"].cmd("ip route"))
    CLI(net)

    net.stop()


if __name__ == "__main__":
    setLogLevel("info")
    run()
