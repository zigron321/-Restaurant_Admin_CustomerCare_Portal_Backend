from rest_framework import status, viewsets
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework.response import Response
from rest_framework.decorators import action
from apps.users.serializers import (
    CustomUserSerializer, 
    CustomUserCreateSerializer, 
    LoginSerializer, 
    ChangePasswordSerializer,
    FavoriteRestaurantSerializer, FavoriteMenuItemSerializer, 
    GiftCardSerializer, RewardSerializer
)
from apps.common.responses import SuccessResponse, ErrorResponse
from django.contrib.auth import get_user_model

from apps.users.serializers import EmailVerificationSerializer, ForgotPasswordSerializer, ResetPasswordSerializer
from apps.users.models import (
    User, UserProfile, SavedAddress, EmailVerificationToken, PasswordResetToken, FavoriteRestaurant,
      FavoriteMenuItem, GiftCard, NotificationPreference, Notification, Campaign
)
from apps.users.email_service import EmailService
from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny
from apps.users.models import SavedAddress
from apps.common.permissions import IsCustomerUser

from django.db.models import Count, Q
from datetime import timedelta

from apps.users.serializers import (
    SavedAddressSerializer, FavoriteRestaurantSerializer, FavoriteMenuItemSerializer, GiftCardSerializer, 
    RewardSerializer, NotificationPreferenceSerializer, NotificationSerializer, CampaignSerializer
)
from apps.orders.models import Order
from apps.common.permissions import IsCustomerUser, IsRestaurantOwner
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import ValidationError
from apps.restaurants.models import Restaurant
from apps.common.active_restaurant import managed_restaurants






User = get_user_model()

class UserRegistrationViewSet(viewsets.ViewSet):
    """ViewSet for user registration"""
    permission_classes = [AllowAny]

    def create(self, request):
        serializer = CustomUserCreateSerializer(data=request.data)
        if serializer.is_valid():
            user = serializer.save()
            refresh = RefreshToken.for_user(user)
            user_data = CustomUserSerializer(user).data
            return SuccessResponse(
                message="Registration successful",
                data={
                    "access_token": str(refresh.access_token),
                    "refresh_token": str(refresh),
                    "user": user_data
                },
                status_code=status.HTTP_201_CREATED
            )
        return ErrorResponse(
            message="Registration failed",
            errors=serializer.errors,
            status_code=status.HTTP_400_BAD_REQUEST
        )

class UserLoginView(APIView):
    """View for user login"""
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = LoginSerializer(data=request.data, context={'request': request})
        if serializer.is_valid():
            user = serializer.validated_data['user']
            refresh = RefreshToken.for_user(user)
            user_data = CustomUserSerializer(user).data
            return SuccessResponse(
                message="Login successful",
                data={
                    "access_token": str(refresh.access_token),
                    "refresh_token": str(refresh),
                    "user": user_data
                }
            )
        return ErrorResponse(
            message="Invalid credentials",
            errors=serializer.errors,
            status_code=status.HTTP_401_UNAUTHORIZED
        )

