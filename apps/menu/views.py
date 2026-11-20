from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, IsAuthenticatedOrReadOnly
from rest_framework.filters import SearchFilter, OrderingFilter
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.pagination import PageNumberPagination
from django.shortcuts import get_object_or_404

from apps.menu.models import MenuCategory, MenuItem, MenuItemCustomization, MenuItemAddOn
from apps.menu.serializers import (
    MenuCategorySerializer, MenuCategoryDetailSerializer, 
    MenuItemSerializer, MenuItemDetailSerializer, 
    MenuItemCustomizationSerializer, MenuItemAddOnSerializer
)
from apps.restaurants.models import Restaurant
from apps.common.permissions import CanManageRestaurant, IsRestaurantOwner
from apps.common.active_restaurant import OWNER_SIDE_ROLES, active_restaurant, managed_restaurants, manages, scope_queryset

class MenuCategoryViewSet(viewsets.ModelViewSet):
    """Menu category CRUD endpoints"""
    queryset = MenuCategory.objects.all()
    serializer_class = MenuCategorySerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [SearchFilter, OrderingFilter]
    search_fields = ['name', 'description']
    ordering_fields = ['order', 'name']

    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            # Use IsRestaurantOwner to block customers/staff immediately
            return [IsRestaurantOwner(), CanManageRestaurant()]
        return [IsAuthenticatedOrReadOnly()]

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return MenuCategoryDetailSerializer
        return MenuCategorySerializer

    def get_queryset(self):
        # Only filter for list action so permission classes can evaluate 403 for individual items
        if self.action == 'list':
            queryset = MenuCategory.objects.filter(is_active=True)
            if self.request.user.is_authenticated and self.request.user.role in OWNER_SIDE_ROLES:
                # Only the restaurant picked in the switcher (all of the owner's / manager's restaurants if none is picked).
                queryset = scope_queryset(MenuCategory.objects.filter(restaurant__in=managed_restaurants(self.request.user)), self.request)
            
            restaurant_id = self.request.query_params.get('restaurant_id')
            if restaurant_id:
                queryset = queryset.filter(restaurant_id=restaurant_id)
            return queryset
        
        # For retrieve, update, destroy: return all objects so CanManageRestaurant can return 403
        return MenuCategory.objects.all()

    def perform_create(self, serializer):
        restaurant_id = self.request.data.get('restaurant_id')
        if restaurant_id:
            restaurant = get_object_or_404(managed_restaurants(self.request.user), id=restaurant_id)
        else:
            # No restaurant named in the form: use the one the owner is working on.
            restaurant = active_restaurant(self.request)
        serializer.save(restaurant=restaurant)


class MenuItemViewSet(viewsets.ModelViewSet):
    """Menu item CRUD endpoints"""
    queryset = MenuItem.objects.all()
    serializer_class = MenuItemDetailSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['is_vegetarian', 'is_vegan', 'is_spicy', 'is_featured', 'is_new', 'is_available', 'category']
    search_fields = ['name', 'description', 'category__name']
    ordering_fields = ['name', 'price', 'rating', 'preparation_time_minutes']

    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy', 'toggle_availability', 'toggle_featured']:
            return [IsRestaurantOwner(), CanManageRestaurant()]
        return [IsAuthenticatedOrReadOnly()]

    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return MenuItemSerializer
        if self.action == 'list':
            return MenuItemSerializer
        return MenuItemDetailSerializer

    def get_queryset(self):
        if self.action == 'list':
            queryset = MenuItem.objects.filter(is_available=True, restaurant__is_active=True)
            if self.request.user.is_authenticated and self.request.user.role in OWNER_SIDE_ROLES:
                queryset = scope_queryset(MenuItem.objects.filter(restaurant__in=managed_restaurants(self.request.user)), self.request)
            
            restaurant_id = self.request.query_params.get('restaurant_id')
            if restaurant_id:
                queryset = queryset.filter(restaurant_id=restaurant_id)
            return queryset
        
        return MenuItem.objects.all()

    def perform_create(self, serializer):
        category_id = self.request.data.get('category_id')
        category = get_object_or_404(MenuCategory, id=category_id)
        if not manages(self.request.user, category.restaurant_id):
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("You do not own this category.")
        serializer.save(restaurant=category.restaurant, category=category)

    @action(detail=True, methods=['post'], permission_classes=[IsRestaurantOwner, CanManageRestaurant])
    def toggle_availability(self, request, pk=None):
        """POST /api/v1/menu/items/{id}/toggle_availability/"""
        item = self.get_object()
        item.is_available = not item.is_available
        item.save()
        return Response({"message": f"Item availability set to {item.is_available}"}, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'], permission_classes=[IsRestaurantOwner, CanManageRestaurant])
    def toggle_featured(self, request, pk=None):
        """POST /api/v1/menu/items/{id}/toggle_featured/"""
        item = self.get_object()
        item.is_featured = not item.is_featured
        item.save()
        return Response({"message": f"Item featured status set to {item.is_featured}"}, status=status.HTTP_200_OK)


class MenuItemCustomizationViewSet(viewsets.ModelViewSet):
    """Menu item customization CRUD endpoints"""
    queryset = MenuItemCustomization.objects.all()
    serializer_class = MenuItemCustomizationSerializer
    
    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            return [IsRestaurantOwner(), CanManageRestaurant()]
        return [IsAuthenticatedOrReadOnly()]

    def get_queryset(self):
        if self.action == 'list':
            user = self.request.user
            if user.is_authenticated and user.role in OWNER_SIDE_ROLES:
                return scope_queryset(MenuItemCustomization.objects.filter(menu_item__restaurant__in=managed_restaurants(user)), self.request, 'menu_item__restaurant')
            return MenuItemCustomization.objects.filter(menu_item__is_available=True)
        return MenuItemCustomization.objects.all()

    def perform_create(self, serializer):
        menu_item_id = self.request.data.get('menu_item_id')
        menu_item = get_object_or_404(MenuItem, id=menu_item_id)
        if not manages(self.request.user, menu_item.restaurant_id):
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("You do not own this menu item.")
        serializer.save(menu_item=menu_item)


class MenuItemAddOnViewSet(viewsets.ModelViewSet):
    """Menu item add-on CRUD endpoints"""
    queryset = MenuItemAddOn.objects.all()
    serializer_class = MenuItemAddOnSerializer
    
    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            return [IsRestaurantOwner(), CanManageRestaurant()]
        return [IsAuthenticatedOrReadOnly()]

    def get_queryset(self):
        if self.action == 'list':
            user = self.request.user
            if user.is_authenticated and user.role in OWNER_SIDE_ROLES:
                return scope_queryset(MenuItemAddOn.objects.filter(menu_item__restaurant__in=managed_restaurants(user)), self.request, 'menu_item__restaurant')
            return MenuItemAddOn.objects.filter(menu_item__is_available=True)
        return MenuItemAddOn.objects.all()

    def perform_create(self, serializer):
        menu_item_id = self.request.data.get('menu_item_id')
        menu_item = get_object_or_404(MenuItem, id=menu_item_id)
        if not manages(self.request.user, menu_item.restaurant_id):
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("You do not own this menu item.")
        serializer.save(menu_item=menu_item)