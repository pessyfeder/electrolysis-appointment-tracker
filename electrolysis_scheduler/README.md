# Electrolysis Scheduler

A local, offline desktop app for scheduling appointments, tracking clients,
and recording payments for a solo electrolysis practice. Built per
`electrolysis_scheduler_spec.txt` (Draft v4.0): Python 3.13 + PySide6 (Qt) +
SQLite, packaged as a standalone Windows `.exe` with PyInstaller. No cloud,
no network calls, no email/SMS.

## What's included

- Admin password gate to open the app at all (bcrypt-hashed, never stored in plaintext)
- Week / Month calendar (no separate day view). Week shows only the actual
  open-for-business windows as self-contained cards (e.g. a separate morning
  card and evening card) — closed time isn't rendered at all — with
  blocked-time (hatched) blocks and status color coding within each card
- Past dates are grayed out and locked from new bookings on both the month
  and week views; existing appointments already booked on a past day stay
  clickable so Admin can still view who was booked
- A "Next Available Appointment" label on the Appointments tab, always kept
  up to date; click it to jump to and flash that slot
- Business-hour + 15-minute-minimum + 1–14-minute unbookable-gap enforcement
- Appointments can have more than one client on the same slot, each billed
  independently and sequentially (Start/End Session per client, with an
  auto-suggested "start the next client" prompt when one finishes)
- Appointment form: click-to-suggest earliest start time, a pre-validated
  duration dropdown, and a date picker that blocks past dates for new
  appointments
- Client quick-add/light-edit popup during booking — last name required,
  first name optional, phone required and auto-formatted as
  `(XXX) XXX-XXXX`, no notes field
- Start/End session timing → auto-calculated price ($2.50/min) on completion,
  per client
- Payments, running client balance (credit/debt), CSV export by date range
- Admin-password-gated client detail view (balance, full appointment/payment
  history, archive) reachable by double-clicking a client in the Billing tab
- Second admin-password gate specifically for editing business hours,
  blocking/unblocking time, or viewing client details (spec 7.4)
- Local-only SQLite database in `%APPDATA%\ElectrolysisScheduler\scheduler.db`

## Project layout

```
main.py                   Entry point (password gate -> main window)
app/
  db.py                    Schema (appointments + appointment_clients join table) + migration + connection
  models.py                CRUD for clients/appointments/appointment_clients/payments/blocked_times/business_hours
  auth.py                  bcrypt password hashing/verification
  scheduling.py            Business-hours + gap + conflict validation, duration options, start-time suggestion
  billing.py                Price calculation, CSV export
  paths.py, util.py         App-data directory, phone/name formatting helpers
ui/
  login_dialog.py           Password gate (first-run setup + unlock)
  main_window.py             Tabs (Appointments / Billing) + Admin menu
  calendar_view.py            Week grid of business-hours cards, toolbar, navigation, past-day graying
  month_view.py                Month grid, past days grayed, every day routes to week view
  appointment_dialog.py        Book/edit; multiple clients per slot, each with independent Start/End-session/cancel/no-show
  client_dialog.py              Quick-add/light-edit popup (last name + phone required, first name optional) used during booking
  client_detail_dialog.py        Admin-gated balance + full history + archive (opened from Billing)
  billing_view.py                 Record payments, balances, CSV export, client detail launcher
  block_time_dialog.py             Block a slot/day off (reason required)
  business_hours_dialog.py          Edit weekly business hours (Phase 3, admin-gated)
```

## Running it

You need a Python 3.11+ environment with the packages in `requirements.txt`
(`PySide6`, `bcrypt`) installed.

**If you have a normal Python install:**
```bash
pip install -r requirements.txt
python main.py
```

**This machine's setup:** a full "installer" Python could not be installed
silently in this environment (Windows blocked the unattended UAC elevation
step). Instead, a self-contained, no-install Python 3.13 was set up at:
```
C:\Users\User\AppData\Local\Programs\PythonEmbed313\python.exe
```
It already has `PySide6`, `bcrypt`, and `pyinstaller` installed and has been
verified to run the app. To use it directly:
```bash
C:\Users\User\AppData\Local\Programs\PythonEmbed313\python.exe main.py
```
or double-click `run.bat` in this folder.

If you'd rather have a normal, on-PATH Python for everyday development,
double-click `python-3.13.15-amd64.exe` in your Downloads folder yourself
(approve the UAC prompt when Windows asks) — that only fails in unattended/
scripted installs, not when you run it interactively.

## Building the standalone .exe (PyInstaller)

Already built once as a smoke test — see `dist\ElectrolysisScheduler\ElectrolysisScheduler.exe`.
To rebuild after making changes:
```bash
C:\Users\User\AppData\Local\Programs\PythonEmbed313\python.exe -m PyInstaller --noconfirm ElectrolysisScheduler.spec
```
The finished app is `dist\ElectrolysisScheduler\ElectrolysisScheduler.exe` —
copy the whole `ElectrolysisScheduler` folder wherever you want to run it
from; it needs no Python install on the target machine.

## Where the data lives / backups

All data is in a single SQLite file:
```
%APPDATA%\ElectrolysisScheduler\scheduler.db
```
(i.e. `C:\Users\<you>\AppData\Roaming\ElectrolysisScheduler\scheduler.db`)

There is no cloud backup by design (spec 7.5/9). Periodically copy that file
to a USB drive or another folder to protect against disk failure — Phase 3
in the spec calls out a future in-app "copy database file to..." button as
an optional enhancement if this becomes a concern.

## Password reset

The admin password is stored only as a bcrypt hash (`settings` table, key
`admin_password_hash`) — it can't be recovered if forgotten. To reset it
without losing appointment/client data, open the database with any SQLite
tool (e.g. DB Browser for SQLite) and delete that one row:
```sql
DELETE FROM settings WHERE key = 'admin_password_hash';
```
The next launch will treat it as first-run and prompt to set a new password.

## Notes / things to know

- Business hours default to the table in spec section 7.1 and can be edited
  from the **Admin → Edit Business Hours…** menu (requires the admin
  password again, per spec 7.4).
- Right-click an empty slot on the calendar to block that time off; left-click
  an existing blocked (hatched) block to remove it — both require the admin
  password.
- Appointments are never hard-deleted; cancel or mark no-show instead, so
  history stays intact for billing/reporting.
