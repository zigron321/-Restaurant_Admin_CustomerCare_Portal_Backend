"""
"Which restaurant is this person working on right now?"

An owner can run several restaurants, and a kitchen / delivery team member can work at several too.
The website tells the server which one it is looking at by adding `?active_restaurant=<id>` to its requests
(the `X-Restaurant-Id` header works as well). Every owner / staff / admin screen then shows only that restaurant.

* Nothing sent  -> old behaviour (lists show everything the person may see, single-item screens use the oldest restaurant).
* An id that the person has no access to -> 404, so nobody can peek into someone else's restaurant.
"""
from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import Http404

PARAM = 'active_restaurant'
HEADER_META = 'HTTP_X_RESTAURANT_ID'


def my_restaurants(user):
    """Every restaurant this user is allowed to work on."""
    from apps.restaurants.models import Restaurant

    role = getattr(user, 'role', None)
    if role == 'RESTAURANT_OWNER':
        return Restaurant.objects.filter(owner=user)
    if role in ('RESTAURANT_STAFF', 'DELIVERY_STAFF'):
        return Restaurant.objects.filter(staff_members__user=user, staff_members__is_active=True).distinct()
    if role == 'SUPER_ADMIN':
        return Restaurant.objects.all()
    return Restaurant.objects.none()


def requested_id(request):
    """The restaurant id the website asked for, or None."""
    raw = None
    query = getattr(request, 'query_params', None)
    if query is not None:
        raw = query.get(PARAM)
    raw = raw or request.META.get(HEADER_META)
    raw = (raw or '').strip()
    return raw or None


def active_restaurant(request, required=True):
    """
    The restaurant the person is working on: the one they asked for, or their oldest one.
    Raises 404 if they asked for one they cannot access (or have none and `required` is True).
    """
    restaurants = my_restaurants(request.user)
    rid = requested_id(request)
    if rid:
        try:
            return restaurants.get(pk=rid)
        except (restaurants.model.DoesNotExist, ValueError, DjangoValidationError):
            raise Http404('That restaurant is not available to this account.')
    restaurant = restaurants.order_by('created_at').first()
    if restaurant is None and required:
        raise Http404('No restaurant is linked to this account.')
    return restaurant


def scope_queryset(queryset, request, field='restaurant'):
    """
    Narrow a queryset to the active restaurant when the website named one.
    `field` is the path to the restaurant, e.g. 'restaurant' or 'order__restaurant'.
    Without a named restaurant the queryset is returned unchanged.
    """
    if not requested_id(request):
        return queryset
    return queryset.filter(**{field: active_restaurant(request)})