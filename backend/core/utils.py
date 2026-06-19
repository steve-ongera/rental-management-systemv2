from decimal import Decimal

from django.utils import timezone

from .models import Payment, PaymentAllocation


def compute_outstanding_balance(tenancy):
    """
    Computes how much rent is owed for the CURRENT month, based on whether
    a PaymentAllocation already covers it. Used to flag tenants who are
    behind on rent on the owner dashboard / tenant dashboard.
    """
    today = timezone.now().date()
    covered = PaymentAllocation.objects.filter(
        payment__tenancy=tenancy,
        payment__payment_type=Payment.PaymentType.RENT,
        payment__status=Payment.Status.COMPLETED,
        period_year=today.year,
        period_month=today.month,
    ).exists()

    if covered:
        return Decimal("0.00")
    return tenancy.agreed_rent


def get_effective_due_date(tenancy):
    """
    Returns the effective rent due-date for the current month: either the
    standard rent_due_day (default 5th), or an office-granted extension if
    one is set on the tenancy for the current period.
    """
    today = timezone.now().date()
    if tenancy.extended_due_date and tenancy.extended_due_date.month == today.month \
            and tenancy.extended_due_date.year == today.year:
        return tenancy.extended_due_date

    try:
        return today.replace(day=tenancy.rent_due_day)
    except ValueError:
        # e.g. rent_due_day=31 in a 30-day month -> fall back to last day
        import calendar
        last_day = calendar.monthrange(today.year, today.month)[1]
        return today.replace(day=last_day)


def is_rent_overdue(tenancy):
    today = timezone.now().date()
    due_date = get_effective_due_date(tenancy)
    return today > due_date and compute_outstanding_balance(tenancy) > 0


def months_paid_ahead(tenancy, payment_type=Payment.PaymentType.RENT):
    """
    Returns how many consecutive months ahead of the current month
    have already been paid/allocated for this tenancy (used to enforce
    and display the 5-10 month advance payment cap).
    """
    today = timezone.now().date()
    allocations = (
        PaymentAllocation.objects.filter(
            payment__tenancy=tenancy,
            payment__payment_type=payment_type,
            payment__status=Payment.Status.COMPLETED,
        )
        .values_list("period_year", "period_month")
        .distinct()
    )
    future_periods = [
        (y, m) for (y, m) in allocations
        if (y > today.year) or (y == today.year and m >= today.month)
    ]
    return len(future_periods)