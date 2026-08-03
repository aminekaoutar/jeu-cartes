"""Plain-dict JSON views of game state, shared by the server-rendered
templates and the AJAX/fetch endpoints so both stay in sync.
"""

from .game_engine import hand_value
from .models import GameStatus, SeatStatus, Suit

SUIT_SYMBOLS = {
    Suit.HEARTS: "♥",
    Suit.DIAMONDS: "♦",
    Suit.CLUBS: "♣",
    Suit.SPADES: "♠",
}

RED_SUITS = {Suit.HEARTS, Suit.DIAMONDS}


def card_display(code):
    rank, suit = code[:-1], code[-1]
    return {
        "code": code,
        "rank": rank,
        "suit": suit,
        "symbol": SUIT_SYMBOLS.get(suit, "?"),
        "color": "red" if suit in RED_SUITS else "black",
    }


def serialize_dealer(game):
    hand = game.dealer_hand
    if not game.dealer_revealed and len(hand) >= 1:
        visible = [card_display(hand[0])] + [{"hidden": True}] * (len(hand) - 1)
        total = None
    else:
        visible = [card_display(c) for c in hand]
        total = hand_value(hand) if hand else None
    return {"cards": visible, "total": total, "revealed": game.dealer_revealed}


def serialize_participation(p, viewer):
    return {
        "seat": p.seat,
        "username": p.player.username,
        "is_you": p.player_id == viewer.id,
        "hand": [card_display(c) for c in p.hand],
        "total": hand_value(p.hand) if p.hand else None,
        "bet": p.bet,
        "status": p.status,
        "status_label": p.get_status_display(),
        "result": p.result,
        "result_label": p.get_result_display(),
        "is_turn": p.status == SeatStatus.PLAYING and p.seat == p.game.current_turn_seat,
    }


def serialize_game(game, viewer):
    participations = list(game.participations.select_related("player").order_by("seat"))
    your_participation = next((p for p in participations if p.player_id == viewer.id), None)

    return {
        "code": game.code,
        "status": game.status,
        "status_label": game.get_status_display(),
        "is_host": game.host_id == viewer.id,
        "can_start": game.status == GameStatus.EN_ATTENTE and game.host_id == viewer.id,
        "current_turn_seat": game.current_turn_seat,
        "dealer": serialize_dealer(game),
        "players": [serialize_participation(p, viewer) for p in participations],
        "you_are_seated": your_participation is not None,
        "your_seat": your_participation.seat if your_participation else None,
        "your_turn": bool(
            your_participation
            and your_participation.status == SeatStatus.PLAYING
            and game.current_turn_seat == your_participation.seat
        ),
        "seats_free": game.max_players - len(participations),
    }
