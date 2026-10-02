from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from django.db import transaction
from rest_framework.authentication import TokenAuthentication
from rest_framework.authtoken.models import Token
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from api.throttling import LoginIPThrottle, LoginUsernameThrottle, RegisterIPThrottle, get_client_ip
from api.turnstile import turnstile_enabled, verify_turnstile

from .models import UserProfile, generate_username
from .serializers import UserProfileSerializer, UserSerializer


def _auth_response(user, profile):
    token, _ = Token.objects.get_or_create(user=user)
    return {
        'token': token.key,
        'user': UserSerializer(user).data,
        'profile': UserProfileSerializer(profile).data,
    }


def _non_object_body(request):
    if isinstance(request.data, dict):
        return None
    return Response({'non_field_errors': ['Expected a JSON object.']}, status=400)


class RegisterView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [RegisterIPThrottle]

    def post(self, request):
        if (error := _non_object_body(request)) is not None:
            return error
        # Checked before anything else so bots learn nothing (e.g. whether a username exists).
        if turnstile_enabled() and not verify_turnstile(request.data.get('turnstile_token'), get_client_ip(request)):
            return Response({'turnstile': ['Human verification failed. Please try again.']}, status=400)
        username = (request.data.get('username') or '').strip() or generate_username()
        password = request.data.get('password', '')

        if not password:
            return Response({'password': ['Password is required.']}, status=400)

        if User.objects.filter(username=username).exists():
            return Response({'username': ['A user with that username already exists.']}, status=400)

        with transaction.atomic():
            user = User.objects.create_user(
                username=username,
                password=password,
                email=request.data.get('email', ''),
            )
            profile = UserProfile.objects.create(
                user=user,
                age_range=request.data.get('age_range', ''),
                country=request.data.get('country', ''),
                us_state=request.data.get('us_state', ''),
                gender=request.data.get('gender', ''),
            )
        return Response(_auth_response(user, profile), status=201)


class LoginView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [LoginIPThrottle, LoginUsernameThrottle]

    def post(self, request):
        if (error := _non_object_body(request)) is not None:
            return error
        username = request.data.get('username', '')
        password = request.data.get('password', '')
        user = authenticate(request, username=username, password=password)
        if user is None:
            return Response(
                {'non_field_errors': ['Unable to log in with provided credentials.']},
                status=400,
            )
        profile, _ = UserProfile.objects.get_or_create(user=user)
        return Response(_auth_response(user, profile))


class LogoutView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [AllowAny]

    def post(self, request):
        if request.user.is_authenticated:
            Token.objects.filter(user=request.user).delete()
        return Response(status=204)


class ProfileView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [AllowAny]

    def get(self, request):
        if not request.user.is_authenticated:
            return Response({'detail': 'Authentication credentials were not provided.'}, status=401)
        profile, _ = UserProfile.objects.get_or_create(user=request.user)
        return Response(UserProfileSerializer(profile).data)

    def patch(self, request):
        if not request.user.is_authenticated:
            return Response({'detail': 'Authentication credentials were not provided.'}, status=401)
        profile, _ = UserProfile.objects.get_or_create(user=request.user)
        for field in ('age_range', 'country', 'us_state', 'gender', 'saved_zipcode'):
            if field in request.data:
                setattr(profile, field, request.data[field])
        profile.save()
        return Response(UserProfileSerializer(profile).data)
