from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

app_name = "blackjack"

urlpatterns = [
    path("", views.lobby, name="lobby"),
    path("signup/", views.signup, name="signup"),
    path(
        "login/",
        auth_views.LoginView.as_view(template_name="blackjack/login.html"),
        name="login",
    ),
    path("logout/", auth_views.LogoutView.as_view(next_page="blackjack:login"), name="logout"),
    path("profile/", views.profile_view, name="profile"),
    path("games/<str:code>/", views.table, name="table"),
    path("games/<str:code>/state/", views.game_state, name="game_state"),
    path("games/<str:code>/join/", views.game_join, name="game_join"),
    path("games/<str:code>/leave/", views.game_leave, name="game_leave"),
    path("games/<str:code>/start/", views.game_start, name="game_start"),
    path("games/<str:code>/action/", views.game_action, name="game_action"),
]
