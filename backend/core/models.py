import uuid
from decimal import Decimal

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone


# ---------------------------------------------------------------------------
# USER
# ---------------------------------------------------------------------------

class User(AbstractUser):
    """
    Single custom user model shared by both portals.
    role determines which dashboard/permissions apply on the frontend.
    """

    class Role(models.TextChoices):
        OWNER = "OWNER", "Owner"
        TENANT = "TENANT", "Tenant"

    role = models.CharField(max_length=10, choices=Role.choices, default=Role.TENANT)
    phone_number = models.CharField(max_length=15, unique=True, help_text="Format: 2547XXXXXXXX")
    id_number = models.CharField(max_length=20, blank=True, null=True)
    profile_photo = models.ImageField(upload_to="profiles/", blank=True, null=True)
    next_of_kin_name = models.CharField(max_length=150, blank=True, null=True)
    next_of_kin_phone = models.CharField(max_length=15, blank=True, null=True)
    is_active_account = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.get_full_name() or self.username} ({self.role})"

    @property
    def is_owner(self):
        return self.role == self.Role.OWNER

    @property
    def is_tenant(self):
        return self.role == self.Role.TENANT


# ---------------------------------------------------------------------------
# PROPERTY STRUCTURE: Flat -> Room
# ---------------------------------------------------------------------------

class Flat(models.Model):
    """
    A physical apartment building / estate owned by an Owner.
    e.g. Kalungu Square (Kasarani), Kwetu Apartments (Mlolongo), Tsavo (Umoja)
    """

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="flats",
        limit_choices_to={"role": "OWNER"},
    )
    name = models.CharField(max_length=150)
    location = models.CharField(max_length=200, help_text="e.g. Kasarani, Mlolongo, Umoja")
    address = models.CharField(max_length=255, blank=True)
    description = models.TextField(blank=True)
    image = models.ImageField(upload_to="flats/", blank=True, null=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        unique_together = ("owner", "name")

    def __str__(self):
        return f"{self.name} - {self.location}"

    @property
    def total_rooms(self):
        return self.rooms.count()

    @property
    def occupied_rooms_count(self):
        return self.rooms.filter(status=Room.Status.OCCUPIED).count()

    @property
    def vacant_rooms_count(self):
        return self.rooms.filter(status=Room.Status.VACANT).count()


class Room(models.Model):
    """
    A rentable unit within a Flat. e.g. Bedsitter A1, 1BR-204, 3BR-Penthouse
    """

    class RoomType(models.TextChoices):
        BEDSITTER = "BEDSITTER", "Bedsitter"
        ONE_BEDROOM = "ONE_BEDROOM", "One Bedroom"
        TWO_BEDROOM = "TWO_BEDROOM", "Two Bedroom"
        THREE_BEDROOM = "THREE_BEDROOM", "Three Bedroom"
        SINGLE_ROOM = "SINGLE_ROOM", "Single Room"

    class Status(models.TextChoices):
        VACANT = "VACANT", "Vacant"
        OCCUPIED = "OCCUPIED", "Occupied"
        MAINTENANCE = "MAINTENANCE", "Under Maintenance"

    flat = models.ForeignKey(Flat, on_delete=models.CASCADE, related_name="rooms")
    room_number = models.CharField(max_length=30, help_text="e.g. A1, 204, G-03")
    room_type = models.CharField(max_length=20, choices=RoomType.choices, default=RoomType.BEDSITTER)
    floor = models.CharField(max_length=20, blank=True)
    status = models.CharField(max_length=15, choices=Status.choices, default=Status.VACANT)

    # rent & charges
    monthly_rent = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])
    deposit_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    water_bill_amount = models.DecimalField(
        max_digits=8, decimal_places=2, default=Decimal("0.00"),
        help_text="Fixed monthly water charge for this room",
    )

    # features
    has_balcony = models.BooleanField(default=False)
    has_shower = models.BooleanField(default=False)
    has_tiles = models.BooleanField(default=False)
    has_wardrobe = models.BooleanField(default=False)
    has_parking = models.BooleanField(default=False)
    extra_features = models.TextField(blank=True, help_text="Any other features, comma separated")

    image = models.ImageField(upload_to="rooms/", blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["flat", "room_number"]
        unique_together = ("flat", "room_number")

    def __str__(self):
        return f"{self.flat.name} - {self.room_number} ({self.get_room_type_display()})"

    @property
    def current_tenancy(self):
        return self.tenancies.filter(status=Tenancy.Status.ACTIVE).first()


# ---------------------------------------------------------------------------
# TENANCY: the link between a Tenant and a Room over a period of time
# ---------------------------------------------------------------------------

class Tenancy(models.Model):
    """
    Represents a tenant's occupation of a room for a period.
    History is preserved: when a tenant moves out or switches rooms,
    the old Tenancy is closed (status=ENDED) rather than deleted,
    so the owner can still see historical records.
    """

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        ENDED = "ENDED", "Ended"
        PENDING = "PENDING", "Pending Move-in"

    tenant = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="tenancies",
        limit_choices_to={"role": "TENANT"},
    )
    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name="tenancies")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)

    move_in_date = models.DateField(default=timezone.now)
    move_out_date = models.DateField(blank=True, null=True)

    agreed_rent = models.DecimalField(max_digits=10, decimal_places=2)
    agreed_deposit = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    deposit_paid = models.BooleanField(default=False)

    # rent due-day rule (Nairobi convention: due by the 5th, can be extended by office)
    rent_due_day = models.PositiveSmallIntegerField(default=5)
    extended_due_date = models.DateField(
        blank=True, null=True,
        help_text="If owner/office grants an extension for the current period",
    )

    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-move_in_date"]
        verbose_name_plural = "Tenancies"

    def __str__(self):
        return f"{self.tenant} @ {self.room} [{self.status}]"

    def end_tenancy(self, move_out_date=None):
        self.status = self.Status.ENDED
        self.move_out_date = move_out_date or timezone.now().date()
        self.save()
        # free up the room if no other active tenancy exists
        if not self.room.tenancies.filter(status=Tenancy.Status.ACTIVE).exclude(pk=self.pk).exists():
            self.room.status = Room.Status.VACANT
            self.room.save()


