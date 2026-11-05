# Member 1 (Uday): Application lead

## Responsibilities

The exam application, built on raw TCP sockets, and the student web portal.

## What I built

| File | What it does |
|---|---|
| `app/protocol.py` | Message format: 4-byte length + JSON, and `recv_exact` so partial TCP reads never split a message |
| `app/exam_server.py` | Concurrent exam server: one thread per student (capped by a semaphore), login, questions one at a time, server-side timer, resume after disconnect, grading, results CSV |
| `app/exam_client.py` | Terminal client with an interactive mode and an `--auto` mode for tests; records the response time of every request |
| `app/minihttp.py` | Small HTTP/1.1 server written on raw sockets (no framework) |
| `app/student_portal.py`, `app/web/student.html` | Student exam page on every seat: login, countdown, questions, result and review |
| `data/questions.json`, `data/students.json` | Question bank and demo student accounts |

## Key design decisions

- **TCP, not UDP:** exam answers must not be lost or arrive out of order.
- **Length-prefixed framing:** TCP is a byte stream, so every message carries its length.
- **The timer lives on the server:** the remaining time is used as the socket timeout, so a silent or cheating client is still cut off and auto-submitted.
- **One session per student:** duplicate logins and re-submissions are refused; a dropped student resumes with the same deadline.
- **Overload safety:** when all slots are busy, a new client gets a clean "server full" error instead of crashing the server.

## How to test my part

```
python3 tests/test_local.py
```
