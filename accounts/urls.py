# accounts/urls.py
from django.urls import path
from .views import RegisterAPIView, LoginAPIView, LogoutAPIView, UserProfileAPIView

urlpatterns = [
    # API Auth URLs
    path('register/', RegisterAPIView.as_view(), name='register'),
    path('login/', LoginAPIView.as_view(), name='login'),
    path('logout/', LogoutAPIView.as_view(), name='logout'),
    path('profile/', UserProfileAPIView.as_view(), name='profile'),
]