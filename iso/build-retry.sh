#!/bin/bash
# retries build.sh when deb.debian.org flakes (HTTP 500)
cd "$(dirname "$0")"
for i in 1 2 3 4 5 6; do
  until curl -s --max-time 20 -o /dev/null -w "%{http_code}" http://deb.debian.org/debian/dists/trixie/InRelease | grep -q 200; do sleep 30; done
  echo "=== attempt $i $(date)" >> build/attempts.log
  ./build.sh > build/build.log 2>&1 && grep -q "Build completed successfully" build/build.log && { echo ok >> build/attempts.log; exit 0; }
  sleep 60
done; exit 1
