from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm

User = get_user_model()


class SignUpForm(UserCreationForm):
    email = forms.EmailField(required=False)

    class Meta:
        model = User
        fields = ("username", "email", "password1", "password2")


class CreateGameForm(forms.Form):
    max_players = forms.IntegerField(min_value=1, max_value=6, initial=3, label="Places à la table")
    bet = forms.IntegerField(min_value=1, initial=10, label="Mise (jetons)")


class JoinGameForm(forms.Form):
    bet = forms.IntegerField(min_value=1, initial=10, label="Mise (jetons)")
