from django.urls import path

from . import views

app_name = "users"

urlpatterns = [
    path(
        "auth/register/",
        views.UserRegisterView.as_view(),
        name='user-register'
    ),
    path(
        "auth/login/",
        views.UserLoginView.as_view(),
        name="user-login"
    ),
    path(
        "auth/csrf/",
        views.CSRFTokenView.as_view(),
        name="csrf-token"
    ),
]
