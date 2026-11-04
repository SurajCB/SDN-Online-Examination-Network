# Test Plan

## Level 1 — Without Mininet (any Linux/macOS machine)

```bash
python3 tests/test_local.py                      # protocol, server, portal and console tests (16 tests)
source ~/ryu-venv/bin/activate
python tests/test_controller.py                  # controller logic with a mocked switch (18 tests)
```

| ID | Test | Expected |
|---|---|---|
| L1–L4 | Frame round-trip, byte-by-byte fragmented frame, oversized frame, closed peer | Decoded correctly / `ProtocolError` / `ConnectionClosed` |
| L5 | `exam_start` signal emitted at startup | Fake controller receives event with 6 allowed IPs |
| L6 | 4 concurrent auto clients | All `completed`, 10 answers each, metrics rows written |
| L7 | Re-login after submission | `LOGIN_FAIL: exam already submitted` |
| L8 | 3 wrong PINs | 3 × `LOGIN_FAIL`, `auth_fail` count reaches 3 |
| L9 | Disconnect after 1 answer, log back in | `LOGIN_OK resumed=true answered=1` |
| L10 | Idle student | `TIME_UP` then `RESULT status=timeout` |
| C1–C17 | Controller: ARP for 10.0.0.254, exam_start, bad token, spoofed signal, exam flow on queue 1, other flow on queue 0, unauthorised host blocked (IP + ARP), ARP scan gets nothing, probe of a seat blocked, console host still reachable, seat isolation, proxy ARP, auth-fail threshold, exam_end unblocks, new run resets state, no queue outside exam mode, flow-table snapshot | All pass |

## Level 2 — Mininet end-to-end (D1 demo)

Terminal 1: `./scripts/run_controller.sh`  ·  Terminal 2: `./scripts/run_demo.sh`

| ID | Scenario | How | Pass condition |
|---|---|---|---|
| T1 | Connectivity | `pingall` | 0 % loss |
| T2 | App → SDN signal | server starts on srv | `/exam/status` shows `exam_active: true` + whitelist |
| T3 | Concurrent TCP clients | 3 auto clients on st1–st3 at once | all connect and finish |
| T4 | Unauthorised host | client on intr (10.0.0.66) | SYN dropped, `10.0.0.66` in `blocked` |
| T5 | Results | results CSV | 3/3 students have a row |
| T6 | Timer | the last student (Suraj, st3) thinks 8–10 s/question with a 60 s limit | status `timeout` |
| T7 | Brute force | 3 wrong passwords from st3 | `10.0.0.13` in `blocked` |
| T8 | Monitoring | `/exam/stats` | exam_bytes > 0 |
| T9 | Exam end | SIGINT to server | `exam_active: false`, blocks removed |
| T10 | Host discovery | st4 (unassigned) pings a seat and the server | No replies; `10.0.0.14` blocked with reason "probed exam host" |
| T11 | Seat isolation | st1 pings st2 | No reply; controller logs `seat_isolation` for 10.0.0.11 → 10.0.0.12 |

The demo prints PASS/FAIL for each and a summary. Logs: `logs/<tag>_*.log`, results: `results/`.

## Level 2b — Web portal demo

Terminal 1: `./scripts/run_controller.sh`  ·  Terminal 2: `./scripts/run_portal.sh`  ·  Firefox on the Ubuntu desktop

| ID | Scenario | Pass condition |
|---|---|---|
| W1 | Open `http://localhost:9000` and log in with the console password | Console shows "Exam running", 3 switches, 3 students "Not joined" |
| W2 | Log in as Harsha at `http://10.0.0.11:8000` | Question 1 appears with a countdown; console shows Harsha "In exam" |
| W3 | Answer and submit | Result page with score and review; console shows "Submitted" and the score |
| W4 | Log in at `http://10.0.0.66:8000` | "Cannot reach the exam server" error; Integration tab lists 10.0.0.66 as blocked |
| W5 | 3 wrong passwords at `http://10.0.0.13:8000` | Console shows failed-login events, then 10.0.0.13 blocked |
| W6 | Click Unblock for 10.0.0.13 (Integration tab) | The seat can log in again |

| W7 | `./scripts/run_public.sh`, open the student link on a phone using mobile data | Seat picker loads; picking a seat and logging in works; the console shows the student |
| W8 | Open the console link on another device | Password page; wrong password refused; correct password opens all 5 tabs |
| W9 | Console → Testing tab | Live checks all PASS while the exam is running |
| W11 | 3 wrong passwords on Seat 1 from a phone, then pick Seat 2 on the same phone | "Device blocked" on every seat; another phone can still log in on Seat 1; Unblock under "Blocked devices" frees it |
| W10 | View source of the seat picker and exam page, and open `/seats/api` | No IP addresses, host names, server address or student names |

## Manual checks for the viva

```bash
mininet> sh ovs-ofctl -O OpenFlow13 dump-flows s1          # see cookies 0xe1/0xe2/0xe3 and set_queue
mininet> sh ovs-vsctl list queue                            # q0/q1 configuration
mininet> sh ovs-ofctl -O OpenFlow13 queue-stats s1
mininet> st1 python3 app/exam_client.py --id Harsha --pin 'Harsha@123'   # interactive exam
$ ./scripts/status.sh                                        # controller state + events
$ curl -X POST localhost:8080/exam/block/10.0.0.12           # manual block, then st2 cannot connect
```

## Level 3 — D2 experiments (prepared)

| Experiment | Command (controller env → topology flags) |
|---|---|
| Baseline, no load | `EXAM_PRIORITIZE=0` → `--demo --tag base_idle` |
| Baseline, congested | `EXAM_PRIORITIZE=0` → `--demo --congestion --tag base_cong` |
| SDN QoS, no load | `EXAM_PRIORITIZE=1` → `--demo --tag sdn_idle` |
| SDN QoS, congested | `EXAM_PRIORITIZE=1` → `--demo --congestion --tag sdn_cong` |

Then `python3 tools/analyze.py --plot results/rtt.png` prints avg/p95/max RTT and Jain's fairness per scenario.
