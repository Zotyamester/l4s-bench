#!/bin/bash

OUT=${OUT:-$PWD}
QLEN_FACTOR=${QLEN_FACTOR:-1}
BW=${BW:-32}
DELAY=${DELAY:-6}
DURATION=${DURATION:-60}

set -o xtrace
set -e

mkdir -p $OUT/results/{prague,new-reno}
./net.py --out-dir $OUT/results/prague --quic-benchmark --algorithm prague --bottleneck-bandwidth $BW --last-mile-delay $DELAY --measurement-duration $DURATION
./net.py --out-dir $OUT/results/new-reno --quic-benchmark --algorithm new-reno --bottleneck-bandwidth $BW --last-mile-delay $DELAY --measurement-duration $DURATION
./process-qlog.py --client $OUT/results/prague/h1.qlog --server $OUT/results/prague/h2.qlog > $OUT/results/prague/qlog.json
./process-qlog.py --client $OUT/results/new-reno/h1.qlog --server $OUT/results/new-reno/h2.qlog > $OUT/results/new-reno/qlog.json
./process-queues.py --kind dualpi2 $OUT/results/prague/queues.jsonl > $OUT/results/prague/queues.json
./process-queues.py --kind dualpi2 $OUT/results/new-reno/queues.jsonl > $OUT/results/new-reno/queues.json

. .venv/bin/activate # for matplotlib only
./plot.py \
    --qlog $OUT/results/prague/qlog.json:prague \
    --qlog $OUT/results/new-reno/qlog.json:new-reno \
    --queue $OUT/results/prague/queues.json:prague \
    --queue $OUT/results/new-reno/queues.json:new-reno \
    --queue-length-factor $QLEN_FACTOR \
    --bandwidth $BW \
    --round-trip-time $((4*$DELAY)) \
    $OUT/results/plot.png

chown -R $SUDO_USER:$SUDO_USER $OUT/results/
