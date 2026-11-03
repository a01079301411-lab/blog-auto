#!/usr/bin/env bash
# 사용법: 프로젝트 루트에서  bash video/build_all.sh
set -e
cd "$(dirname "$0")/.."
run(){ n=$1; v=$2; d=out/${n}_$v
  python3 video/render2.py data/products/$n.json $v $d
  python3 video/audio.py $d/bgm.wav $d/plan.json
  ffmpeg -y -loglevel error -i $d/video_silent.mp4 -i $d/bgm.wav -map 0:v -map 1:a -c:v copy -c:a aac -b:a 192k -shortest $d/final.part.mp4
  mv $d/final.part.mp4 $d/insaengtem_${n}_$v.mp4; echo "DONE $n $v"; }
for n in seolleong egg shake shampoo; do run $n v1 & run $n v2 & run $n v3; wait; done