# ---------------------------------------------------------------------------
# PAYMENTS (rent + water), with month-allocation for advance/lump payments
# ---------------------------------------------------------------------------

class Payment(models.Model):
    """
    A single payment transaction made by a tenant (or recorded by office staff
    for a cash payment). A payment can be for RENT or WATER, and can cover
    one month or be a lump sum that gets allocated across several future
    months via PaymentAllocation records.
    """

    class PaymentType(models.TextChoices):
        RENT = "RENT", "Rent"
        WATER = "WATER", "Water Bill"
        DEPOSIT = "DEPOSIT", "Deposit"

    class Method(models.TextChoices):
        CASH = "CASH", "Cash (Office)"
        MPESA = "MPESA", "M-Pesa Online"

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        COMPLETED = "COMPLETED", "Completed"
        FAILED = "FAILED", "Failed"

    reference = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    tenancy = models.ForeignKey(Tenancy, on_delete=models.CASCADE, related_name="payments")
    payment_type = models.CharField(max_length=10, choices=PaymentType.choices, default=PaymentType.RENT)
    method = models.CharField(max_length=10, choices=Method.choices, default=Method.CASH)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)

    amount = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])
    months_covered = models.PositiveSmallIntegerField(
        default=1, help_text="How many months this lump payment should be allocated across",
    )

    # M-Pesa specific
    mpesa_checkout_request_id = models.CharField(max_length=100, blank=True, null=True)
    mpesa_receipt_number = models.CharField(max_length=50, blank=True, null=True)
    phone_used = models.CharField(max_length=15, blank=True, null=True)

    # who recorded it (office staff / owner) for cash payments
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="payments_recorded",
    )

    notes = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_payment_type_display()} - {self.amount} - {self.tenancy.tenant} [{self.status}]"

    def allocate_to_months(self):
        """
        Splits this completed RENT/WATER payment across `months_covered`
        consecutive months starting from the next unpaid period, creating
        PaymentAllocation rows. Called once status becomes COMPLETED.
        """
        if self.status != self.Status.COMPLETED:
            return
        if self.allocations.exists():
            return  # already allocated

        per_month = (self.amount / self.months_covered).quantize(Decimal("0.01"))
        start = PaymentAllocation.get_next_unallocated_period(self.tenancy, self.payment_type)

        year, month = start
        remaining = self.amount
        for i in range(self.months_covered):
            this_month_amount = per_month if i < self.months_covered - 1 else remaining - per_month * i
            PaymentAllocation.objects.create(
                payment=self,
                period_year=year,
                period_month=month,
                amount=this_month_amount,
            )
            month += 1
            if month > 12:
                month = 1
                year += 1


class PaymentAllocation(models.Model):
    """
    Links a Payment to the specific calendar month(s) it pays for.
    This is what lets a tenant pay 5-10 months in advance in one go,
    while the system still knows exactly which months are settled.
    """

    payment = models.ForeignKey(Payment, on_delete=models.CASCADE, related_name="allocations")
    period_year = models.PositiveSmallIntegerField()
    period_month = models.PositiveSmallIntegerField()  # 1-12
    amount = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        ordering = ["period_year", "period_month"]
        unique_together = ("payment", "period_year", "period_month")

    def __str__(self):
        return f"{self.period_month}/{self.period_year} - {self.amount}"

    @staticmethod
    def get_next_unallocated_period(tenancy, payment_type):
        """
        Finds the next calendar month (year, month) that has not yet been
        paid for, for this tenancy + payment type. Starts from the tenancy's
        move-in month if nothing has been paid yet.
        """
        last = (
            PaymentAllocation.objects.filter(
                payment__tenancy=tenancy,
                payment__payment_type=payment_type,
                payment__status=Payment.Status.COMPLETED,
            )
            .order_by("-period_year", "-period_month")
            .first()
        )
        if last:
            year, month = last.period_year, last.period_month
            month += 1
            if month > 12:
                month = 1
                year += 1
            return (year, month)

        today = timezone.now().date()
        move_in = tenancy.move_in_date
        if move_in.year > today.year or (move_in.year == today.year and move_in.month > today.month):
            return (move_in.year, move_in.month)
        return (today.year, today.month)


