# ParkIQ — Smart Parking Lot Allocation & Billing System

A ready-to-run local web application built for the DBMS PBL reviews. It uses Flask + SQLite for a zero-server setup and includes the relational schema, transactions, allocation, ticketing, billing, reservations, tariffs, reporting and audit logging.

## Quick start

### Windows
1. Install Python 3.10 or later.
2. Extract this folder.
3. Open Command Prompt/PowerShell in the `ParkIQ` folder.
4. Run:

```powershell
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

5. Open http://127.0.0.1:5000 in your browser.

### macOS / Linux
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```
Then visit http://127.0.0.1:5000.

The database `parkiq.db` is created automatically on first run, with a sample parking lot, 30 slots, sample tariffs, and three demo active sessions.

## Features

- Dashboard with slot availability, occupancy, active tickets and daily revenue
- Slot map with filters by car, bike and EV
- Vehicle directory and registration
- Transaction-safe vehicle check-in and nearest compatible slot allocation
- Active sessions and checkout
- Billing: configurable hourly rate, grace period, daily cap, peak-hour multiplier, and active membership discount calculation
- Payment ledger (demo UPI/card/cash; no actual payment is taken)
- Reservations and cancellation
- Tariff settings for each vehicle type
- Reports for revenue, session duration, peak entry hours and audit trail
- 13 normalized relational tables, foreign keys and indexes

## Default demo tariffs
| Vehicle | Hourly rate | Daily cap | Grace |
|---|---:|---:|---:|
| Car | ₹30 | ₹250 | 15 minutes |
| Bike | ₹15 | ₹120 | 15 minutes |
| EV | ₹35 | ₹280 | 15 minutes |

The sample peak-hour multiplier is 1.5× for entry/exit hours 08:00, 09:00, 17:00, 18:00 and 19:00. Actual production tariff rules should be approved and tested before deployment.

## Main workflow
1. Open **Vehicle check-in**.
2. Enter the vehicle plate, type and optional owner details.
3. ParkIQ creates/reuses a vehicle record, allocates a compatible free slot, creates a ticket, and records a sensor event.
4. Open **Active sessions**, then select **Checkout & bill**.
5. Review the bill and select a demo payment method.
6. The app closes the ticket, records payment, releases the slot and logs the operation in one database transaction.
7. Use Reports and Analytics to review persisted records.

## Database tables
`UserAccount`, `Vehicle`, `ParkingLot`, `ParkingSlot`, `Tariff`, `Membership`, `Reservation`, `ParkingTicket`, `Payment`, `Penalty`, `Staff`, `AuditLog`, `SlotSensorEvent`.

## Important notes
- This is a runnable educational/local prototype, not a production payment or access-control system.
- SQLite is used so it can run immediately on a student laptop without a separate DB server. It supports real persisted data in `parkiq.db`.
- The accompanying `mysql_schema.sql` provides the MySQL 8 relational schema for the intended DBMS submission. Some engine-specific procedures/triggers should be adapted and tested in MySQL Workbench.
- Login/hashed passwords, enforced role authorization, scheduled reservation expiry, actual sensor hardware, online payments, HTTPS and production backups are not enabled in this local demo.
- Do not expose the Flask development server to the public internet.
- To reset all demo data, stop the app and delete `parkiq.db`; it will be recreated on the next launch.
