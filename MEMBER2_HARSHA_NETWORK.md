# Member 2 (Harsha): Network / SDN lead

## Responsibilities

The Mininet network and the Ryu SDN controller.

## What I built

| File | What it does |
|---|---|
| `topology/exam_topo.py` | Campus-style Mininet topology: core switch s1, lab switches s2 and s3, 10 Mbps core links with OVS QoS queues (q0 best effort, q1 exam traffic with at least 8 Mbps), automated test run T1-T11 |
| `controller/exam_controller.py` | Ryu OpenFlow 1.3 controller: flow-table design, exam mode from app signals, seat whitelist, intruder and brute-force blocking, host-discovery protection, proxy ARP, seat isolation, queue selection, traffic monitoring, congestion detection, REST API |
| `scripts/install.sh` | Installs Mininet, Open vSwitch and Ryu (in a Python 3.9 environment) |

## Flow-table design

| Priority | Rule | Action |
|---|---|---|
| 400 | Signals to 10.0.0.254 | Send to controller |
| 310 / 300 | Blocked hosts, seat to seat | Drop (console host only for blocked) |
| 100 | Exam TCP connection (port 5000) | Queue q1 + forward |
| 10 | Other IPv4 traffic | Queue q0 + forward |
| 5 | ARP / L2 | Learning switch |
| 0 | Table-miss | Send to controller |

## Key design decisions

- **Slow core links on purpose:** congestion can be reproduced, and the priority queue's benefit can be measured.
- **The controller decides once per connection:** it installs a rule, and the switch handles the rest at line rate.
- **Intruders learn nothing:** unregistered hosts are blocked at their first ARP or IP packet towards an exam machine.

## How to test my part

```
~/ryu-venv/bin/python tests/test_controller.py
mininet> sh ovs-ofctl -O OpenFlow13 dump-flows s1
```
