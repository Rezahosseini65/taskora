
from django.urls import path

from . import views

app_name = "users"

urlpatterns = [
    path(
        "auth/register/",
        views.UserRegisterView.as_view(),
        name="user-register"
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
    path(
        "auth/logout/",
        views.UserLogoutView.as_view(),
        name="user-logout"
    ),
    path(
        "auth/refresh/",
        views.RefreshAccessTokenView.as_view(),
        name="token-refresh",
    ),
    path(
        "auth/email/verify/",
        views.EmailVerificationView.as_view(),
        name="email-verify",
    ),
    path(
        "auth/email/resend/",
        views.ResendVerificationEmailView.as_view(),
        name="email-resend",
    ),
    path(
        "auth/password/change/",
        views.UserChangePasswordView.as_view(),
        name="user-change-password",
    ),
    path(
        "auth/password/forgot/",
        views.ForgotPasswordView.as_view(),
        name="forgot-password",
    ),
    path(
        "auth/password/reset/",
        views.ResetPasswordView.as_view(),
        name="reset-password",
    ),
    path(
        "auth/me/",
        views.UserMeView.as_view(),
        name="me",
    ),
    path(
        "auth/sessions/",
        views.UserSessionListView.as_view(),
        name="user-session-list",
    ),
    path(
        "auth/sessions/<uuid:session_id>/",
        views.UserSessionRevokeView.as_view(),
        name="user-session-revoke",
    ),
    path(
        "auth/sessions/logout-all/",
        views.UserLogoutAllSessionsView.as_view(),
        name="user-session-logout-all",
    ),
]
