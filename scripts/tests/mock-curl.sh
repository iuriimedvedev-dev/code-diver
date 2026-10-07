#!/usr/bin/env bash
set -eu
[[ "$*" == *'/health'* ]]
printf '%s\n' '{"status":"ok","service":"code-diver"}'