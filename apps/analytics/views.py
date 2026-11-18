from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db.models import Sum, Count, Q, Avg
from django.db.models.functions import TruncMonth, TruncDay
from django.utils import timezone
from datetime import timedelta
import csv
from django.http import HttpResponse

from apps.common.permissions import IsRestaurantOwner
from apps.common.active_restaurant import active_restaurant
from apps.restaurants.models import Restaurant
from apps.orders.models import Order
from apps.menu.models import MenuItem
from apps.analytics.serializers import (
    PopularItemSerializer, RecentOrderSerializer, 
    SalesReportSerializer, CustomerAnalyticsSerializer, 
    OperationalMetricsSerializer
)

class DashboardViewSet(viewsets.ViewSet):
    """Analytics endpoints for the Restaurant Owner Dashboard"""
    permission_classes = [IsAuthenticated, IsRestaurantOwner]

    def get_restaurant(self, request):
        """The restaurant the owner is working on (switcher), or their oldest one. None if they have no restaurant."""
        return active_restaurant(request, required=False)

    def list(self, request):
        """GET /api/v1/analytics/dashboard/ - Main overview stats"""
        restaurant = self.get_restaurant(request)
        if not restaurant:
            return Response({"error": "No restaurant found for this user"}, status=status.HTTP_404_NOT_FOUND)

        today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start + timedelta(days=1)

        all_orders = Order.objects.filter(restaurant=restaurant).exclude(status='CART')
        today_orders = all_orders.filter(placed_at__gte=today_start, placed_at__lt=today_end)

        total_sales = all_orders.aggregate(total=Sum('total_amount'))['total'] or 0
        today_sales = today_orders.aggregate(total=Sum('total_amount'))['total'] or 0
        
        total_orders = all_orders.count()
        today_orders_count = today_orders.count()

        pending_orders = today_orders.filter(status__in=['PLACED', 'CONFIRMED', 'PREPARING']).count()
        completed_orders = today_orders.filter(status='DELIVERED').count()
        cancelled_orders = today_orders.filter(status='CANCELLED').count()

        total_customers = all_orders.values('customer').distinct().count()

        data = {
            "restaurant_name": restaurant.name,
            "today_sales": str(today_sales),
            "today_orders_count": today_orders_count,
            "pending_orders": pending_orders,
            "completed_orders": completed_orders,
            "cancelled_orders": cancelled_orders,
            "total_sales": str(total_sales),
            "total_orders": total_orders,
            "total_customers": total_customers,
        }
        return Response(data, status=status.HTTP_200_OK)

    @action(detail=False, methods=['get'])
    def popular_items(self, request):
        """GET /api/v1/analytics/dashboard/popular_items/ - Top 5 selling items"""
        restaurant = self.get_restaurant(request)
        if not restaurant:
            return Response({"error": "No restaurant found"}, status=status.HTTP_404_NOT_FOUND)

        popular = MenuItem.objects.filter(restaurant=restaurant).annotate(
            total_quantity_sold=Sum('orderitem__quantity'),
            total_revenue=Sum('orderitem__subtotal')
        ).filter(total_quantity_sold__gt=0).order_by('-total_quantity_sold')[:5]

        serializer = PopularItemSerializer(popular, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=False, methods=['get'])
    def recent_orders(self, request):
        """GET /api/v1/analytics/dashboard/recent_orders/ - Last 5 orders"""
        restaurant = self.get_restaurant(request)
        if not restaurant:
            return Response({"error": "No restaurant found"}, status=status.HTTP_404_NOT_FOUND)

        recent = Order.objects.filter(restaurant=restaurant).exclude(status='CART').order_by('-placed_at', '-created_at')[:5]
        serializer = RecentOrderSerializer(recent, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=False, methods=['get'], url_path='sales-report')
    def sales_report(self, request):
        """GET /api/v1/analytics/dashboard/sales-report/?period=daily|weekly|monthly"""
        restaurant = self.get_restaurant(request)
        if not restaurant:
            return Response({"error": "No restaurant found"}, status=status.HTTP_404_NOT_FOUND)

        period = request.query_params.get('period', 'daily')
        days = 30 if period == 'daily' else 12 if period == 'monthly' else 7
        
        start_date = timezone.now() - timedelta(days=days)
        
        if period == 'monthly':
            report = Order.objects.filter(
                restaurant=restaurant, placed_at__gte=start_date, status='DELIVERED'
            ).annotate(
                month=TruncMonth('placed_at')
            ).values('month').annotate(
                total_orders=Count('id'),
                total_sales=Sum('total_amount'),
                average_order_value=Avg('total_amount')
            ).order_by('month')
            
            data = [{
                "date": str(entry['month'].strftime('%Y-%m')),
                "total_orders": entry['total_orders'],
                "total_sales": str(entry['total_sales'] or 0),
                "average_order_value": str(entry['average_order_value'] or 0)
            } for entry in report]
        else:
            report = Order.objects.filter(
                restaurant=restaurant, placed_at__gte=start_date, status='DELIVERED'
            ).annotate(
                day=TruncDay('placed_at')
            ).values('day').annotate(
                total_orders=Count('id'),
                total_sales=Sum('total_amount'),
                average_order_value=Avg('total_amount')
            ).order_by('day')
            
            data = [{
                "date": str(entry['day'].strftime('%Y-%m-%d')),
                "total_orders": entry['total_orders'],
                "total_sales": str(entry['total_sales'] or 0),
                "average_order_value": str(entry['average_order_value'] or 0)
            } for entry in report]

        serializer = SalesReportSerializer(data, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=False, methods=['get'], url_path='customer-analytics')
    def customer_analytics(self, request):
        """GET /api/v1/analytics/dashboard/customer-analytics/"""
        restaurant = self.get_restaurant(request)
        if not restaurant:
            return Response({"error": "No restaurant found"}, status=status.HTTP_404_NOT_FOUND)

        top_customers = Order.objects.filter(
            restaurant=restaurant, status='DELIVERED'
        ).values(
            'customer__id', 'customer__email'
        ).annotate(
            total_orders=Count('id'),
            total_spent=Sum('total_amount')
        ).order_by('-total_spent')[:10]

        data = [{
            "customer_id": str(entry['customer__id']),
            "customer_email": entry['customer__email'],
            "total_orders": entry['total_orders'],
            "total_spent": str(entry['total_spent'] or 0)
        } for entry in top_customers]

        serializer = CustomerAnalyticsSerializer(data, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=False, methods=['get'], url_path='operational-metrics')
    def operational_metrics(self, request):
        """GET /api/v1/analytics/dashboard/operational-metrics/"""
        restaurant = self.get_restaurant(request)
        if not restaurant:
            return Response({"error": "No restaurant found"}, status=status.HTTP_404_NOT_FOUND)

        start_date = timezone.now() - timedelta(days=30)
        orders = Order.objects.filter(
            restaurant=restaurant, placed_at__gte=start_date
        ).exclude(status='CART')

        peak_hours = orders.extra(
            select={'hour': "EXTRACT(hour FROM placed_at)"}
        ).values('hour').annotate(
            order_count=Count('id')
        ).order_by('-order_count')[:5]

        data = [{
            "peak_hour": int(entry['hour']),
            "order_count": entry['order_count']
        } for entry in peak_hours]

        serializer = OperationalMetricsSerializer(data, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=False, methods=['get'], url_path='export-sales')
    def export_sales_csv(self, request):
        """GET /api/v1/analytics/dashboard/export-sales/ - Download CSV report"""
        restaurant = self.get_restaurant(request)
        if not restaurant:
            return Response({"error": "No restaurant found"}, status=status.HTTP_404_NOT_FOUND)

        start_date = timezone.now() - timedelta(days=30)
        orders = Order.objects.filter(
            restaurant=restaurant, placed_at__gte=start_date
        ).exclude(status='CART').select_related('customer').order_by('-placed_at')

        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="sales_report_{restaurant.name}.csv"'

        writer = csv.writer(response)
        writer.writerow(['Order Number', 'Customer Email', 'Status', 'Order Type', 'Total Amount', 'Placed At'])

        for order in orders:
            writer.writerow([
                order.order_number,
                order.customer.email,
                order.status,
                order.order_type,
                str(order.total_amount),
                order.placed_at.strftime('%Y-%m-%d %H:%M')
            ])

        return response