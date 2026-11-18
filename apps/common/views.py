from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db.models import Sum, Count
from django.shortcuts import get_object_or_404

from apps.common.permissions import IsSuperAdmin
from apps.users.models import User
from apps.restaurants.models import Restaurant
from apps.orders.models import Order
from apps.support.models import SupportTicket
from apps.common.serializers import AdminUserSerializer, AdminRestaurantSerializer, AdminOrderSerializer
from django.http import JsonResponse
from apps.common.active_restaurant import requested_id, active_restaurant

def health_check(request):
    """Simple health check endpoint."""
    return JsonResponse({
        "status": "healthy",
        "service": "restaurant_portal",
        "version": "1.0.0"
    })





class SuperAdminViewSet(viewsets.ViewSet):
    """Super Admin Dashboard and Management APIs"""
    permission_classes = [IsAuthenticated, IsSuperAdmin]

    @action(detail=False, methods=['get'], url_path='dashboard')
    def dashboard(self, request):
        """GET /api/v1/admin/dashboard/ - Platform overview stats"""
        orders = Order.objects.all()
        tickets = SupportTicket.objects.all()
        restaurants = Restaurant.objects.filter(is_active=True)
        # With a restaurant picked in the switcher, show only that restaurant's numbers.
        if requested_id(request):
            picked = active_restaurant(request)
            orders = orders.filter(restaurant=picked)
            tickets = tickets.filter(restaurant=picked)
            restaurants = restaurants.filter(pk=picked.pk)

        total_revenue = orders.filter(status='DELIVERED').aggregate(total=Sum('total_amount'))['total'] or 0
        total_orders = orders.exclude(status='CART').count()
        active_restaurants = restaurants.count()
        total_customers = User.objects.filter(role='CUSTOMER').count()
        open_tickets = tickets.filter(status__in=['OPEN', 'IN_PROGRESS']).count()

        data = {
            "total_revenue": str(total_revenue),
            "total_orders": total_orders,
            "active_restaurants": active_restaurants,
            "total_customers": total_customers,
            "open_support_tickets": open_tickets
        }
        return Response(data, status=status.HTTP_200_OK)

    @action(detail=False, methods=['get'], url_path='users')
    def list_users(self, request):
        """GET /api/v1/admin/users/ - List all platform users"""
        users = User.objects.all().order_by('-date_joined')
        serializer = AdminUserSerializer(users, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'], url_path='toggle-user-active')
    def toggle_user_active(self, request, pk=None):
        """POST /api/v1/admin/users/{id}/toggle-user-active/ - Block/Unblock user"""
        user = get_object_or_404(User, id=pk)
        user.is_active = not user.is_active
        user.save()
        return Response({"id": str(user.id), "is_active": user.is_active}, status=status.HTTP_200_OK)

    @action(detail=False, methods=['get'], url_path='restaurants')
    def list_restaurants(self, request):
        """GET /api/v1/admin/restaurants/ - List all restaurants"""
        restaurants = Restaurant.objects.all().order_by('-created_at')
        serializer = AdminRestaurantSerializer(restaurants, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'], url_path='toggle-restaurant-active')
    def toggle_restaurant_active(self, request, pk=None):
        """POST /api/v1/admin/restaurants/{id}/toggle-restaurant-active/ - Activate/Deactivate restaurant"""
        restaurant = get_object_or_404(Restaurant, id=pk)
        restaurant.is_active = not restaurant.is_active
        restaurant.save()
        return Response({"id": str(restaurant.id), "is_active": restaurant.is_active}, status=status.HTTP_200_OK)

    @action(detail=False, methods=['get'], url_path='orders')
    def list_orders(self, request):
        """GET /api/v1/admin/orders/ - List all platform orders"""
        orders = Order.objects.exclude(status='CART')
        if requested_id(request):
            orders = orders.filter(restaurant=active_restaurant(request))
        orders = orders.order_by('-placed_at')[:50]  # Last 50 orders
        serializer = AdminOrderSerializer(orders, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)