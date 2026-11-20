from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.db.models import Q

from apps.delivery.models import Delivery
from apps.delivery.serializers import DeliverySerializer, AssignDriverSerializer, UpdateLocationSerializer
from apps.orders.models import Order
from apps.restaurants.models import Restaurant, RestaurantStaffMember
from apps.common.permissions import IsRestaurantOwner, IsDeliveryStaff
from apps.common.active_restaurant import managed_restaurants, my_restaurants, scope_queryset

def ensure_deliveries(restaurant_ids):
    """
    Every DELIVERY order the kitchen/owner has dispatched needs a Delivery row so a driver can pick it up.
    Creates the missing ones (safe to call often).
    """
    orders = (
        Order.objects.filter(restaurant_id__in=restaurant_ids, order_type='DELIVERY', status='DISPATCHED', delivery__isnull=True)
        .select_related('restaurant')
    )
    for order in orders:
        restaurant = order.restaurant
        Delivery.objects.create(
            order=order,
            customer=order.customer,
            restaurant=restaurant,
            status='PENDING',
            pickup_address=str(getattr(restaurant, 'address', '') or restaurant.name),
            delivery_address=str(getattr(order, 'delivery_address', '') or ''),
            estimated_delivery_time_minutes=getattr(restaurant, 'delivery_time_minutes', None) or 30,
        )


class DeliveryViewSet(viewsets.ModelViewSet):
    """Delivery management endpoints"""
    serializer_class = DeliverySerializer
    permission_classes = [IsAuthenticated]

    def get_permissions(self):
        if self.action in ['assign_driver']:
            return [IsAuthenticated(), IsRestaurantOwner()]
        elif self.action in ['update_location', 'mark_picked_up', 'mark_delivered']:
            return [IsAuthenticated(), IsDeliveryStaff()]
        return [IsAuthenticated()]

    def get_queryset(self):
        user = self.request.user
        queryset = Delivery.objects.select_related('order', 'restaurant', 'driver__user')
        
        if user.role == 'DELIVERY_STAFF':
            # Drivers see deliveries assigned to them, plus dispatched ones at their restaurant that nobody has taken yet
            # (whoever picks one up becomes its driver).
            restaurant_ids = list(my_restaurants(user).values_list('id', flat=True))
            ensure_deliveries(restaurant_ids)
            jobs = queryset.filter(Q(driver__user=user) | Q(driver__isnull=True, restaurant_id__in=restaurant_ids, status='PENDING'))
            # Only the restaurant picked in the switcher (all of the driver's restaurants if none is picked).
            return scope_queryset(jobs, self.request)
        elif user.role in ('RESTAURANT_OWNER', 'RESTAURANT_MANAGER'):
            # Owners (and the managers they appointed) see deliveries for their restaurants
            mine = managed_restaurants(user)
            ensure_deliveries(list(mine.values_list('id', flat=True)))
            return scope_queryset(queryset.filter(restaurant__in=mine), self.request)
        elif user.role == 'RESTAURANT_STAFF':
            return scope_queryset(queryset.filter(restaurant__in=my_restaurants(user)), self.request)
        elif user.role == 'SUPER_ADMIN':
            return scope_queryset(queryset.all(), self.request)
        
        # Customers can track their own deliveries
        if user.role == 'CUSTOMER':
            return queryset.filter(customer=user)
            
        return queryset.none()

    @action(detail=True, methods=['post'], url_path='assign-driver')
    def assign_driver(self, request, pk=None):
        """POST /api/v1/delivery/{id}/assign-driver/"""
        delivery = self.get_object()
        serializer = AssignDriverSerializer(data=request.data)
        
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
            
        driver_id = serializer.validated_data['driver_id']
        driver = get_object_or_404(RestaurantStaffMember, id=driver_id, restaurant=delivery.restaurant)
        
        delivery.assign_driver(driver)
        return Response(DeliverySerializer(delivery).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'], url_path='update-location')
    def update_location(self, request, pk=None):
        """POST /api/v1/delivery/{id}/update-location/"""
        delivery = self.get_object()
        
        # Ensure the driver is assigned to this delivery
        if not delivery.driver or delivery.driver.user != request.user:
            return Response({"error": "You are not assigned to this delivery."}, status=status.HTTP_403_FORBIDDEN)
            
        serializer = UpdateLocationSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
            
        delivery.update_location(
            serializer.validated_data['latitude'],
            serializer.validated_data['longitude']
        )
        return Response({"message": "Location updated successfully"}, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'], url_path='mark-picked-up')
    def mark_picked_up(self, request, pk=None):
        """POST /api/v1/delivery/{id}/mark-picked-up/"""
        delivery = self.get_object()
        
        if delivery.driver and delivery.driver.user != request.user:
            return Response({"error": "You are not assigned to this delivery."}, status=status.HTTP_403_FORBIDDEN)
            
        if delivery.status not in ['ASSIGNED', 'PENDING']:
            return Response({"error": f"Cannot pick up delivery with status {delivery.status}"}, status=status.HTTP_400_BAD_REQUEST)

        if delivery.driver is None:
            # Nobody was assigned: the driver who picks it up takes it.
            me = RestaurantStaffMember.objects.filter(user=request.user, restaurant=delivery.restaurant).first()
            if me is None:
                return Response({"error": "You do not work for this restaurant."}, status=status.HTTP_403_FORBIDDEN)
            delivery.assign_driver(me)

        delivery.mark_picked_up()
        
        # Also update the order status to OUT_FOR_DELIVERY
        delivery.order.update_status('OUT_FOR_DELIVERY')
        
        return Response(DeliverySerializer(delivery).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'], url_path='mark-delivered')
    def mark_delivered(self, request, pk=None):
        """POST /api/v1/delivery/{id}/mark-delivered/"""
        delivery = self.get_object()
        
        if delivery.driver and delivery.driver.user != request.user:
            return Response({"error": "You are not assigned to this delivery."}, status=status.HTTP_403_FORBIDDEN)
            
        if delivery.status != 'PICKED_UP':
            return Response({"error": f"Cannot deliver order with status {delivery.status}"}, status=status.HTTP_400_BAD_REQUEST)
            
        delivery.mark_delivered()
        
        # Also update the order status to DELIVERED
        delivery.order.update_status('DELIVERED')
        
        return Response(DeliverySerializer(delivery).data, status=status.HTTP_200_OK)