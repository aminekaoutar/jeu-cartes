"""Blackjack rules engine.

Deliberately kept free of Django views/HTTP concerns (SRP): every function
here takes plain model instances and users, validates the move against the
current game state, and raises IllegalMoveError on any rule violation so a
client can never cheat by tampering with the request. Views are the only
callers, and are responsible for wrapping mutating calls in a locked
transaction (select_for_update on Game) to keep concurrent turns consistent.
"""

from .models import (
    Deck,
    Game,
    GameStatus,
    MoveAction,
    MoveLog,
    Participation,
    RoundResult,
    SeatStatus,
)

DEALER_STAND_TOTAL = 17


class IllegalMoveError(Exception):
    """Raised whenever a requested action violates the game's rules or state."""


def _evaluate(cards):
    """Return (total, is_soft) for a list of card codes, applying the
    standard ace-as-11-or-1 downgrade rule.
    """
    total = 0
    aces = 0
    for code in cards:
        rank = code[:-1]
        if rank == "A":
            aces += 1
            total += 11
        elif rank in ("J", "Q", "K"):
            total += 10
        else:
            total += int(rank)
    soft = aces > 0
    while total > 21 and aces:
        total -= 10
        aces -= 1
        soft = aces > 0
    return total, soft


def hand_value(cards):
    return _evaluate(cards)[0]


def is_bust(cards):
    return hand_value(cards) > 21


def is_blackjack(cards):
    return len(cards) == 2 and hand_value(cards) == 21


def create_game(host, max_players=3, bet=10):
    game = Game.objects.create(host=host, max_players=max_players)
    join_game(game, host, bet=bet)
    return game


def join_game(game, user, bet=10):
    if game.status != GameStatus.EN_ATTENTE:
        raise IllegalMoveError("Cette partie a déjà commencé.")
    if game.participations.filter(player=user).exists():
        raise IllegalMoveError("Vous participez déjà à cette partie.")
    if bet <= 0:
        raise IllegalMoveError("La mise doit être positive.")
    seats_taken = game.participations.count()
    if seats_taken >= game.max_players:
        raise IllegalMoveError("La table est complète.")
    profile = user.profile
    if profile.chips < bet:
        raise IllegalMoveError("Solde de jetons insuffisant.")
    profile.chips -= bet
    profile.save()
    return Participation.objects.create(game=game, player=user, seat=seats_taken, bet=bet)


def leave_game(game, user):
    try:
        participation = game.participations.get(player=user)
    except Participation.DoesNotExist:
        return
    if game.status == GameStatus.EN_ATTENTE:
        profile = user.profile
        profile.chips += participation.bet
        profile.save()
        participation.delete()
    else:
        participation.status = SeatStatus.LEFT
        participation.save()
        if game.current_turn_seat == participation.seat:
            _advance_turn(game)


def _first_playing_seat(participations):
    for p in participations:
        if p.status == SeatStatus.PLAYING:
            return p.seat
    return None


def start_game(game, actor):
    if game.status != GameStatus.EN_ATTENTE:
        raise IllegalMoveError("La partie a déjà démarré.")
    if actor.id != game.host_id:
        raise IllegalMoveError("Seul l'hôte peut démarrer la partie.")

    participations = list(game.participations.select_related("player").order_by("seat"))
    if not participations:
        raise IllegalMoveError("Il faut au moins un joueur pour démarrer.")

    deck, _ = Deck.objects.get_or_create(game=game)
    deck.build()
    deck.shuffle()

    game.dealer_hand = []
    game.dealer_revealed = False

    for p in participations:
        p.hand = []
        p.status = SeatStatus.PLAYING
        p.result = RoundResult.PENDING

    for _ in range(2):
        for p in participations:
            p.hand.append(deck.draw())
        game.dealer_hand.append(deck.draw())

    for p in participations:
        p.save()
        _log_move(game, p.player, MoveAction.DEAL, hand_total=hand_value(p.hand))
    _log_move(game, None, MoveAction.DEAL, hand_total=hand_value(game.dealer_hand))

    deck.save()

    for p in participations:
        if is_blackjack(p.hand):
            p.status = SeatStatus.BLACKJACK
            p.save()
            _log_move(game, p.player, MoveAction.BLACKJACK, hand_total=21)

    game.status = GameStatus.EN_COURS
    game.current_turn_seat = _first_playing_seat(participations)
    game.save()

    if game.current_turn_seat is None:
        _dealer_play(game)
        _settle_round(game)

    return game


def _get_participation(game, user):
    try:
        return game.participations.get(player=user)
    except Participation.DoesNotExist:
        raise IllegalMoveError("Vous ne participez pas à cette partie.") from None


def _assert_players_turn(game, participation):
    if game.status != GameStatus.EN_COURS:
        raise IllegalMoveError("La partie n'est pas en cours.")
    if participation.status != SeatStatus.PLAYING:
        raise IllegalMoveError("Ce n'est pas à vous de jouer.")
    if game.current_turn_seat != participation.seat:
        raise IllegalMoveError("Ce n'est pas votre tour.")


