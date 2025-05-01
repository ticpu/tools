#!/bin/bash
# watch_out_of_order_writes.sh -- Report out-of-order sector writes with time/delta on a device
set -e

if [[ $# -ne 1 ]]; then
    echo "Usage: $0 /dev/sdX"
    exit 1
fi

DEVPATH="$1"

if [[ ! -b "$DEVPATH" ]]; then
    echo "Error: $DEVPATH is not a block device"
    exit 1
fi

# Get major and minor in hex
read MAJOR_HEX MINOR_HEX < <(stat -c "%t %T" "$DEVPATH")
MAJOR=$((0x$MAJOR_HEX))
MINOR=$((0x$MINOR_HEX))

# Compute dev id (major << 20 | minor)
DEVID=$(( MAJOR << 20 | MINOR ))
DEVID_HEX=$(printf "0x%x" $DEVID)

echo "Monitoring out-of-order writes on $DEVPATH (major=$MAJOR, minor=$MINOR, devid=$DEVID_HEX)"
echo "Press Ctrl+C to stop."

sudo bpftrace -e "
tracepoint:block:block_rq_issue
/ args->dev == $DEVID && args->rwbs == \"W\" /
{
  printf(\"%llu %u\\n\", nsecs, args->sector);
}" | awk '
NR == 1 {
  prev_sector = $2;
  prev_time = $1;
  prev_oo_time = 0;
  next
}
{
  # Time difference between current and previous event (in ms)
  delta = ($1 - prev_time) / 1e6;

  # Detect out-of-order sector
  if ($2 < prev_sector) {
    # Time since last out-of-order event (or since start if first)
    if (prev_oo_time == 0) {
      delta_oo = "N/A";
    } else {
      delta_oo = ($1 - prev_oo_time) / 1e9  # convert to seconds
      delta_oo = sprintf("%.3f s", delta_oo);
    }
    print "Out-of-order sector:", prev_sector, "->", $2, "at", $1, "ns (+", delta, "ms since prev event; +", delta_oo, "since last out-of-order)";
    prev_oo_time = $1;
  }
  prev_sector = $2;
  prev_time = $1;
}
'
