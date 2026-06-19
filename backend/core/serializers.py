from django.contrib.auth import authenticate
from django.db import transaction
from django.utils import timezone
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from .models import (
    DeadlineExtensionRequest,
    Flat,
    MaintenanceRequest,
    Payment,
    PaymentAllocation,
    RelocationDepositRequest,
    Room,
    SwitchRequest,
    Tenancy,
    User,
)


# ---------------------------------------------------------------------------
# AUTH / USER
# ---------------------------------------------------------------------------

class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    """Adds role/profile info into the JWT payload + login response."""

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token["role"] = user.role
        token["full_name"] = user.get_full_name() or user.username
        return token

    def validate(self, attrs):
        data = super().validate(attrs)
        data["user"] = UserSerializer(self.user).data
        return data


class UserSerializer(serializers.ModelSerializer):
    full_name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id", "username", "email", "first_name", "last_name", "full_name",
            "role", "phone_number", "id_number", "profile_photo",
            "next_of_kin_name", "next_of_kin_phone", "is_active_account",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]

    def get_full_name(self, obj):
        return obj.get_full_name() or obj.username


class TenantRegisterSerializer(serializers.ModelSerializer):
    """Used by the OWNER to onboard a new tenant (creates the user account)."""

    password = serializers.CharField(write_only=True, min_length=6)

    class Meta:
        model = User
        fields = [
            "id", "username", "password", "email", "first_name", "last_name",
            "phone_number", "id_number", "next_of_kin_name", "next_of_kin_phone",
        ]

    def create(self, validated_data):
        password = validated_data.pop("password")
        user = User(role=User.Role.TENANT, **validated_data)
        user.set_password(password)
        user.save()
        return user


class ProfileUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = [
            "first_name", "last_name", "email", "phone_number",
            "id_number", "profile_photo", "next_of_kin_name", "next_of_kin_phone",
        ]


class ChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField()
    new_password = serializers.CharField(min_length=6)

    def validate_old_password(self, value):
        user = self.context["request"].user
        if not user.check_password(value):
            raise serializers.ValidationError("Old password is incorrect.")
        return value


# ---------------------------------------------------------------------------
# ROOM / FLAT
# ---------------------------------------------------------------------------

