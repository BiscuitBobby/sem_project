from django.contrib.auth.models import User
from rest_framework.test import APITestCase, APIClient
from rest_framework.authtoken.models import Token
from rest_framework.test import force_authenticate
from rest_framework import status
from django.urls import reverse

from django.test import TestCase
from unittest.mock import patch, MagicMock
from rest_framework.test import APIRequestFactory

from accounts.views import RegisterAPIView, LoginAPIView, LogoutAPIView, UserProfileAPIView

# ------------ Integration testing ------------
class AuthTests(APITestCase):

    def setUp(self):
        self.client = APIClient()
        self.register_url = reverse('register')
        self.login_url = reverse('login')
        self.logout_url = reverse('logout')
        self.profile_url = reverse('profile')

        self.user_data = {
            'username': 'testuser',
            'password': 'testpass123'
        }

        # Create a user for login/logout/profile tests
        self.user = User.objects.create_user(**self.user_data)
        self.token = Token.objects.create(user=self.user)

    def test_register_user_success(self):
        response = self.client.post(self.register_url, {
            'username': 'newuser',
            'password': 'newpass123'
        })
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn('token', response.data)
        self.assertIn('user', response.data)

    def test_register_user_invalid_data(self):
        response = self.client.post(self.register_url, {
            'username': '', 
            'password': ''
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_login_success(self):
        response = self.client.post(self.login_url, self.user_data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('token', response.data)

    def test_login_failure(self):
        response = self.client.post(self.login_url, {
            'username': 'wrong',
            'password': 'wrong'
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('error', response.data)

    def test_logout_success(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token.key)
        response = self.client.post(self.logout_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['message'], 'Successfully logged out.')

    def test_logout_unauthenticated(self):
        response = self.client.post(self.logout_url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_profile_authenticated(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token.key)
        response = self.client.get(self.profile_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['username'], self.user.username)

    def test_profile_unauthenticated(self):
        response = self.client.get(self.profile_url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


# ------------ Unit testing ------------
class RegisterAPIViewUnitTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.view = RegisterAPIView.as_view()
        self.url = '/register/'

    @patch('accounts.views.UserSerializer')
    @patch('accounts.views.Token.objects.get_or_create')
    def test_register_success(self, mock_get_token, mock_user_serializer):
        # Mocks
        mock_serializer = MagicMock()
        mock_serializer.is_valid.return_value = True
        mock_serializer.save.return_value = MagicMock()
        mock_serializer.data = {'username': 'mockeduser'}
        mock_user_serializer.return_value = mock_serializer

        mock_token = MagicMock()
        mock_token.key = 'mocked_token'
        mock_get_token.return_value = (mock_token, True)

        request = self.factory.post(self.url, {'username': 'test', 'password': 'test'})
        response = self.view(request)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['token'], 'mocked_token')

    @patch('accounts.views.UserSerializer')
    def test_register_invalid_data(self, mock_user_serializer):
        mock_serializer = MagicMock()
        mock_serializer.is_valid.return_value = False
        mock_serializer.errors = {'username': ['This field is required.']}
        mock_user_serializer.return_value = mock_serializer

        request = self.factory.post(self.url, {})
        response = self.view(request)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

class LoginAPIViewUnitTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.view = LoginAPIView.as_view()
        self.url = '/login/'

    @patch('accounts.views.authenticate')
    @patch('accounts.views.Token.objects.get_or_create')
    def test_login_success(self, mock_get_token, mock_authenticate):
        mock_user = MagicMock()
        mock_authenticate.return_value = mock_user

        mock_token = MagicMock()
        mock_token.key = 'valid_token'
        mock_get_token.return_value = (mock_token, True)

        request = self.factory.post(self.url, {'username': 'user', 'password': 'pass'})
        response = self.view(request)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['token'], 'valid_token')

    @patch('accounts.views.authenticate')
    def test_login_failure(self, mock_authenticate):
        mock_authenticate.return_value = None

        request = self.factory.post(self.url, {'username': 'user', 'password': 'wrong'})
        response = self.view(request)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('error', response.data)

class LogoutAPIViewUnitTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.view = LogoutAPIView.as_view()
        self.url = '/logout/'

    def test_logout_success(self):
        mock_user = MagicMock()
        mock_user.auth_token.delete.return_value = None

        request = self.factory.post(self.url)
        force_authenticate(request, user=mock_user)  # <-- Authenticates the request
        response = self.view(request)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['message'], 'Successfully logged out.')


    def test_logout_exception(self):
        mock_user = MagicMock()
        mock_user.auth_token.delete.side_effect = Exception("Deletion error")

        request = self.factory.post(self.url)
        force_authenticate(request, user=mock_user)  # <-- Authenticates the request
        response = self.view(request)

        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        self.assertIn('error', response.data)


class UserProfileAPIViewUnitTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.view = UserProfileAPIView.as_view()
        self.url = '/profile/'

    @patch('accounts.views.UserSerializer')
    def test_get_profile(self, mock_serializer_class):
        mock_user = MagicMock(username='mockeduser')
        mock_serializer = MagicMock()
        mock_serializer.data = {'username': 'mockeduser'}
        mock_serializer_class.return_value = mock_serializer

        request = self.factory.get(self.url)
        force_authenticate(request, user=mock_user)  # <-- Authenticates the request
        response = self.view(request)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['username'], 'mockeduser')
