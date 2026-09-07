"""Price calculation and CSV export for payments (spec 7.3)."""
import csv
from datetime import datetime

from app import models

RATE_PER_MINUTE = 2.50


def calculate_price(start_dt: datetime, end_dt: datetime) -> float:
    minutes = (end_dt - start_dt).total_seconds() / 60
    return round(minutes * RATE_PER_MINUTE, 2)


def export_payments_csv(path, start_dt, end_dt):
    payments = models.list_payments_between(start_dt, end_dt)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Date", "Client", "Amount", "Method", "Appointment ID", "Notes"])
        for p in payments:
            writer.writerow([
                p["paid_at"],
                f'{p["first_name"]} {p["last_name"]}',
                f'{p["amount"]:.2f}',
                p["method"],
                p["appointment_id"] or "",
                p["notes"] or "",
            ])
    return len(payments)
