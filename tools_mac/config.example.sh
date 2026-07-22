#!/bin/bash
# CyberDog2 connection config (example - copy to config.sh and edit)
DogUser="mi"
DogHost="192.168.x.x"
DogTarget="${DogUser}@${DogHost}"

RemoteProgramDir="/home/mi/cyberdog_course/program"
LocalProgramDir="$(cd "$(dirname "$0")/../program" && pwd)"
LogDir="$(cd "$(dirname "$0")/../log" && pwd)"
