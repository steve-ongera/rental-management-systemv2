from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics, status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView

from .mpesa import MpesaClient, normalize_phone_number
from .models import (
    DeadlineExtensionRequest,
    Flat,
    MaintenanceRequest,
    Payment,
    RelocationDepositRequest,
    Room,
    SwitchRequest,
    Tenancy,
    User,
)
from .permissions import IsOwner, IsTenant
from .serializers import (
    CashPaymentCreateSerializer,
    ChangePasswordSerializer,
    CustomTokenObtainPairSerializer,
    DeadlineExtensionDecisionSerializer,
    DeadlineExtensionRequestSerializer,
    FlatListSerializer,
    FlatSerializer,
    MaintenanceOwnerUpdateSerializer,
    MaintenanceRequestCreateSerializer,
    MaintenanceRequestSerializer,
    MpesaSTKPushSerializer,
    PaymentSerializer,
    ProfileUpdateSerializer,
    RelocationDepositCreateSerializer,
    RelocationDepositDecisionSerializer,
    RelocationDepositRequestSerializer,
    RoomSerializer,
    SwitchRequestCreateSerializer,
    SwitchRequestDecisionSerializer,
    SwitchRequestSerializer,
    TenancyCreateSerializer,
    TenancyEndSerializer,
    TenancySerializer,
    TenantRegisterSerializer,
    UserSerializer,
)
from .utils import compute_outstanding_balance, is_rent_overdue, months_paid_ahead


# ---------------------------------------------------------------------------
# AUTH
# ---------------------------------------------------------------------------

class LoginView(TokenObtainPairView):
    serializer_class = CustomTokenObtainPairSerializer


class TenantRegisterView(generics.CreateAPIView):
    """Owner onboards a new tenant account."""

    queryset = User.objects.all()
    serializer_class = TenantRegisterSerializer
    permission_classes = [IsOwner]


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(UserSerializer(request.user).data)

    def patch(self, request):
        serializer = ProfileUpdateSerializer(request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(UserSerializer(request.user).data)


class ChangePasswordView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = ChangePasswordSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        request.user.set_password(serializer.validated_data["new_password"])
        request.user.save()
        return Response({"detail": "Password updated successfully."})


# ---------------------------------------------------------------------------
# FLATS  (Owner: full CRUD. Tenant: read-only, only vacant rooms for browsing)
# ---------------------------------------------------------------------------

class FlatViewSet(viewsets.ModelViewSet):
    serializer_class = FlatSerializer

    def get_permissions(self):
        if self.action in ["list", "retrieve", "available_rooms"]:
            return [IsAuthenticated()]
        return [IsOwner()]

    def get_serializer_class(self):
        if self.action == "list":
            return FlatListSerializer
        return FlatSerializer

    def get_queryset(self):
        user = self.request.user
        if user.is_owner:
            return Flat.objects.filter(owner=user).prefetch_related("rooms")
        # tenants can view flats (e.g. to browse for switch requests)
        return Flat.objects.filter(is_active=True).prefetch_related("rooms")

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)


class RoomViewSet(viewsets.ModelViewSet):
    serializer_class = RoomSerializer

    def get_permissions(self):
        if self.action in ["list", "retrieve", "available"]:
            return [IsAuthenticated()]
        return [IsOwner()]

    def get_queryset(self):
        user = self.request.user
        qs = Room.objects.select_related("flat")
        if user.is_owner:
            qs = qs.filter(flat__owner=user)
        flat_id = self.request.query_params.get("flat")
        if flat_id:
            qs = qs.filter(flat_id=flat_id)
        status_param = self.request.query_params.get("status")
        if status_param:
            qs = qs.filter(status=status_param)
        return qs

    def get_object(self):
        obj = super().get_object()
        user = self.request.user
        if user.is_owner and obj.flat.owner != user:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("You do not own this room.")
        return obj


# ---------------------------------------------------------------------------
# TENANCY
# ---------------------------------------------------------------------------