class RoomSerializer(serializers.ModelSerializer):
    flat_name = serializers.CharField(source="flat.name", read_only=True)
    flat_location = serializers.CharField(source="flat.location", read_only=True)
    current_tenant_name = serializers.SerializerMethodField()
    current_tenant_id = serializers.SerializerMethodField()

    class Meta:
        model = Room
        fields = [
            "id", "flat", "flat_name", "flat_location", "room_number", "room_type",
            "floor", "status", "monthly_rent", "deposit_amount", "water_bill_amount",
            "has_balcony", "has_shower", "has_tiles", "has_wardrobe", "has_parking",
            "extra_features", "image", "current_tenant_name", "current_tenant_id",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def get_current_tenant_name(self, obj):
        t = obj.current_tenancy
        return t.tenant.get_full_name() or t.tenant.username if t else None

    def get_current_tenant_id(self, obj):
        t = obj.current_tenancy
        return t.tenant.id if t else None


class RoomNestedSerializer(serializers.ModelSerializer):
    """Lightweight room representation nested under a Flat."""

    class Meta:
        model = Room
        fields = [
            "id", "room_number", "room_type", "status", "monthly_rent",
            "deposit_amount", "water_bill_amount", "has_balcony", "has_shower",
            "has_tiles", "has_wardrobe", "has_parking",
        ]


class FlatSerializer(serializers.ModelSerializer):
    total_rooms = serializers.IntegerField(read_only=True)
    occupied_rooms_count = serializers.IntegerField(read_only=True)
    vacant_rooms_count = serializers.IntegerField(read_only=True)
    rooms = RoomNestedSerializer(many=True, read_only=True)

    class Meta:
        model = Flat
        fields = [
            "id", "owner", "name", "location", "address", "description", "image",
            "is_active", "total_rooms", "occupied_rooms_count", "vacant_rooms_count",
            "rooms", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "owner", "created_at", "updated_at"]


class FlatListSerializer(serializers.ModelSerializer):
    """Lighter serializer for list views (no nested rooms)."""

    total_rooms = serializers.IntegerField(read_only=True)
    occupied_rooms_count = serializers.IntegerField(read_only=True)
    vacant_rooms_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Flat
        fields = [
            "id", "owner", "name", "location", "address", "image", "is_active",
            "total_rooms", "occupied_rooms_count", "vacant_rooms_count",
        ]


# ---------------------------------------------------------------------------
# TENANCY
# ---------------------------------------------------------------------------

class TenancySerializer(serializers.ModelSerializer):
    tenant_detail = UserSerializer(source="tenant", read_only=True)
    room_detail = RoomNestedSerializer(source="room", read_only=True)
    flat_name = serializers.CharField(source="room.flat.name", read_only=True)
    flat_location = serializers.CharField(source="room.flat.location", read_only=True)
    balance_due = serializers.SerializerMethodField()

    class Meta:
        model = Tenancy
        fields = [
            "id", "tenant", "tenant_detail", "room", "room_detail", "flat_name",
            "flat_location", "status", "move_in_date", "move_out_date",
            "agreed_rent", "agreed_deposit", "deposit_paid", "rent_due_day",
            "extended_due_date", "notes", "balance_due", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def get_balance_due(self, obj):
        from .utils import compute_outstanding_balance
        return compute_outstanding_balance(obj)


class TenancyCreateSerializer(serializers.ModelSerializer):
    """Owner assigns a tenant to a room -> creates Tenancy + marks room occupied."""

    class Meta:
        model = Tenancy
        fields = [
            "id", "tenant", "room", "move_in_date", "agreed_rent",
            "agreed_deposit", "deposit_paid", "rent_due_day", "notes",
        ]

    def validate_room(self, room):
        if room.status == Room.Status.OCCUPIED:
            raise serializers.ValidationError("This room is already occupied.")
        return room

    def create(self, validated_data):
        room = validated_data["room"]
        validated_data.setdefault("agreed_rent", room.monthly_rent)
        validated_data.setdefault("agreed_deposit", room.deposit_amount)
        tenancy = Tenancy.objects.create(**validated_data, status=Tenancy.Status.ACTIVE)
        room.status = Room.Status.OCCUPIED
        room.save()
        return tenancy


class TenancyEndSerializer(serializers.Serializer):
    move_out_date = serializers.DateField(required=False)


# ---------------------------------------------------------------------------
# PAYMENTS
# ---------------------------------------------------------------------------

class PaymentAllocationSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaymentAllocation
        fields = ["id", "period_year", "period_month", "amount"]


class PaymentSerializer(serializers.ModelSerializer):
    allocations = PaymentAllocationSerializer(many=True, read_only=True)
    tenant_name = serializers.SerializerMethodField()
    room_label = serializers.SerializerMethodField()

    class Meta:
        model = Payment
        fields = [
            "id", "reference", "tenancy", "tenant_name", "room_label", "payment_type",
            "method", "status", "amount", "months_covered", "mpesa_checkout_request_id",
            "mpesa_receipt_number", "phone_used", "recorded_by", "notes",
            "allocations", "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "reference", "mpesa_checkout_request_id", "mpesa_receipt_number",
            "created_at", "updated_at",
        ]

    def get_tenant_name(self, obj):
        return obj.tenancy.tenant.get_full_name() or obj.tenancy.tenant.username

    def get_room_label(self, obj):
        return f"{obj.tenancy.room.flat.name} - {obj.tenancy.room.room_number}"


class CashPaymentCreateSerializer(serializers.ModelSerializer):
    """Owner/office records a cash payment made at the office."""

    class Meta:
        model = Payment
        fields = ["id", "tenancy", "payment_type", "amount", "months_covered", "notes"]

    def create(self, validated_data):
        request = self.context["request"]
        validated_data["method"] = Payment.Method.CASH
        validated_data["status"] = Payment.Status.COMPLETED
        validated_data["recorded_by"] = request.user
        payment = Payment.objects.create(**validated_data)
        payment.allocate_to_months()
        return payment


class MpesaSTKPushSerializer(serializers.Serializer):
    """Tenant-initiated M-Pesa payment request."""

    tenancy = serializers.PrimaryKeyRelatedField(queryset=Tenancy.objects.all())
    payment_type = serializers.ChoiceField(choices=Payment.PaymentType.choices)
    amount = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=1)
    months_covered = serializers.IntegerField(min_value=1, max_value=10, default=1)
    phone_number = serializers.CharField(max_length=15)

    def validate_months_covered(self, value):
        if value > 10:
            raise serializers.ValidationError("Tenants may pay a maximum of 10 months in advance.")
        return value


# ---------------------------------------------------------------------------
# MAINTENANCE
# ---------------------------------------------------------------------------

class MaintenanceRequestSerializer(serializers.ModelSerializer):
    tenant_name = serializers.SerializerMethodField()
    room_label = serializers.SerializerMethodField()

    class Meta:
        model = MaintenanceRequest
        fields = [
            "id", "tenancy", "tenant_name", "room_label", "title", "description",
            "priority", "status", "owner_notes", "cost", "image",
            "created_at", "updated_at", "resolved_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at", "resolved_at"]

    def get_tenant_name(self, obj):
        return obj.tenancy.tenant.get_full_name() or obj.tenancy.tenant.username

    def get_room_label(self, obj):
        return f"{obj.tenancy.room.flat.name} - {obj.tenancy.room.room_number}"


class MaintenanceRequestCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = MaintenanceRequest
        fields = ["id", "tenancy", "title", "description", "priority", "image"]


class MaintenanceOwnerUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = MaintenanceRequest
        fields = ["status", "owner_notes", "cost"]

    def update(self, instance, validated_data):
        instance = super().update(instance, validated_data)
        if instance.status == MaintenanceRequest.Status.RESOLVED and not instance.resolved_at:
            instance.resolved_at = timezone.now()
            instance.save()
        return instance


# ---------------------------------------------------------------------------
# SWITCH REQUEST
# ---------------------------------------------------------------------------

class SwitchRequestSerializer(serializers.ModelSerializer):
    tenant_name = serializers.SerializerMethodField()
    current_room_label = serializers.SerializerMethodField()
    requested_room_label = serializers.SerializerMethodField()

    class Meta:
        model = SwitchRequest
        fields = [
            "id", "current_tenancy", "tenant_name", "current_room_label",
            "requested_room", "requested_room_label", "reason", "status",
            "owner_response_notes", "new_tenancy", "created_at", "decided_at",
        ]
        read_only_fields = ["id", "new_tenancy", "created_at", "decided_at"]

    def get_tenant_name(self, obj):
        return obj.current_tenancy.tenant.get_full_name() or obj.current_tenancy.tenant.username

    def get_current_room_label(self, obj):
        return f"{obj.current_tenancy.room.flat.name} - {obj.current_tenancy.room.room_number}"

    def get_requested_room_label(self, obj):
        return f"{obj.requested_room.flat.name} - {obj.requested_room.room_number}"


class SwitchRequestCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = SwitchRequest
        fields = ["id", "current_tenancy", "requested_room", "reason"]

    def validate_requested_room(self, room):
        if room.status != Room.Status.VACANT:
            raise serializers.ValidationError("That room is not currently vacant.")
        return room


class SwitchRequestDecisionSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=["APPROVE", "REJECT"])
    notes = serializers.CharField(required=False, allow_blank=True)


