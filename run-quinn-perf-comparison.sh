#!/bin/bash

set -o xtrace
set -e

mkdir -p results/{prague,new-reno}
./net.py --out-dir results/prague --quic-benchmark --algorithm prague --bottleneck-bandwidth 32 --last-mile-delay 6 --measurement-duration 60
./net.py --out-dir results/new-reno --quic-benchmark --algorithm new-reno --bottleneck-bandwidth 32 --last-mile-delay 6 --measurement-duration 60
./process-qlog.py --client results/prague/h1.qlog --server results/prague/h2.qlog > results/prague/qlog.json
./process-qlog.py --client results/new-reno/h1.qlog --server results/new-reno/h2.qlog > results/new-reno/qlog.json
./process-queues.py --kind dualpi2 results/prague/queues.jsonl > results/prague/queues.json
./process-queues.py --kind dualpi2 results/new-reno/queues.jsonl > results/new-reno/queues.json

. .venv/bin/activate # for matplotlib only
./plot.py --qlog results/prague/qlog.json:prague --qlog results/new-reno/qlog.json:new-reno --queue results/prague/queues.json:prague --queue results/new-reno/queues.json:new-reno plot.png