class TenancyViewSet(viewsets.ModelViewSet):
    def get_permissions(self):
        if self.action in ["list", "retrieve", "my_active", "my_history"]:
            return [IsAuthenticated()]
        return [IsOwner()]

    def get_serializer_class(self):
        if self.action == "create":
            return TenancyCreateSerializer
        return TenancySerializer

    def get_queryset(self):
        user = self.request.user
        qs = Tenancy.objects.select_related("tenant", "room", "room__flat")
        if user.is_owner:
            qs = qs.filter(room__flat__owner=user)
        elif user.is_tenant:
            qs = qs.filter(tenant=user)
        flat_id = self.request.query_params.get("flat")
        if flat_id:
            qs = qs.filter(room__flat_id=flat_id)
        status_param = self.request.query_params.get("status")
        if status_param:
            qs = qs.filter(status=status_param)
        return qs

    def end_tenancy(self, request, pk=None):
        tenancy = get_object_or_404(Tenancy, pk=pk)
        if tenancy.room.flat.owner != request.user:
            return Response({"detail": "Not allowed."}, status=status.HTTP_403_FORBIDDEN)
        serializer = TenancyEndSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        tenancy.end_tenancy(move_out_date=serializer.validated_data.get("move_out_date"))
        return Response(TenancySerializer(tenancy).data)


class MyActiveTenancyView(APIView):
    """Tenant: fetch my current active tenancy (room/flat/balance)."""

    permission_classes = [IsTenant]

    def get(self, request):
        tenancy = Tenancy.objects.filter(
            tenant=request.user, status=Tenancy.Status.ACTIVE
        ).select_related("room", "room__flat").first()
        if not tenancy:
            return Response({"detail": "No active tenancy found."}, status=status.HTTP_404_NOT_FOUND)
        data = TenancySerializer(tenancy).data
        data["is_overdue"] = is_rent_overdue(tenancy)
        data["months_paid_ahead"] = months_paid_ahead(tenancy)
        return Response(data)


class MyTenancyHistoryView(generics.ListAPIView):
    """Tenant: full history of all rooms ever occupied (incl. ended ones)."""

    serializer_class = TenancySerializer
    permission_classes = [IsTenant]

    def get_queryset(self):
        return Tenancy.objects.filter(tenant=self.request.user).select_related("room", "room__flat")


# ---------------------------------------------------------------------------
# PAYMENTS
# ---------------------------------------------------------------------------

class PaymentViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = PaymentSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        qs = Payment.objects.select_related("tenancy__tenant", "tenancy__room__flat").prefetch_related("allocations")
        if user.is_owner:
            qs = qs.filter(tenancy__room__flat__owner=user)
        elif user.is_tenant:
            qs = qs.filter(tenancy__tenant=user)
        tenancy_id = self.request.query_params.get("tenancy")
        if tenancy_id:
            qs = qs.filter(tenancy_id=tenancy_id)
        flat_id = self.request.query_params.get("flat")
        if flat_id:
            qs = qs.filter(tenancy__room__flat_id=flat_id)
        payment_type = self.request.query_params.get("payment_type")
        if payment_type:
            qs = qs.filter(payment_type=payment_type)
        return qs


class RecordCashPaymentView(generics.CreateAPIView):
    """Owner/office records a cash payment made in person at the office."""

    serializer_class = CashPaymentCreateSerializer
    permission_classes = [IsOwner]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        tenancy = serializer.validated_data["tenancy"]
        if tenancy.room.flat.owner != request.user:
            return Response({"detail": "Not allowed."}, status=status.HTTP_403_FORBIDDEN)
        payment = serializer.save()
        return Response(PaymentSerializer(payment).data, status=status.HTTP_201_CREATED)


