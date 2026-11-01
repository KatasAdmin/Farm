"""Pure validation of Telegram Stars payment notifications.

The database transaction still owns the final idempotency check.
"""


def matches_order(order, message):
    payment = message.get("successful_payment") or {}
    return (
        order.get("status") == "created"
        and order.get("telegram_id") == (message.get("from") or {}).get("id")
        and payment.get("currency") == "XTR"
        and type(payment.get("total_amount")) is int
        and payment["total_amount"] == order.get("stars")
        and payment.get("invoice_payload") == order.get("id")
        and isinstance(payment.get("telegram_payment_charge_id"), str)
        and bool(payment["telegram_payment_charge_id"])
    )
