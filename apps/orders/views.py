from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.exceptions import ValidationError
from django.shortcuts import get_object_or_404
from django_filters.rest_framework import DjangoFilterBackend

from apps.common.permissions import IsCustomerUser, IsOwnerOfOrder
from apps.orders.models import Order, OrderItem, OrderItemCustomization, OrderItemAddOn, Coupon
from apps.orders.serializers import (
    CartSerializer, AddToCartSerializer, OrderSerializer, 
    OrderTrackingSerializer, OrderStatusUpdateSerializer, CouponSerializer
)
from apps.menu.models import MenuItem, MenuItemCustomizationOption, MenuItemAddOn
from apps.restaurants.models import Restaurant, RestaurantStaffMember
from apps.users.models import SavedAddress
from apps.common.active_restaurant import managed_restaurants, my_restaurants, scope_queryset
from decimal import Decimal
from django.utils import timezone





class OrderViewSet(viewsets.ModelViewSet):
    """ViewSet for viewing and managing placed orders"""
    serializer_class = OrderSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['status', 'order_type', 'payment_status', 'restaurant']

    def get_permissions(self):
        if self.action == 'create':
            permission_classes = [IsCustomerUser]
        elif self.action in ['update', 'partial_update', 'destroy', 'update_status', 'cancel']:
            permission_classes = [IsOwnerOfOrder]
        else:
            permission_classes = [IsAuthenticated]
        return [permission() for permission in permission_classes]

    def get_queryset(self):
        user = self.request.user
        if user.role == 'CUSTOMER':
            # Customers only see their own orders, excluding active carts
            return Order.objects.filter(customer=user).exclude(status='CART').select_related('restaurant').prefetch_related('items')
        elif user.role in ('RESTAURANT_OWNER', 'RESTAURANT_MANAGER'):
            # The restaurant picked in the switcher (all of the owner's / manager's restaurants if none is picked).
            qs = scope_queryset(Order.objects.filter(restaurant__in=managed_restaurants(user)), self.request)
            return qs.exclude(status='CART').select_related('restaurant').prefetch_related('items')
        elif user.role == 'RESTAURANT_STAFF':
            qs = scope_queryset(Order.objects.filter(restaurant__in=my_restaurants(user)), self.request)
            return qs.exclude(status='CART').select_related('restaurant').prefetch_related('items')
        elif user.role == 'SUPER_ADMIN':
            qs = scope_queryset(Order.objects.all(), self.request)
            return qs.exclude(status='CART').select_related('restaurant').prefetch_related('items')
        return Order.objects.none()

    @action(detail=True, methods=['get'], permission_classes=[IsAuthenticated])
    def track(self, request, pk=None):
        """GET /api/v1/orders/{id}/track/ - Track order status"""
        order = self.get_object()
        serializer = OrderTrackingSerializer(order)
        return Response(serializer.data)

    @action(detail=True, methods=['post'], url_path='update-status')
    def update_status(self, request, pk=None):
        """POST /api/v1/orders/{id}/update-status/ - Update order status (e.g., to PREPARING)"""
        order = self.get_object()
        serializer = OrderStatusUpdateSerializer(data=request.data)
        
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
            
        new_status = serializer.validated_data['status']
        
        # Prevent reverting cancelled/delivered orders
        if order.status in ['DELIVERED', 'CANCELLED', 'REFUNDED'] and new_status not in ['CANCELLED', 'REFUNDED']:
            raise ValidationError(f"Cannot change status of a {order.status} order.")
            
        order.update_status(new_status)
        return Response({"message": f"Order status updated to {new_status}", "current_status": order.status}, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'], url_path='cancel')
    def cancel(self, request, pk=None):
        """POST /api/v1/orders/{id}/cancel/ - Cancel an order"""
        order = self.get_object()
        
        if not order.can_be_cancelled():
            raise ValidationError(f"Order cannot be cancelled because its current status is {order.status}.")
            
        cancellation_reason = request.data.get('reason', 'Cancelled by restaurant/admin')
        order.cancellation_reason = cancellation_reason
        order.update_status('CANCELLED')
        
        return Response({"message": "Order cancelled successfully"}, status=status.HTTP_200_OK)


class CartViewSet(viewsets.ViewSet):
    """Shopping Cart endpoints for Customers (Step 3.3 & 3.4)"""
    permission_classes = [IsAuthenticated, IsCustomerUser]

    def get_cart(self, request):
        """Get or create the user's active cart"""
        cart, created = Order.objects.get_or_create(
            customer=request.user,
            status='CART'
        )
        return cart

    def list(self, request):
        """GET /api/v1/cart/ - Get current cart"""
        cart = self.get_cart(request)
        serializer = CartSerializer(cart)
        return Response(serializer.data)

    @action(detail=False, methods=['post'], url_path='items')
    def add_item(self, request):
        """POST /api/v1/cart/items/ - Add item to cart"""
        serializer = AddToCartSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        data = serializer.validated_data
        menu_item = data['menu_item']
        quantity = data['quantity']
        
        cart = self.get_cart(request)
        
        # Enforce single restaurant per cart
        if cart.restaurant_id and cart.restaurant_id != menu_item.restaurant_id:
            return Response(
                {"error": "Your cart already contains items from another restaurant. Please clear your cart first."},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Assign restaurant to cart if empty
        if not cart.restaurant_id:
            cart.restaurant = menu_item.restaurant
            cart.save()

        # Calculate item price (base + customizations + addons)
        item_price = menu_item.price
        
        # Create OrderItem
        order_item = OrderItem.objects.create(
            order=cart,
            menu_item=menu_item,
            item_name=menu_item.name,
            item_price=item_price,
            quantity=quantity,
            special_instructions=data.get('special_instructions', '')
        )

        # Add Customizations
        if 'customization_option_ids' in data:
            for opt_id in data['customization_option_ids']:
                try:
                    opt = MenuItemCustomizationOption.objects.get(id=opt_id, customization__menu_item=menu_item)
                    OrderItemCustomization.objects.create(
                        order_item=order_item,
                        customization_name=opt.customization.name,
                        option_name=opt.name,
                        price_modifier=opt.price_modifier
                    )
                    item_price += opt.price_modifier
                except MenuItemCustomizationOption.DoesNotExist:
                    pass

        # Add Add-ons
        if 'addon_ids' in data:
            for addon_id in data['addon_ids']:
                try:
                    addon = MenuItemAddOn.objects.get(id=addon_id, menu_item=menu_item)
                    OrderItemAddOn.objects.create(
                        order_item=order_item,
                        addon_name=addon.name,
                        addon_price=addon.price
                    )
                    item_price += addon.price
                except MenuItemAddOn.DoesNotExist:
                    pass

        # Update order item price with modifiers and recalculate subtotal
        order_item.item_price = item_price
        order_item.save()
        order_item.calculate_subtotal()

        # Recalculate cart totals
        cart.calculate_totals()

        return Response(CartSerializer(cart).data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=['patch'], url_path='items/(?P<item_id>[^/.]+)')
    def update_item(self, request, item_id=None):
        """PATCH /api/v1/cart/items/{item_id}/ - Update quantity"""
        cart = self.get_cart(request)
        order_item = get_object_or_404(OrderItem, id=item_id, order=cart)
        
        quantity = request.data.get('quantity')
        if not quantity or int(quantity) < 1:
            return Response({"error": "Quantity must be at least 1"}, status=status.HTTP_400_BAD_REQUEST)
        
        order_item.quantity = int(quantity)
        order_item.save()
        order_item.calculate_subtotal()
        cart.calculate_totals()
        
        return Response(CartSerializer(cart).data)

    @action(detail=False, methods=['delete'], url_path='items/(?P<item_id>[^/.]+)')
    def remove_item(self, request, item_id=None):
        """DELETE /api/v1/cart/items/{item_id}/ - Remove item from cart"""
        cart = self.get_cart(request)
        order_item = get_object_or_404(OrderItem, id=item_id, order=cart)
        
        order_item.delete()
        cart.calculate_totals()
        
        # If cart is empty, remove restaurant association
        if not cart.items.exists():
            cart.restaurant = None
            cart.save()

        return Response(CartSerializer(cart).data, status=status.HTTP_200_OK)

    @action(detail=False, methods=['post'], url_path='checkout')
    def checkout(self, request):
        """POST /api/v1/cart/checkout/ - Convert cart to a placed order (Step 3.4 Logic)"""
        cart = self.get_cart(request)
        
        if not cart.items.exists():
            return Response({"error": "Cannot checkout an empty cart"}, status=status.HTTP_400_BAD_REQUEST)
        
        order_type = request.data.get('order_type', 'PICKUP').upper()
        
        # Validate order type selection against restaurant offerings
        if order_type == 'PICKUP' and not cart.restaurant.allows_pickup:
            raise ValidationError("This restaurant does not accept pickup orders.")
        elif order_type == 'DELIVERY' and not cart.restaurant.allows_delivery:
            raise ValidationError("This restaurant does not accept delivery orders.")
        elif order_type == 'DINE_IN' and not cart.restaurant.allows_dine_in:
            raise ValidationError("This restaurant does not accept dine-in orders.")

        cart.status = 'PLACED'
        cart.order_type = order_type

        # Handle Order Type Specifics
        if order_type == 'DELIVERY':
            address_id = request.data.get('address_id')
            if not address_id:
                raise ValidationError({"address_id": "Address ID is required for delivery orders."})
            
            try:
                address = SavedAddress.objects.get(id=address_id, user=request.user)
            except SavedAddress.DoesNotExist:
                raise ValidationError({"address_id": "Invalid delivery address."})
                
            cart.delivery_address = address.address
            cart.delivery_city = address.city
            cart.delivery_state = address.state
            cart.delivery_country = address.country
            cart.delivery_postal_code = address.postal_code
            cart.delivery_latitude = address.latitude
            cart.delivery_longitude = address.longitude
            cart.delivery_instructions = request.data.get('delivery_instructions', '')

        elif order_type == 'PICKUP':
            pickup_time = request.data.get('pickup_time')
            if not pickup_time:
                raise ValidationError({"pickup_time": "Pickup time is required for pickup orders."})
            cart.pickup_time = pickup_time

        elif order_type == 'DINE_IN':
            table_number = request.data.get('table_number')
            if not table_number:
                raise ValidationError({"table_number": "Table number is required for dine-in orders."})
            cart.table_number = table_number
            cart.number_of_guests = request.data.get('number_of_guests', 1)

        cart.save()
        cart.calculate_totals()
        
        return Response({
            "message": "Order placed successfully!",
            "order_id": str(cart.id),
            "order_type": cart.order_type,
            "total_amount": str(cart.total_amount)
        }, status=status.HTTP_200_OK)


# Add these to your existing apps/orders/views.py


# Make sure to import IsRestaurantOwner at the top of apps/orders/views.py
from apps.common.permissions import IsCustomerUser, IsOwnerOfOrder, IsRestaurantOwner

class CouponViewSet(viewsets.ModelViewSet):
    """Manage restaurant coupons and offers"""
    serializer_class = CouponSerializer
    permission_classes = [IsAuthenticated]

    def get_permissions(self):
        # Block customers/staff from creating or modifying coupons
        if self.action in ['create', 'update', 'partial_update', 'destroy', 'toggle_active']:
            return [IsAuthenticated(), IsRestaurantOwner()]
        return [IsAuthenticated()]

    def get_queryset(self):
        user = self.request.user
        if user.role in ('RESTAURANT_OWNER', 'RESTAURANT_MANAGER'):
            return scope_queryset(Coupon.objects.filter(restaurant__in=managed_restaurants(user)), self.request).prefetch_related('redemptions')
        elif user.role == 'SUPER_ADMIN':
            return scope_queryset(Coupon.objects.all(), self.request).prefetch_related('redemptions')
        return Coupon.objects.none()

    def perform_create(self, serializer):
        restaurant_id = self.request.data.get('restaurant_id')
        if not restaurant_id:
            raise ValidationError({"restaurant_id": "This field is required."})
            
        try:
            restaurant = managed_restaurants(self.request.user).get(id=restaurant_id)
        except Restaurant.DoesNotExist:
            raise ValidationError("Invalid restaurant or you do not own this restaurant.")
            
        # Check if code already exists
        code = self.request.data.get('code', '').upper()
        if Coupon.objects.filter(code=code).exists():
            raise ValidationError({"code": "This coupon code already exists."})
            
        serializer.save(restaurant=restaurant, code=code)

    @action(detail=True, methods=['post'], url_path='toggle-active')
    def toggle_active(self, request, pk=None):
        """POST /api/v1/orders/coupons/{id}/toggle-active/"""
        coupon = self.get_object()
        coupon.is_active = not coupon.is_active
        coupon.save()
        return Response({"is_active": coupon.is_active}, status=status.HTTP_200_OK)