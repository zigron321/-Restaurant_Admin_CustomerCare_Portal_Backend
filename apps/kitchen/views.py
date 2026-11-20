from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db.models import Q

from apps.orders.models import Order
from apps.common.active_restaurant import active_restaurant
from apps.kitchen.serializers import KitchenOrderSerializer
from apps.common.permissions import IsRestaurantStaffOrOwner

class KitchenOrderViewSet(viewsets.GenericViewSet):
    """Endpoints for the Kitchen Display System (KDS)"""
    serializer_class = KitchenOrderSerializer
    permission_classes = [IsAuthenticated, IsRestaurantStaffOrOwner]

    def get_queryset(self):
        # The restaurant being worked on: the one picked in the restaurant switcher, or the person's oldest one.
        # Owners see their own restaurants; managers and kitchen staff only the restaurants they were added to.
        restaurant = active_restaurant(self.request)

        # The kitchen works these: paid orders waiting to be accepted (PLACED), accepted ones (CONFIRMED),
        # on the stove (PREPARING) and finished ones waiting to be handed over (READY).
        # An order still waiting for its payment (PLACED + PENDING/FAILED) is not shown yet.
        waiting_paid = Q(status='PLACED') & ~Q(payment_status__in=['PENDING', 'FAILED'])
        return Order.objects.filter(
            Q(restaurant=restaurant) & (waiting_paid | Q(status__in=['CONFIRMED', 'PREPARING', 'READY']))
        ).prefetch_related('items__customizations', 'items__addons').order_by('placed_at')

    def list(self, request):
        """GET /api/v1/kitchen/orders/ - Get active orders for the kitchen"""
        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['post'], url_path='confirm')
    def confirm_order(self, request, pk=None):
        """POST /api/v1/kitchen/orders/{id}/confirm/ - Accept a new order (PLACED -> CONFIRMED)"""
        order = self.get_object()

        if order.status != 'PLACED':
            return Response({"error": f"Order must be PLACED to accept. Current: {order.status}"}, status=status.HTTP_400_BAD_REQUEST)

        order.update_status('CONFIRMED')
        serializer = self.get_serializer(order)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'], url_path='dispatch')
    def dispatch_order(self, request, pk=None):
        """POST /api/v1/kitchen/orders/{id}/dispatch/ - Hand a finished order over (READY -> DISPATCHED)"""
        order = self.get_object()

        if order.status != 'READY':
            return Response({"error": f"Order must be READY to dispatch. Current: {order.status}"}, status=status.HTTP_400_BAD_REQUEST)

        order.update_status('DISPATCHED')
        serializer = self.get_serializer(order)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'], url_path='start')
    def start_preparation(self, request, pk=None):
        """POST /api/v1/kitchen/orders/{id}/start/ - Mark order as PREPARING"""
        order = self.get_object()
        
        if order.status != 'CONFIRMED':
            return Response({"error": f"Order must be CONFIRMED to start. Current: {order.status}"}, status=status.HTTP_400_BAD_REQUEST)
            
        order.update_status('PREPARING')
        serializer = self.get_serializer(order)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'], url_path='ready')
    def mark_ready(self, request, pk=None):
        """POST /api/v1/kitchen/orders/{id}/ready/ - Mark order as READY for pickup/delivery"""
        order = self.get_object()
        
        if order.status != 'PREPARING':
            return Response({"error": f"Order must be PREPARING to mark as ready. Current: {order.status}"}, status=status.HTTP_400_BAD_REQUEST)
            
        order.update_status('READY')
        serializer = self.get_serializer(order)
        return Response(serializer.data, status=status.HTTP_200_OK)