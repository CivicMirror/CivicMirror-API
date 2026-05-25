from django.urls import path

from .views import LoginView, LogoutView, ProfileView, RegisterView

urlpatterns = [
    path('auth/login/', LoginView.as_view(), name='auth-login'),
    path('auth/register/', RegisterView.as_view(), name='auth-register'),
    path('auth/logout/', LogoutView.as_view(), name='auth-logout'),
    path('users/me/profile/', ProfileView.as_view(), name='user-profile'),
]
