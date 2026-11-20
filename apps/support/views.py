from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.utils import timezone

from apps.support.models import SupportTicket, SupportTicketMessage
from apps.common.active_restaurant import managed_restaurants, scope_queryset
from apps.support.serializers import SupportTicketSerializer, SupportTicketMessageSerializer

class SupportTicketViewSet(viewsets.ModelViewSet):
    """Customer support ticket endpoints"""
    serializer_class = SupportTicketSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if user.role == 'CUSTOMER':
            # Customers only see their own tickets
            return SupportTicket.objects.filter(customer=user).prefetch_related('messages').order_by('-created_at')
        elif user.role in ('RESTAURANT_OWNER', 'RESTAURANT_MANAGER'):
            # Owners (and their managers) see tickets related to their restaurants
            return scope_queryset(SupportTicket.objects.filter(restaurant__in=managed_restaurants(user)), self.request).prefetch_related('messages').order_by('-created_at')
        elif user.role == 'SUPER_ADMIN':
            return scope_queryset(SupportTicket.objects.all(), self.request).prefetch_related('messages').order_by('-created_at')
        return SupportTicket.objects.none()

    def perform_create(self, serializer):
        # Automatically attach the logged-in user as the customer
        serializer.save(customer=self.request.user)

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def add_message(self, request, pk=None):
        """POST /api/v1/support/{id}/add_message/ - Add a message to the ticket chat"""
        ticket = self.get_object()
        
        # Security: Ensure only the ticket owner or staff can message
        if request.user != ticket.customer and request.user.role not in ['RESTAURANT_OWNER', 'RESTAURANT_MANAGER', 'SUPER_ADMIN', 'RESTAURANT_STAFF']:
            return Response({"error": "Not authorized to message this ticket"}, status=status.HTTP_403_FORBIDDEN)

        serializer = SupportTicketMessageSerializer(data=request.data)
        if serializer.is_valid():
            # Determine message type based on who is sending it
            msg_type = 'CUSTOMER_MESSAGE' if request.user == ticket.customer else 'STAFF_MESSAGE'
            serializer.save(ticket=ticket, sender=request.user, message_type=msg_type)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def close(self, request, pk=None):
        """POST /api/v1/support/{id}/close/ - Close a ticket"""
        ticket = self.get_object()
        
        # Only the customer who created it or an admin can close it
        if request.user != ticket.customer and request.user.role != 'SUPER_ADMIN':
            return Response({"error": "Not authorized to close this ticket"}, status=status.HTTP_403_FORBIDDEN)

        ticket.status = 'CLOSED'
        ticket.is_resolved = True
        ticket.closed_at = timezone.now()
        ticket.save()
        return Response({"message": "Ticket closed successfully"}, status=status.HTTP_200_OK)