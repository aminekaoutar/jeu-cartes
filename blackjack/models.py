import uuid

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models


class Suit(models.TextChoices):
    HEARTS = "H", "Coeur"
    DIAMONDS = "D", "Carreau"
    CLUBS = "C", "Trefle"
    SPADES = "S", "Pique"


class Rank(models.TextChoices):
    TWO = "2", "2"
    THREE = "3", "3"
    FOUR = "4", "4"
    FIVE = "5", "5"
    SIX = "6", "6"
    SEVEN = "7", "7"
    EIGHT = "8", "8"
    NINE = "9", "9"
    TEN = "10", "10"
    JACK = "J", "Valet"
    QUEEN = "Q", "Dame"
    KING = "K", "Roi"
    ACE = "A", "As"


class Card(models.Model):
    """Canonical catalog of the 52 standard playing cards (reference data)."""

    suit = models.CharField(max_length=1, choices=Suit.choices)
    rank = models.CharField(max_length=2, choices=Rank.choices)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["suit", "rank"], name="unique_suit_rank"),
        ]
        indexes = [models.Index(fields=["suit", "rank"])]
        ordering = ["suit", "rank"]

    def __str__(self):
        return self.code

    @property
    def code(self):
        """Short identifier used across Deck/Hand JSON payloads, e.g. 'AS', '10H'."""
        return f"{self.rank}{self.suit}"

    @property
    def blackjack_value(self):
        if self.rank == Rank.ACE:
            return 11
        if self.rank in (Rank.JACK, Rank.QUEEN, Rank.KING):
            return 10
        return int(self.rank)


class Deck(models.Model):
    """The single shoe of cards attached to a Game. Cards are tracked as
    compact string codes (rank+suit) rather than Card FKs so draw/shuffle
    stay cheap in-memory list operations backed by a JSONField.
    """

    game = models.OneToOneField("Game", on_delete=models.CASCADE, related_name="deck")
    cards_remaining = models.JSONField(default=list)
    discard_pile = models.JSONField(default=list)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Deck<game={self.game_id}, remaining={len(self.cards_remaining)}>"

    def build(self):
        """(Re)populate with a fresh, ordered 52-card set."""
        self.cards_remaining = [f"{rank}{suit}" for suit in Suit.values for rank in Rank.values]
        self.discard_pile = []

    def shuffle(self):
        import random

        random.shuffle(self.cards_remaining)

    def draw(self):
        """Pop and return one card code, reshuffling the discard pile back
        into play automatically if the shoe runs empty. When both piles are
        empty the shoe is rebuilt minus the cards currently held in hands,
        so a card can never exist twice on the table.
        """
        if not self.cards_remaining:
            if self.discard_pile:
                self.cards_remaining, self.discard_pile = self.discard_pile, []
            else:
                self.build()
                in_play = set(self.game.dealer_hand)
                for hand in self.game.participations.values_list("hand", flat=True):
                    in_play.update(hand)
                self.cards_remaining = [c for c in self.cards_remaining if c not in in_play]
            self.shuffle()
        return self.cards_remaining.pop()


class GameStatus(models.TextChoices):
    EN_ATTENTE = "EN_ATTENTE", "En attente"
    EN_COURS = "EN_COURS", "En cours"
    TERMINEE = "TERMINEE", "Terminee"


class Game(models.Model):
    """A blackjack table. Tracks the round state machine; per-seat hand
    state lives on Participation, dealer hand lives here since the dealer
    is not a Player row.
    """

    code = models.CharField(max_length=8, unique=True, editable=False)
    host = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="hosted_games"
    )
    status = models.CharField(
        max_length=12, choices=GameStatus.choices, default=GameStatus.EN_ATTENTE
    )
    max_players = models.PositiveSmallIntegerField(default=3, validators=[MinValueValidator(1)])
    current_turn_seat = models.PositiveSmallIntegerField(null=True, blank=True)
    dealer_hand = models.JSONField(default=list)
    dealer_revealed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["created_at"]),
        ]
        ordering = ["-created_at"]

    def __str__(self):
        return f"Game<{self.code}> [{self.status}]"

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = uuid.uuid4().hex[:8].upper()
        super().save(*args, **kwargs)


class SeatStatus(models.TextChoices):
    WAITING = "WAITING", "En attente"
    PLAYING = "PLAYING", "En jeu"
    STOOD = "STOOD", "Reste"
    BUST = "BUST", "Depasse"
    BLACKJACK = "BLACKJACK", "Blackjack"
    LEFT = "LEFT", "Parti"


class RoundResult(models.TextChoices):
    PENDING = "PENDING", "En attente"
    WIN = "WIN", "Gagne"
    LOSE = "LOSE", "Perdu"
    PUSH = "PUSH", "Egalite"
    BLACKJACK = "BLACKJACK", "Blackjack"


class Participation(models.Model):
    """A player's seat at a Game table, holding their current-round hand,
    bet and outcome. One row per (game, player); reused across rounds.
    """

    game = models.ForeignKey(Game, on_delete=models.CASCADE, related_name="participations")
    player = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="participations"
    )
    seat = models.PositiveSmallIntegerField()
    hand = models.JSONField(default=list)
    bet = models.PositiveIntegerField(default=10)
    status = models.CharField(max_length=12, choices=SeatStatus.choices, default=SeatStatus.WAITING)
    result = models.CharField(
        max_length=12, choices=RoundResult.choices, default=RoundResult.PENDING
    )
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["game", "player"], name="unique_player_per_game"),
            models.UniqueConstraint(fields=["game", "seat"], name="unique_seat_per_game"),
        ]
        indexes = [models.Index(fields=["game", "status"])]
        ordering = ["seat"]

    def __str__(self):
        return f"{self.player} @ {self.game.code} (seat {self.seat})"


class Profile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile"
    )
    chips = models.PositiveIntegerField(default=1000)
    games_played = models.PositiveIntegerField(default=0)
    games_won = models.PositiveIntegerField(default=0)
    games_lost = models.PositiveIntegerField(default=0)
    games_pushed = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["user"])]

    def __str__(self):
        return f"Profile<{self.user.username}>"

    @property
    def win_rate(self):
        if not self.games_played:
            return 0.0
        return round(100 * self.games_won / self.games_played, 1)


class MoveAction(models.TextChoices):
    DEAL = "DEAL", "Distribution"
    HIT = "HIT", "Tirer"
    STAND = "STAND", "Rester"
    DOUBLE = "DOUBLE", "Doubler"
    BUST = "BUST", "Depasse"
    BLACKJACK = "BLACKJACK", "Blackjack"
    DEALER_HIT = "DEALER_HIT", "Tirage croupier"
    DEALER_STAND = "DEALER_STAND", "Croupier reste"
    ROUND_END = "ROUND_END", "Fin de manche"


class MoveLog(models.Model):
    """Append-only, traceable history of every action taken in a game."""

    game = models.ForeignKey(Game, on_delete=models.CASCADE, related_name="moves")
    player = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="moves",
    )
    action = models.CharField(max_length=12, choices=MoveAction.choices)
    card = models.CharField(max_length=3, blank=True)
    hand_total = models.PositiveSmallIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["game", "created_at"])]
        ordering = ["created_at"]

    def __str__(self):
        who = self.player or "dealer"
        return f"[{self.game.code}] {who}: {self.action}"