class InitiateMpesaPaymentView(APIView):
    """
    Tenant-initiated M-Pesa STK Push for rent/water. Creates a PENDING
    Payment, fires the STK push, and stores the CheckoutRequestID for
    reconciliation when the callback arrives.
    """

    permission_classes = [IsTenant]

    def post(self, request):
        serializer = MpesaSTKPushSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        tenancy = data["tenancy"]
        if tenancy.tenant != request.user:
            return Response({"detail": "Not allowed."}, status=status.HTTP_403_FORBIDDEN)
        if data["months_covered"] > 1 and data["payment_type"] != Payment.PaymentType.RENT:
            return Response(
                {"detail": "Multi-month advance payment is only supported for rent."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if months_paid_ahead(tenancy) + data["months_covered"] > 10:
            return Response(
                {"detail": "You cannot pay more than 10 months of rent in advance."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        phone = normalize_phone_number(data["phone_number"])

        payment = Payment.objects.create(
            tenancy=tenancy,
            payment_type=data["payment_type"],
            method=Payment.Method.MPESA,
            status=Payment.Status.PENDING,
            amount=data["amount"],
            months_covered=data["months_covered"],
            phone_used=phone,
        )

        try:
            client = MpesaClient()
            account_ref = f"{tenancy.room.flat.name[:6]}{tenancy.room.room_number}"
            result = client.stk_push(
                phone_number=phone,
                amount=data["amount"],
                account_reference=account_ref,
                transaction_desc=data["payment_type"],
            )
            payment.mpesa_checkout_request_id = result.get("CheckoutRequestID")
            payment.save()
            return Response(
                {
                    "detail": "STK push sent. Enter your M-Pesa PIN to complete payment.",
                    "payment_id": payment.id,
                    "checkout_request_id": payment.mpesa_checkout_request_id,
                },
                status=status.HTTP_202_ACCEPTED,
            )
        except Exception as exc:  # noqa: BLE001
            payment.status = Payment.Status.FAILED
            payment.notes = f"STK push failed: {exc}"
            payment.save()
            return Response(
                {"detail": "Failed to initiate M-Pesa payment. Please try again."},
                status=status.HTTP_502_BAD_GATEWAY,
            )


class MpesaCallbackView(APIView):
    """
    Public endpoint Safaricom calls once the STK push is completed
    (success or failure). No auth - protect via URL secrecy / IP allowlist
    in production.
    """

    permission_classes = []
    authentication_classes = []

    def post(self, request):
        body = request.data.get("Body", {})
        stk_callback = body.get("stkCallback", {})
        checkout_id = stk_callback.get("CheckoutRequestID")
        result_code = stk_callback.get("ResultCode")

        payment = Payment.objects.filter(mpesa_checkout_request_id=checkout_id).first()
        if not payment:
            return Response({"ResultCode": 0, "ResultDesc": "Accepted"})

        if result_code == 0:
            metadata = stk_callback.get("CallbackMetadata", {}).get("Item", [])
            receipt = next((i["Value"] for i in metadata if i.get("Name") == "MpesaReceiptNumber"), None)
            payment.status = Payment.Status.COMPLETED
            payment.mpesa_receipt_number = receipt
            payment.save()
            payment.allocate_to_months()
        else:
            payment.status = Payment.Status.FAILED
            payment.notes = stk_callback.get("ResultDesc", "")
            payment.save()

        return Response({"ResultCode": 0, "ResultDesc": "Accepted"})


class MpesaStatusCheckView(APIView):
    """Tenant polls this to check if their STK push has completed."""

    permission_classes = [IsTenant]

    def get(self, request, payment_id):
        payment = get_object_or_404(Payment, id=payment_id, tenancy__tenant=request.user)
        return Response(PaymentSerializer(payment).data)


# ---------------------------------------------------------------------------
# MAINTENANCE REQUESTS
# ---------------------------------------------------------------------------

class MaintenanceRequestViewSet(viewsets.ModelViewSet):
    def get_serializer_class(self):
        if self.action == "create":
            return MaintenanceRequestCreateSerializer
        if self.action in ["partial_update", "update"] and self.request.user.is_owner:
            return MaintenanceOwnerUpdateSerializer
        return MaintenanceRequestSerializer

    def get_permissions(self):
        return [IsAuthenticated()]

    def get_queryset(self):
        user = self.request.user
        qs = MaintenanceRequest.objects.select_related("tenancy__tenant", "tenancy__room__flat")
        if user.is_owner:
            qs = qs.filter(tenancy__room__flat__owner=user)
        elif user.is_tenant:
            qs = qs.filter(tenancy__tenant=user)
        status_param = self.request.query_params.get("status")
        if status_param:
            qs = qs.filter(status=status_param)
        return qs

    def perform_create(self, serializer):
        tenancy = serializer.validated_data["tenancy"]
        if tenancy.tenant != self.request.user:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("You can only raise requests for your own tenancy.")
        serializer.save()

    def perform_update(self, serializer):
        if self.request.user.is_owner:
            instance = serializer.save()
            if instance.status == MaintenanceRequest.Status.RESOLVED and not instance.resolved_at:
                instance.resolved_at = timezone.now()
                instance.save()
        else:
            serializer.save()


# ---------------------------------------------------------------------------
# SWITCH REQUESTS
# ---------------------------------------------------------------------------

class SwitchRequestViewSet(viewsets.ModelViewSet):
    def get_serializer_class(self):
        if self.action == "create":
            return SwitchRequestCreateSerializer
        return SwitchRequestSerializer

    def get_permissions(self):
        return [IsAuthenticated()]

    def get_queryset(self):
        user = self.request.user
        qs = SwitchRequest.objects.select_related(
            "current_tenancy__tenant", "current_tenancy__room__flat", "requested_room__flat"
        )
        if user.is_owner:
            qs = qs.filter(current_tenancy__room__flat__owner=user)
        elif user.is_tenant:
            qs = qs.filter(current_tenancy__tenant=user)
        return qs

    def perform_create(self, serializer):
        tenancy = serializer.validated_data["current_tenancy"]
        if tenancy.tenant != self.request.user:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("You can only request a switch for your own tenancy.")
        serializer.save()

    def decide(self, request, pk=None):
        """POST /switch-requests/{id}/decide/  body: {action: APPROVE|REJECT, notes}"""
        switch_request = get_object_or_404(SwitchRequest, pk=pk)
        if switch_request.current_tenancy.room.flat.owner != request.user:
            return Response({"detail": "Not allowed."}, status=status.HTTP_403_FORBIDDEN)
        if switch_request.status != SwitchRequest.Status.PENDING:
            return Response({"detail": "This request has already been decided."}, status=status.HTTP_400_BAD_REQUEST)

        serializer = SwitchRequestDecisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        action = serializer.validated_data["action"]
        notes = serializer.validated_data.get("notes", "")

        try:
            if action == "APPROVE":
                with transaction.atomic():
                    switch_request.approve()
            else:
                switch_request.reject(notes=notes)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(SwitchRequestSerializer(switch_request).data)


# ---------------------------------------------------------------------------
# DEADLINE EXTENSION REQUESTS
# ---------------------------------------------------------------------------

class DeadlineExtensionRequestViewSet(viewsets.ModelViewSet):
    serializer_class = DeadlineExtensionRequestSerializer

    def get_permissions(self):
        return [IsAuthenticated()]

    def get_queryset(self):
        user = self.request.user
        qs = DeadlineExtensionRequest.objects.select_related("tenancy__tenant", "tenancy__room__flat")
        if user.is_owner:
            qs = qs.filter(tenancy__room__flat__owner=user)
        elif user.is_tenant:
            qs = qs.filter(tenancy__tenant=user)
        return qs

    def perform_create(self, serializer):
        tenancy = serializer.validated_data["tenancy"]
        if tenancy.tenant != self.request.user:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("You can only request an extension for your own tenancy.")
        serializer.save()

    def decide(self, request, pk=None):
        ext_request = get_object_or_404(DeadlineExtensionRequest, pk=pk)
        if ext_request.tenancy.room.flat.owner != request.user:
            return Response({"detail": "Not allowed."}, status=status.HTTP_403_FORBIDDEN)
        if ext_request.status != DeadlineExtensionRequest.Status.PENDING:
            return Response({"detail": "Already decided."}, status=status.HTTP_400_BAD_REQUEST)

        serializer = DeadlineExtensionDecisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        if serializer.validated_data["action"] == "APPROVE":
            ext_request.approve()
        else:
            ext_request.reject()
        return Response(DeadlineExtensionRequestSerializer(ext_request).data)


# ---------------------------------------------------------------------------
# RELOCATION DEPOSIT REQUESTS
# ---------------------------------------------------------------------------

class RelocationDepositRequestViewSet(viewsets.ModelViewSet):
    def get_serializer_class(self):
        if self.action == "create":
            return RelocationDepositCreateSerializer
        return RelocationDepositRequestSerializer

    def get_permissions(self):
        return [IsAuthenticated()]

    def get_queryset(self):
        user = self.request.user
        qs = RelocationDepositRequest.objects.select_related("tenant", "target_room__flat")
        if user.is_owner:
            qs = qs.filter(target_room__flat__owner=user)
        elif user.is_tenant:
            qs = qs.filter(tenant=user)
        return qs

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.user)

    def decide(self, request, pk=None):
        reloc_request = get_object_or_404(RelocationDepositRequest, pk=pk)
        if reloc_request.target_room.flat.owner != request.user:
            return Response({"detail": "Not allowed."}, status=status.HTTP_403_FORBIDDEN)
        if reloc_request.status != RelocationDepositRequest.Status.PENDING:
            return Response({"detail": "Already decided."}, status=status.HTTP_400_BAD_REQUEST)

        serializer = RelocationDepositDecisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        reloc_request.status = (
            RelocationDepositRequest.Status.APPROVED
            if serializer.validated_data["action"] == "APPROVE"
            else RelocationDepositRequest.Status.REJECTED
        )
        reloc_request.decided_at = timezone.now()
        reloc_request.save()
        return Response(RelocationDepositRequestSerializer(reloc_request).data)


# ---------------------------------------------------------------------------
# OWNER DASHBOARD SUMMARY
# ---------------------------------------------------------------------------

class OwnerDashboardSummaryView(APIView):
    permission_classes = [IsOwner]

    def get(self, request):
        owner = request.user
        flats = Flat.objects.filter(owner=owner)
        rooms = Room.objects.filter(flat__owner=owner)
        active_tenancies = Tenancy.objects.filter(room__flat__owner=owner, status=Tenancy.Status.ACTIVE)

        overdue_count = sum(1 for t in active_tenancies if is_rent_overdue(t))

        this_month_start = timezone.now().date().replace(day=1)
        payments_this_month = Payment.objects.filter(
            tenancy__room__flat__owner=owner,
            status=Payment.Status.COMPLETED,
            created_at__date__gte=this_month_start,
        )
        total_collected_this_month = sum((p.amount for p in payments_this_month), start=0)

        pending_maintenance = MaintenanceRequest.objects.filter(
            tenancy__room__flat__owner=owner, status=MaintenanceRequest.Status.PENDING
        ).count()
        pending_switch_requests = SwitchRequest.objects.filter(
            current_tenancy__room__flat__owner=owner, status=SwitchRequest.Status.PENDING
        ).count()
        pending_extension_requests = DeadlineExtensionRequest.objects.filter(
            tenancy__room__flat__owner=owner, status=DeadlineExtensionRequest.Status.PENDING
        ).count()
        pending_relocation_requests = RelocationDepositRequest.objects.filter(
            target_room__flat__owner=owner, status=RelocationDepositRequest.Status.PENDING
        ).count()

        return Response({
            "total_flats": flats.count(),
            "total_rooms": rooms.count(),
            "occupied_rooms": rooms.filter(status=Room.Status.OCCUPIED).count(),
            "vacant_rooms": rooms.filter(status=Room.Status.VACANT).count(),
            "active_tenants": active_tenancies.count(),
            "overdue_tenants": overdue_count,
            "total_collected_this_month": total_collected_this_month,
            "pending_maintenance": pending_maintenance,
            "pending_switch_requests": pending_switch_requests,
            "pending_extension_requests": pending_extension_requests,
            "pending_relocation_requests": pending_relocation_requests,
        })


class AvailableRoomsView(generics.ListAPIView):
    """Tenant-facing: browse vacant rooms across all flats (for switch requests)."""

    serializer_class = RoomSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = Room.objects.filter(status=Room.Status.VACANT).select_related("flat")
        flat_id = self.request.query_params.get("flat")
        if flat_id:
            qs = qs.filter(flat_id=flat_id)
        room_type = self.request.query_params.get("room_type")
        if room_type:
            qs = qs.filter(room_type=room_type)
        return qs