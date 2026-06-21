from rest_framework.permissions import BasePermission, SAFE_METHODS


class IsOwner(BasePermission):
    """Allows access only to users with role=OWNER."""

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.is_owner)


class IsTenant(BasePermission):
    """Allows access only to users with role=TENANT."""

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.is_tenant)


class IsOwnerOfFlat(BasePermission):
    """Object-level: the Flat (or object with a .owner) belongs to the requesting owner."""

    def has_object_permission(self, request, view, obj):
        owner = getattr(obj, "owner", None)
        return bool(request.user.is_owner and owner == request.user)


class IsTenancyOwnerOrTenant(BasePermission):
    """
    For Tenancy-linked objects (Payment, MaintenanceRequest, SwitchRequest...):
    the owner of the related flat can access, OR the tenant who owns the
    tenancy can access (read for tenant, restricted writes enforced in views).
    """

    def has_object_permission(self, request, view, obj):
        tenancy = getattr(obj, "tenancy", None) or getattr(obj, "current_tenancy", None)
        if tenancy is None:
            return False
        if request.user.is_owner:
            return tenancy.room.flat.owner == request.user
        if request.user.is_tenant:
            return tenancy.tenant == request.user
        return False