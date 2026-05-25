import uuid

from django.contrib.auth.models import User
from django.db import models


class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='civic_profile')
    age_range = models.CharField(max_length=20, blank=True)
    country = models.CharField(max_length=2, blank=True)
    us_state = models.CharField(max_length=50, blank=True)
    gender = models.CharField(max_length=50, blank=True)
    saved_zipcode = models.CharField(max_length=10, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'UserProfile({self.user.username})'


def generate_username():
    return f'user_{uuid.uuid4().hex[:10]}'