def player_hit(game, user):
    participation = _get_participation(game, user)
    _assert_players_turn(game, participation)

    deck = game.deck
    card = deck.draw()
    deck.save()

    participation.hand.append(card)
    total = hand_value(participation.hand)
    _log_move(game, user, MoveAction.HIT, card=card, hand_total=total)

    if total > 21:
        participation.status = SeatStatus.BUST
        _log_move(game, user, MoveAction.BUST, hand_total=total)
    participation.save()

    if participation.status == SeatStatus.PLAYING:
        game.save()
    else:
        _advance_turn(game)

    return participation


def player_stand(game, user):
    participation = _get_participation(game, user)
    _assert_players_turn(game, participation)

    participation.status = SeatStatus.STOOD
    participation.save()
    _log_move(game, user, MoveAction.STAND, hand_total=hand_value(participation.hand))

    _advance_turn(game)
    return participation


def player_double(game, user):
    participation = _get_participation(game, user)
    _assert_players_turn(game, participation)
    if len(participation.hand) != 2:
        raise IllegalMoveError("Vous ne pouvez doubler qu'au premier tour.")

    profile = user.profile
    if profile.chips < participation.bet:
        raise IllegalMoveError("Solde de jetons insuffisant pour doubler.")
    profile.chips -= participation.bet
    profile.save()
    participation.bet *= 2

    deck = game.deck
    card = deck.draw()
    deck.save()
    participation.hand.append(card)
    total = hand_value(participation.hand)
    _log_move(game, user, MoveAction.DOUBLE, card=card, hand_total=total)

    if total > 21:
        participation.status = SeatStatus.BUST
        _log_move(game, user, MoveAction.BUST, hand_total=total)
    else:
        participation.status = SeatStatus.STOOD
    participation.save()

    _advance_turn(game)
    return participation


def _advance_turn(game):
    participations = list(game.participations.order_by("seat"))
    current_seat = game.current_turn_seat if game.current_turn_seat is not None else -1
    remaining = [p for p in participations if p.status == SeatStatus.PLAYING]

    next_seat = None
    if remaining:
        upcoming = [p for p in remaining if p.seat > current_seat]
        next_seat = upcoming[0].seat if upcoming else remaining[0].seat

    if next_seat is None:
        _dealer_play(game)
        _settle_round(game)
    else:
        game.current_turn_seat = next_seat
        game.save()


def _dealer_play(game):
    game.dealer_revealed = True
    deck = game.deck
    total, soft = _evaluate(game.dealer_hand)

    while total < DEALER_STAND_TOTAL or (total == DEALER_STAND_TOTAL and soft):
        card = deck.draw()
        game.dealer_hand.append(card)
        total, soft = _evaluate(game.dealer_hand)
        _log_move(game, None, MoveAction.DEALER_HIT, card=card, hand_total=total)

    deck.save()
    _log_move(game, None, MoveAction.DEALER_STAND, hand_total=total)
    game.save()


def _settle_round(game):
    dealer_total, _ = _evaluate(game.dealer_hand)
    dealer_bust = dealer_total > 21
    dealer_blackjack = is_blackjack(game.dealer_hand)

    for p in game.participations.select_related("player__profile"):
        if p.status == SeatStatus.LEFT:
            continue

        payout = 0
        if p.status == SeatStatus.BUST:
            p.result = RoundResult.LOSE
        elif p.status == SeatStatus.BLACKJACK:
            if dealer_blackjack:
                p.result = RoundResult.PUSH
                payout = p.bet
            else:
                p.result = RoundResult.BLACKJACK
                payout = p.bet + (p.bet * 3) // 2
        else:  # STOOD
            p_total = hand_value(p.hand)
            if dealer_blackjack:
                p.result = RoundResult.LOSE
            elif dealer_bust or p_total > dealer_total:
                p.result = RoundResult.WIN
                payout = p.bet * 2
            elif p_total == dealer_total:
                p.result = RoundResult.PUSH
                payout = p.bet
            else:
                p.result = RoundResult.LOSE
        p.save()

        profile = p.player.profile
        profile.games_played += 1
        if p.result in (RoundResult.WIN, RoundResult.BLACKJACK):
            profile.games_won += 1
        elif p.result == RoundResult.PUSH:
            profile.games_pushed += 1
        else:
            profile.games_lost += 1
        profile.chips += payout
        profile.save()

    _log_move(game, None, MoveAction.ROUND_END, hand_total=dealer_total)
    game.status = GameStatus.TERMINEE
    game.current_turn_seat = None
    game.save()


def _log_move(game, player, action, card="", hand_total=None):
    MoveLog.objects.create(
        game=game,
        player=player,
        action=action,
        card=card,
        hand_total=hand_total,
    )
