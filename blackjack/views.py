import json

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from . import game_engine
from .forms import CreateGameForm, JoinGameForm, SignUpForm
from .models import Game, GameStatus
from .serializers import serialize_game

ACTIONS = {
    "hit": game_engine.player_hit,
    "stand": game_engine.player_stand,
    "double": game_engine.player_double,
}


def signup(request):
    if request.user.is_authenticated:
        return redirect("blackjack:lobby")
    if request.method == "POST":
        form = SignUpForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            messages.success(request, "Bienvenue à la table ! Vous démarrez avec 1000 jetons.")
            return redirect("blackjack:lobby")
    else:
        form = SignUpForm()
    return render(request, "blackjack/signup.html", {"form": form})


@login_required
def lobby(request):
    if request.method == "POST":
        form = CreateGameForm(request.POST)
        if form.is_valid():
            try:
                game = game_engine.create_game(
                    request.user,
                    max_players=form.cleaned_data["max_players"],
                    bet=form.cleaned_data["bet"],
                )
            except game_engine.IllegalMoveError as exc:
                messages.error(request, str(exc))
            else:
                return redirect("blackjack:table", code=game.code)
    else:
        form = CreateGameForm()

    open_games = (
        Game.objects.filter(status=GameStatus.EN_ATTENTE)
        .select_related("host")
        .prefetch_related("participations")
    )
    my_games = (
        Game.objects.filter(participations__player=request.user)
        .exclude(status=GameStatus.EN_ATTENTE)
        .select_related("host")
        .distinct()
        .order_by("-updated_at")[:10]
    )
    return render(
        request,
        "blackjack/lobby.html",
        {
            "form": form,
            "open_games": open_games,
            "my_games": my_games,
            "profile": request.user.profile,
        },
    )


@login_required
def table(request, code):
    game = get_object_or_404(Game, code=code)
    return render(
        request,
        "blackjack/table.html",
        {"game": game, "state": serialize_game(game, request.user)},
    )


@login_required
def game_state(request, code):
    game = get_object_or_404(Game, code=code)
    return JsonResponse(serialize_game(game, request.user))


@login_required
@require_POST
def game_join(request, code):
    game = get_object_or_404(Game, code=code)
    form = JoinGameForm(request.POST)
    bet = form.cleaned_data["bet"] if form.is_valid() else 10
    try:
        with transaction.atomic():
            game = Game.objects.select_for_update().get(pk=game.pk)
            game_engine.join_game(game, request.user, bet=bet)
    except game_engine.IllegalMoveError as exc:
        messages.error(request, str(exc))
    return redirect("blackjack:table", code=code)


@login_required
@require_POST
def game_leave(request, code):
    game = get_object_or_404(Game, code=code)
    with transaction.atomic():
        game = Game.objects.select_for_update().get(pk=game.pk)
        game_engine.leave_game(game, request.user)
    return redirect("blackjack:lobby")


@login_required
@require_POST
def game_start(request, code):
    game = get_object_or_404(Game, code=code)
    try:
        with transaction.atomic():
            game = Game.objects.select_for_update().get(pk=game.pk)
            game_engine.start_game(game, request.user)
    except game_engine.IllegalMoveError as exc:
        messages.error(request, str(exc))
    return redirect("blackjack:table", code=code)


@login_required
@require_POST
def game_action(request, code):
    """AJAX endpoint: {"action": "hit" | "stand" | "double"} -> updated state JSON."""
    try:
        payload = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        payload = request.POST
    action = payload.get("action")
    handler = ACTIONS.get(action)
    if handler is None:
        return JsonResponse({"error": "Action inconnue."}, status=400)

    game = get_object_or_404(Game, code=code)
    try:
        with transaction.atomic():
            game = Game.objects.select_for_update().get(pk=game.pk)
            handler(game, request.user)
    except game_engine.IllegalMoveError as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    game.refresh_from_db()
    return JsonResponse(serialize_game(game, request.user))


@login_required
def profile_view(request):
    profile = request.user.profile
    recent_games = (
        Game.objects.filter(participations__player=request.user)
        .exclude(status=GameStatus.EN_ATTENTE)
        .distinct()
        .order_by("-updated_at")[:15]
    )
    return render(
        request,
        "blackjack/profile.html",
        {"profile": profile, "recent_games": recent_games},
    )