class UserLogoutView(APIView):
    """View for user logout"""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            refresh_token = request.data.get("refresh_token")
            if not refresh_token:
                return ErrorResponse(message="Refresh token is required", status_code=status.HTTP_400_BAD_REQUEST)
            
            token = RefreshToken(refresh_token)
            token.blacklist()
            return SuccessResponse(message="Logout successful")
        except TokenError:
            return ErrorResponse(message="Invalid token", status_code=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return ErrorResponse(message=str(e), status_code=status.HTTP_400_BAD_REQUEST)

class UserProfileView(APIView):
    """View for retrieving and updating user profile"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        serializer = CustomUserSerializer(request.user)
        return SuccessResponse(message="Profile retrieved", data=serializer.data)

    def put(self, request):
        user = request.user
        serializer = CustomUserSerializer(user, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return SuccessResponse(message="Profile updated", data=serializer.data)
        return ErrorResponse(message="Update failed", errors=serializer.errors)

class ChangePasswordView(APIView):
    """View for changing user password"""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = ChangePasswordSerializer(data=request.data)
        if serializer.is_valid():
            user = request.user
            if not user.check_password(serializer.validated_data['old_password']):
                return ErrorResponse(message="Invalid old password", errors={"old_password": ["Incorrect password."]})
            
            user.set_password(serializer.validated_data['new_password'])
            user.save()
            return SuccessResponse(message="Password changed successfully")
        
        return ErrorResponse(message="Password change failed", errors=serializer.errors)





class VerifyEmailView(APIView):
    permission_classes = [AllowAny]
    def post(self, request):
        serializer = EmailVerificationSerializer(data=request.data)
        if serializer.is_valid():
            token_obj = EmailVerificationToken.objects.get(token=serializer.validated_data['token'])
            token_obj.is_used = True
            token_obj.used_at = timezone.now()
            token_obj.save()
            
            user = token_obj.user
            user.email_verified = True
            user.email_verified_at = timezone.now()
            user.save()
            
            return SuccessResponse(message="Email verified successfully")
        return ErrorResponse(message="Verification failed", errors=serializer.errors)

class RequestEmailVerificationView(APIView):
    permission_classes = [IsAuthenticated]
    def post(self, request):
        user = request.user
        if user.email_verified:
            return SuccessResponse(message="Email already verified")
        
        token = EmailVerificationToken.create_for_user(user)
        email_sent = EmailService.send_verification_email(user, token)
        
        if email_sent:
            return SuccessResponse(message="Verification email sent")
        return ErrorResponse(message="Failed to send email", status_code=500)

class SendVerificationEmailView(APIView):
    permission_classes = [AllowAny]
    def post(self, request):
        email = request.data.get('email')
        if not email:
            return ErrorResponse(message="Email required")
        
        try:
            user = User.objects.get(email=email)
            if user.email_verified:
                return SuccessResponse(message="Email already verified")
            
            token = EmailVerificationToken.create_for_user(user)
            email_sent = EmailService.send_verification_email(user, token)
            
            if email_sent:
                return SuccessResponse(message="Verification email sent")
            return ErrorResponse(message="Failed to send email", status_code=500)
        except User.DoesNotExist:
            return ErrorResponse(message="User not found", status_code=404)

class ForgotPasswordView(APIView):
    permission_classes = [AllowAny]
    def post(self, request):
        serializer = ForgotPasswordSerializer(data=request.data)
        if serializer.is_valid():
            user = User.objects.get(email=serializer.validated_data['email'])
            token = PasswordResetToken.create_for_user(user)
            email_sent = EmailService.send_password_reset_email(user, token)
            
            if email_sent:
                return SuccessResponse(message="Password reset email sent")
            return ErrorResponse(message="Failed to send email", status_code=500)
        return ErrorResponse(message="Request failed", errors=serializer.errors)

class ResetPasswordView(APIView):
    permission_classes = [AllowAny]
    def post(self, request):
        serializer = ResetPasswordSerializer(data=request.data)
        if serializer.is_valid():
            token_obj = PasswordResetToken.objects.get(token=serializer.validated_data['token'])
            user = token_obj.user
            
            user.set_password(serializer.validated_data['new_password'])
            user.last_password_changed = timezone.now()
            user.save()
            
            token_obj.is_used = True
            token_obj.used_at = timezone.now()
            token_obj.save()
            
            EmailService.send_password_changed_email(user)
            
            return SuccessResponse(message="Password reset successfully")
        return ErrorResponse(message="Reset failed", errors=serializer.errors)


class SavedAddressViewSet(viewsets.ModelViewSet):
    """Customer saved addresses management"""
    serializer_class = SavedAddressSerializer
    permission_classes = [IsAuthenticated, IsCustomerUser]

    def get_queryset(self):
        return SavedAddress.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save()



class FavoriteRestaurantViewSet(viewsets.ModelViewSet):
    """Manage favorite restaurants"""
    serializer_class = FavoriteRestaurantSerializer
    permission_classes = [IsAuthenticated, IsCustomerUser]
    http_method_names = ['get', 'post', 'delete', 'head', 'options'] # No update/put

    def get_queryset(self):
        return FavoriteRestaurant.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

class FavoriteMenuItemViewSet(viewsets.ModelViewSet):
    """Manage favorite menu items"""
    serializer_class = FavoriteMenuItemSerializer
    permission_classes = [IsAuthenticated, IsCustomerUser]
    http_method_names = ['get', 'post', 'delete', 'head', 'options']

    def get_queryset(self):
        return FavoriteMenuItem.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

class GiftCardViewSet(viewsets.ReadOnlyModelViewSet):
    """View gift cards"""
    serializer_class = GiftCardSerializer
    permission_classes = [IsAuthenticated, IsCustomerUser]

    def get_queryset(self):
        return GiftCard.objects.filter(user=self.request.user, is_active=True)

class RewardView(APIView):
    """View loyalty points & rewards"""
    permission_classes = [IsAuthenticated, IsCustomerUser]

    def get(self, request):
        profile, created = UserProfile.objects.get_or_create(user=request.user)
        serializer = RewardSerializer(profile)
        return Response(serializer.data)





class CampaignViewSet(viewsets.ModelViewSet):
    """Manage marketing campaigns"""
    serializer_class = CampaignSerializer
    permission_classes = [IsAuthenticated, IsRestaurantOwner]

    def get_queryset(self):
        return Campaign.objects.filter(restaurant__in=managed_restaurants(self.request.user))

    def perform_create(self, serializer):
        restaurant_id = self.request.data.get('restaurant_id')
        if not restaurant_id:
            raise ValidationError({"restaurant_id": "This field is required."})
        restaurant = get_object_or_404(managed_restaurants(self.request.user), id=restaurant_id)
        serializer.save(restaurant=restaurant)

    @action(detail=True, methods=['post'], url_path='send')
    def send_campaign(self, request, pk=None):
        """POST /api/v1/users/campaigns/{id}/send/ - Trigger the campaign"""
        campaign = self.get_object()
        
        if campaign.is_sent:
            return Response({"error": "Campaign already sent"}, status=status.HTTP_400_BAD_REQUEST)
            
        # 1. Determine target audience based on segment
        customers = User.objects.filter(role='CUSTOMER')
        
        if campaign.target_segment == 'INACTIVE':
            # Customers who haven't ordered in 30 days but have ordered before
            thirty_days_ago = timezone.now() - timedelta(days=30)
            recent_customers = Order.objects.filter(placed_at__gte=thirty_days_ago).values_list('customer_id', flat=True)
            customers = customers.filter(orders__isnull=False).exclude(id__in=recent_customers).distinct()
            
        elif campaign.target_segment == 'ABANDONED_CART':
            # Customers with an active CART status order
            cart_users = Order.objects.filter(status='CART').values_list('customer_id', flat=True)
            customers = customers.filter(id__in=cart_users)
            
        # 2. Filter by notification preferences
        if campaign.channel == 'EMAIL':
            customers = customers.filter(notification_preferences__email_promotions=True)
        elif campaign.channel == 'SMS':
            customers = customers.filter(notification_preferences__sms_promotions=True)
        elif campaign.channel == 'PUSH':
            customers = customers.filter(notification_preferences__push_promotions=True)

        # 3. Simulate sending and create Notification records
        notifications_to_create = []
        for customer in customers:
            notifications_to_create.append(Notification(
                user=customer,
                campaign=campaign,
                title=campaign.subject or campaign.name,
                message=campaign.body
            ))
            
        Notification.objects.bulk_create(notifications_to_create)
        
        # 4. Update campaign status
        campaign.is_sent = True
        campaign.sent_at = timezone.now()
        campaign.recipient_count = len(notifications_to_create)
        campaign.save()
        
        return Response({
            "message": f"Campaign sent successfully to {campaign.recipient_count} recipients.",
            "recipient_count": campaign.recipient_count
        }, status=status.HTTP_200_OK)


class NotificationPreferenceViewSet(viewsets.ModelViewSet):
    """Manage user notification preferences"""
    serializer_class = NotificationPreferenceSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return NotificationPreference.objects.filter(user=self.request.user)

    def create(self, request, *args, **kwargs):
        # Use update_or_create to avoid IntegrityError if preferences already exist
        obj, created = NotificationPreference.objects.update_or_create(
            user=request.user,
            defaults={
                'email_promotions': request.data.get('email_promotions', True),
                'sms_promotions': request.data.get('sms_promotions', False),
                'push_promotions': request.data.get('push_promotions', True),
                'order_updates': request.data.get('order_updates', True),
            }
        )
        serializer = self.get_serializer(obj)
        return Response(serializer.data, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)

class NotificationViewSet(viewsets.ReadOnlyModelViewSet):
    """View user notifications"""
    serializer_class = NotificationSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Notification.objects.filter(user=self.request.user).order_by('-created_at')

    @action(detail=True, methods=['post'], url_path='mark-read')
    def mark_read(self, request, pk=None):
        """POST /api/v1/users/notifications/{id}/mark-read/"""
        notification = self.get_object()
        notification.is_read = True
        notification.save()
        return Response({"message": "Notification marked as read"}, status=status.HTTP_200_OK)