# ---------------------------------------------------------------------------
# MAINTENANCE REQUESTS
# ---------------------------------------------------------------------------

class MaintenanceRequest(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        IN_PROGRESS = "IN_PROGRESS", "In Progress"
        RESOLVED = "RESOLVED", "Resolved"
        REJECTED = "REJECTED", "Rejected"

    class Priority(models.TextChoices):
        LOW = "LOW", "Low"
        MEDIUM = "MEDIUM", "Medium"
        HIGH = "HIGH", "High"
        URGENT = "URGENT", "Urgent"

    tenancy = models.ForeignKey(Tenancy, on_delete=models.CASCADE, related_name="maintenance_requests")
    title = models.CharField(max_length=150)
    description = models.TextField()
    priority = models.CharField(max_length=10, choices=Priority.choices, default=Priority.MEDIUM)
    status = models.CharField(max_length=15, choices=Status.choices, default=Status.PENDING)

    owner_notes = models.TextField(blank=True)
    cost = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    image = models.ImageField(upload_to="maintenance/", blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    resolved_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.title} - {self.tenancy.room} [{self.status}]"

    def mark_resolved(self):
        self.status = self.Status.RESOLVED
        self.resolved_at = timezone.now()
        self.save()


# ---------------------------------------------------------------------------
# ROOM SWITCH REQUESTS
# ---------------------------------------------------------------------------

class SwitchRequest(models.Model):
    """
    Tenant requests to move from their current room to a different room
    (could be a different flat entirely). On approval the old Tenancy is
    closed and a new Tenancy is created, preserving full history.
    """

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"

    current_tenancy = models.ForeignKey(
        Tenancy, on_delete=models.CASCADE, related_name="switch_requests_from",
    )
    requested_room = models.ForeignKey(
        Room, on_delete=models.CASCADE, related_name="switch_requests_to",
    )
    reason = models.TextField(blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    owner_response_notes = models.TextField(blank=True)

    new_tenancy = models.ForeignKey(
        Tenancy, on_delete=models.SET_NULL, null=True, blank=True, related_name="switch_request_origin",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    decided_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.current_tenancy.tenant} -> {self.requested_room} [{self.status}]"

    def approve(self):
        if self.requested_room.status != Room.Status.VACANT:
            raise ValueError("Requested room is not vacant.")

        old_tenancy = self.current_tenancy
        old_tenancy.end_tenancy()

        new_tenancy = Tenancy.objects.create(
            tenant=old_tenancy.tenant,
            room=self.requested_room,
            status=Tenancy.Status.ACTIVE,
            move_in_date=timezone.now().date(),
            agreed_rent=self.requested_room.monthly_rent,
            agreed_deposit=self.requested_room.deposit_amount,
        )
        self.requested_room.status = Room.Status.OCCUPIED
        self.requested_room.save()

        self.new_tenancy = new_tenancy
        self.status = self.Status.APPROVED
        self.decided_at = timezone.now()
        self.save()
        return new_tenancy

    def reject(self, notes=""):
        self.status = self.Status.REJECTED
        self.owner_response_notes = notes
        self.decided_at = timezone.now()
        self.save()


# ---------------------------------------------------------------------------
# DEADLINE EXTENSION REQUESTS (rent due-date extension via office)
# ---------------------------------------------------------------------------

class DeadlineExtensionRequest(models.Model):
    """
    Nairobi convention: rent is due by the 5th of the month. If a tenant
    cannot pay by then, they can request an extension from the office.
    """

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"

    tenancy = models.ForeignKey(Tenancy, on_delete=models.CASCADE, related_name="extension_requests")
    period_year = models.PositiveSmallIntegerField()
    period_month = models.PositiveSmallIntegerField()
    requested_new_date = models.DateField()
    reason = models.TextField(blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    decided_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.tenancy.tenant} ext.request {self.period_month}/{self.period_year} [{self.status}]"

    def approve(self):
        self.status = self.Status.APPROVED
        self.decided_at = timezone.now()
        self.save()
        self.tenancy.extended_due_date = self.requested_new_date
        self.tenancy.save()

    def reject(self):
        self.status = self.Status.REJECTED
        self.decided_at = timezone.now()
        self.save()


# ---------------------------------------------------------------------------
# RELOCATION ADVANCE DEPOSIT REQUEST
# ---------------------------------------------------------------------------

class RelocationDepositRequest(models.Model):
    """
    A tenant who knows they'll be relocating to a new room/flat one month
    (or more) early can request to pay the deposit for the new place in
    advance, ahead of actually moving.
    """

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"
        PAID = "PAID", "Paid"

    tenant = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="relocation_requests",
        limit_choices_to={"role": "TENANT"},
    )
    target_room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name="relocation_requests")
    intended_relocation_date = models.DateField()
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    decided_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.tenant} -> {self.target_room} advance deposit [{self.status}]"