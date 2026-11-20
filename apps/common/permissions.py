from rest_framework.permissions import BasePermission, SAFE_METHODS
from apps.restaurants.models import Restaurant
from apps.common.active_restaurant import OWNER_SIDE_ROLES, manages

class IsOwner(BasePermission):
    """Check if user is the object owner"""
    def has_object_permission(self, request, view, obj):
        owner = getattr(obj, 'owner', None) or getattr(obj, 'user', None)
        return owner == request.user

class IsCustomerUser(BasePermission):
    """Only users with CUSTOMER role"""
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.role == 'CUSTOMER')

class IsRestaurantOwner(BasePermission):
    """The people who run a restaurant: the RESTAURANT_OWNER and the RESTAURANT_MANAGER the owner appointed.
    (Which restaurants a manager may touch is decided by the views, via managed_restaurants.)"""
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.role in OWNER_SIDE_ROLES)


class IsOnlyRestaurantOwner(BasePermission):
    """Strictly the RESTAURANT_OWNER (managers are not allowed): adding or deleting restaurants."""
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.role == 'RESTAURANT_OWNER')

class IsRestaurantOwnerOrReadOnly(BasePermission):
    """Allow read access to anyone, write only to restaurant owners"""
    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True
        return bool(request.user and request.user.is_authenticated and request.user.role in OWNER_SIDE_ROLES)

class IsRestaurantStaff(BasePermission):
    """Only RESTAURANT_STAFF role"""
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.role == 'RESTAURANT_STAFF')

class IsDeliveryStaff(BasePermission):
    """Only DELIVERY_STAFF role"""
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.role == 'DELIVERY_STAFF')

class IsRestaurantStaffOrOwner(BasePermission):
    """RESTAURANT_STAFF, RESTAURANT_MANAGER or RESTAURANT_OWNER role (kitchen screen)"""
    def has_permission(self, request, view):
        return bool(
            request.user and
            request.user.is_authenticated and
            request.user.role in ['RESTAURANT_STAFF', 'RESTAURANT_MANAGER', 'RESTAURANT_OWNER']
        )

class IsRestaurantStaffOrDeliveryStaff(BasePermission):
    """Only RESTAURANT_STAFF or DELIVERY_STAFF role"""
    def has_permission(self, request, view):
        return bool(
            request.user and 
            request.user.is_authenticated and 
            request.user.role in ['RESTAURANT_STAFF', 'DELIVERY_STAFF']
        )

class IsSuperAdmin(BasePermission):
    """Only SUPER_ADMIN role"""
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.role == 'SUPER_ADMIN')

class CanManageRestaurant(BasePermission):
    """Check if user owns / manages the restaurant, or is superadmin"""
    def has_object_permission(self, request, view, obj):
        if request.user.role == 'SUPER_ADMIN':
            return True
        if isinstance(obj, Restaurant):
            return obj.owner == request.user or (request.user.role == 'RESTAURANT_MANAGER' and manages(request.user, obj.pk))
        if hasattr(obj, 'restaurant'):
            return obj.restaurant.owner == request.user or (request.user.role == 'RESTAURANT_MANAGER' and manages(request.user, obj.restaurant_id))
        return False

class IsOwnerOfOrder(BasePermission):
    """Customer can access own orders, owner can access restaurant orders"""
    def has_object_permission(self, request, view, obj):
        if request.user.role == 'SUPER_ADMIN':
            return True
        if request.user.role == 'CUSTOMER':
            return obj.customer == request.user
        if request.user.role == 'RESTAURANT_OWNER':
            return obj.restaurant.owner == request.user
        if request.user.role == 'RESTAURANT_MANAGER':
            return manages(request.user, obj.restaurant_id)
        return False