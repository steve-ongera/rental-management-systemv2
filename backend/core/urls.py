from django.urls import include, path
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView

from . import views

router = DefaultRouter()
router.register(r"flats", views.FlatViewSet, basename="flat")
router.register(r"rooms", views.RoomViewSet, basename="room")
router.register(r"tenancies", views.TenancyViewSet, basename="tenancy")
router.register(r"payments", views.PaymentViewSet, basename="payment")
router.register(r"maintenance-requests", views.MaintenanceRequestViewSet, basename="maintenance-request")
router.register(r"switch-requests", views.SwitchRequestViewSet, basename="switch-request")
router.register(r"extension-requests", views.DeadlineExtensionRequestViewSet, basename="extension-request")
router.register(r"relocation-requests", views.RelocationDepositRequestViewSet, basename="relocation-request")

urlpatterns = [
    # ---- Auth ----
    path("auth/login/", views.LoginView.as_view(), name="login"),
    path("auth/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("auth/register-tenant/", views.TenantRegisterView.as_view(), name="register_tenant"),
    path("auth/me/", views.MeView.as_view(), name="me"),
    path("auth/change-password/", views.ChangePasswordView.as_view(), name="change_password"),

    # ---- Tenant-specific convenience endpoints ----
    path("my-tenancy/active/", views.MyActiveTenancyView.as_view(), name="my_active_tenancy"),
    path("my-tenancy/history/", views.MyTenancyHistoryView.as_view(), name="my_tenancy_history"),
    path("rooms/available/", views.AvailableRoomsView.as_view(), name="available_rooms"),

    # ---- Tenancy custom action ----
    path("tenancies/<int:pk>/end/", views.TenancyViewSet.as_view({"post": "end_tenancy"}), name="tenancy_end"),

    # ---- Payments ----
    path("payments/cash/", views.RecordCashPaymentView.as_view(), name="record_cash_payment"),
    path("payments/mpesa/initiate/", views.InitiateMpesaPaymentView.as_view(), name="mpesa_initiate"),
    path("payments/mpesa/callback/", views.MpesaCallbackView.as_view(), name="mpesa_callback"),
    path("payments/mpesa/status/<int:payment_id>/", views.MpesaStatusCheckView.as_view(), name="mpesa_status"),

    # ---- Switch requests decision ----
    path(
        "switch-requests/<int:pk>/decide/",
        views.SwitchRequestViewSet.as_view({"post": "decide"}),
        name="switch_request_decide",
    ),

    # ---- Extension requests decision ----
    path(
        "extension-requests/<int:pk>/decide/",
        views.DeadlineExtensionRequestViewSet.as_view({"post": "decide"}),
        name="extension_request_decide",
    ),

    # ---- Relocation deposit decision ----
    path(
        "relocation-requests/<int:pk>/decide/",
        views.RelocationDepositRequestViewSet.as_view({"post": "decide"}),
        name="relocation_request_decide",
    ),

    # ---- Owner dashboard ----
    path("owner/dashboard-summary/", views.OwnerDashboardSummaryView.as_view(), name="owner_dashboard_summary"),

    # ---- Router-generated CRUD ----
    path("", include(router.urls)),
]