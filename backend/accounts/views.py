from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from django.db import transaction
from rest_framework.authentication import TokenAuthentication
from rest_framework.authtoken.models import Token
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import UserProfile, generate_username
from .serializers import UserProfileSerializer, UserSerializer


def _auth_response(user, profile):
    token, _ = Token.objects.get_or_create(user=user)
    return {
        'token': token.key,
        'user': UserSerializer(user).data,
        'profile': UserProfileSerializer(profile).data,
    }


class RegisterView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
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

    def post(self, request):
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