# ---------------------------------------------------------------------------
# DEADLINE EXTENSION
# ---------------------------------------------------------------------------

class DeadlineExtensionRequestSerializer(serializers.ModelSerializer):
    tenant_name = serializers.SerializerMethodField()
    room_label = serializers.SerializerMethodField()

    class Meta:
        model = DeadlineExtensionRequest
        fields = [
            "id", "tenancy", "tenant_name", "room_label", "period_year",
            "period_month", "requested_new_date", "reason", "status",
            "created_at", "decided_at",
        ]
        read_only_fields = ["id", "created_at", "decided_at"]

    def get_tenant_name(self, obj):
        return obj.tenancy.tenant.get_full_name() or obj.tenancy.tenant.username

    def get_room_label(self, obj):
        return f"{obj.tenancy.room.flat.name} - {obj.tenancy.room.room_number}"


class DeadlineExtensionDecisionSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=["APPROVE", "REJECT"])


# ---------------------------------------------------------------------------
# RELOCATION DEPOSIT REQUEST
# ---------------------------------------------------------------------------

class RelocationDepositRequestSerializer(serializers.ModelSerializer):
    tenant_name = serializers.SerializerMethodField()
    target_room_label = serializers.SerializerMethodField()

    class Meta:
        model = RelocationDepositRequest
        fields = [
            "id", "tenant", "tenant_name", "target_room", "target_room_label",
            "intended_relocation_date", "amount", "status", "notes",
            "created_at", "decided_at",
        ]
        read_only_fields = ["id", "tenant", "created_at", "decided_at"]

    def get_tenant_name(self, obj):
        return obj.tenant.get_full_name() or obj.tenant.username

    def get_target_room_label(self, obj):
        return f"{obj.target_room.flat.name} - {obj.target_room.room_number}"


class RelocationDepositCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = RelocationDepositRequest
        fields = ["id", "target_room", "intended_relocation_date", "amount", "notes"]


class RelocationDepositDecisionSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=["APPROVE", "REJECT"])