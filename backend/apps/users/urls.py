from django.urls import path

from . import views

app_name = "users"

urlpatterns = [
    path(
        "auth/register/",
        views.UserRegisterView.as_view(),
        name='user-register'
    )
]