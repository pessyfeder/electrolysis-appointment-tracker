# Electrolysis Appointment Tracker

A local, offline desktop app for scheduling appointments, tracking clients, and recording payments for a solo electrolysis practice.

Built per `electrolysis-scheduler-spec.txt` (see repo root): Python 3.13 + PySide6 (Qt) + SQLite, packaged as a standalone Windows `.exe` with PyInstaller. No cloud, no network calls, no email/SMS — everything runs on one machine.

The application source lives in the [`electrolysis_scheduler/`](./electrolysis_scheduler) folder.

## What it does

- Admin password gate to open the app at all (bcrypt-hashed, never stored in plaintext)
- Week / Month calendar views. Week view shows only the actual open-for-business windows as self-contained cards, with blocked-time (hatched) blocks and status color coding
- Past dates are grayed out and locked from new bookings; existing appointments on a past day stay viewable so Admin can still see who was booked
- A "Next Available Appointment" indicator on the Appointments tab that jumps to and flashes the next open slot
- Business-hour, 15-minute-minimum, and 1–14-minute unbookable-gap enforcement (no separate "buffer time" concept — any gap under 15 minutes just isn't allowed)
- Multiple clients can share one appointment slot (e.g. a parent and child), each billed independently and sequentially
- Appointment form with click-to-suggest earliest start time, a pre-validated duration dropdown, and a date picker that blocks past dates
- Client quick-add/light-edit popup during booking (last name required, first name optional, phone required and auto-formatted)
- Start/End session timing with auto-calculated price ($2.50/min) per client on completion
- Payment recording, running client balance (credit/debt), and CSV export by date range
- Admin-password-gated client detail view (balance, full appointment/payment history, archive)
- A second admin-password gate specifically for editing business hours or blocking/unblocking time
- Local-only SQLite database — no cloud backup or sync by design

## Tech stack

| Layer | Choice |
|---|---|
| Language | Python 3.13 |
| GUI | PySide6 (Qt for Python) |
| Database | SQLite (local file, no server) |
| Packaging | PyInstaller (standalone Windows `.exe`) |

## Running it

You need Python 3.11+ with the packages in `electrolysis_scheduler/requirements.txt` installed (PySide6, bcrypt).

```bash
cd electrolysis_scheduler
pip install -r requirements.txt
python main.py
```

Or, on Windows, double-click `run.bat` inside the `electrolysis_scheduler/` folder.

### Building the standalone `.exe`

From inside `electrolysis_scheduler/`, with PyInstaller installed:

```bash
python -m PyInstaller --noconfirm ElectrolysisScheduler.spec
```

The finished app lands in `dist\ElectrolysisScheduler\ElectrolysisScheduler.exe`. Copy the whole `ElectrolysisScheduler` folder to the target machine — it needs no separate Python install to run.

## Where the data lives

All data is stored in a single SQLite file:

```
%APPDATA%\ElectrolysisScheduler\scheduler.db
```

(i.e. `C:\Users\<you>\AppData\Roaming\ElectrolysisScheduler\scheduler.db`)

There's no cloud backup by design — periodically copy that file to a USB drive or another folder to protect against disk failure.

## Resetting the admin password

The admin password is stored only as a bcrypt hash and can't be recovered if forgotten. To reset it without losing appointment/client data, open the database with any SQLite tool (e.g. DB Browser for SQLite) and run:

```sql
DELETE FROM settings WHERE key = 'admin_password_hash';
```

The next launch treats it as first-run and prompts for a new password.

## Project layout

```
electrolysis_scheduler/
├── main.py              Entry point (password gate -> main window)
├── app/                  Business logic: DB schema/migrations, CRUD models,
│                         auth, scheduling rules, billing/CSV export
├── ui/                   PySide6 views: login, calendar (week/month),
│                         appointment + client dialogs, billing, admin dialogs
├── requirements.txt
├── run.bat               Launch shortcut (Windows)
└── ElectrolysisScheduler.spec   PyInstaller build spec
```

More detail on features, data model, and design decisions is in `electrolysis-scheduler-spec.txt` at the repo root.
