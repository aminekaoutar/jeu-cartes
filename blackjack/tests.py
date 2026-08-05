import json

from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.test import TestCase
from django.urls import reverse

from . import game_engine as ge
from .models import Deck, Game, GameStatus, Participation, RoundResult, SeatStatus

User = get_user_model()


def make_user(username, chips=1000):
    user = User.objects.create_user(username=username, password="testpass123")
    user.profile.chips = chips
    user.profile.save()
    return user


# ---------------------------------------------------------------------------
# Unit tests: hand scoring
# ---------------------------------------------------------------------------


class HandValueTests(TestCase):
    def test_face_cards_are_worth_ten(self):
        self.assertEqual(ge.hand_value(["KH", "QD"]), 20)

    def test_ace_counts_as_eleven_when_safe(self):
        self.assertEqual(ge.hand_value(["AS", "9H"]), 20)

    def test_ace_downgrades_to_avoid_bust(self):
        self.assertEqual(ge.hand_value(["AS", "9H", "5C"]), 15)

    def test_multiple_aces_downgrade_independently(self):
        self.assertEqual(ge.hand_value(["AS", "AH", "9C"]), 21)
        self.assertEqual(ge.hand_value(["AS", "AH", "AC", "9C"]), 12)

    def test_is_bust(self):
        self.assertTrue(ge.is_bust(["KH", "QD", "5C"]))
        self.assertFalse(ge.is_bust(["KH", "QD"]))

    def test_natural_blackjack(self):
        self.assertTrue(ge.is_blackjack(["AS", "KH"]))

    def test_twenty_one_over_three_cards_is_not_a_natural(self):
        self.assertFalse(ge.is_blackjack(["7S", "7H", "7C"]))


# ---------------------------------------------------------------------------
# Unit tests: Deck.draw() / Deck.shuffle()
# ---------------------------------------------------------------------------


class DeckTests(TestCase):
    def setUp(self):
        self.host = make_user("deckhost")
        self.game = Game.objects.create(host=self.host)
        self.deck = Deck.objects.create(game=self.game)

    def test_build_creates_fifty_two_unique_cards(self):
        self.deck.build()
        self.assertEqual(len(self.deck.cards_remaining), 52)
        self.assertEqual(len(set(self.deck.cards_remaining)), 52)

    def test_draw_removes_a_card_from_the_shoe(self):
        self.deck.build()
        card = self.deck.draw()
        self.assertNotIn(card, self.deck.cards_remaining)
        self.assertEqual(len(self.deck.cards_remaining), 51)

    def test_exhausted_shoe_rebuild_excludes_cards_in_play(self):
        """Rebuilding an exhausted shoe must never reintroduce a card that is
        currently held in a player's or the dealer's hand (no duplicates).
        """
        Participation.objects.create(game=self.game, player=self.host, seat=0, hand=["AS", "KD"])
        self.game.dealer_hand = ["QH", "7C"]
        self.game.save()
        self.deck.cards_remaining = []
        self.deck.discard_pile = []

        drawn = [self.deck.draw() for _ in range(48)]

        self.assertEqual(len(set(drawn)), 48)
        for held in ("AS", "KD", "QH", "7C"):
            self.assertNotIn(held, drawn)
        self.assertEqual(self.deck.cards_remaining, [])

    def test_draw_reshuffles_a_fresh_shoe_once_empty(self):
        self.deck.cards_remaining = []
        self.deck.discard_pile = []
        card = self.deck.draw()
        self.assertIn(
            card,
            [
                f"{r}{s}"
                for s in "HDCS"
                for r in ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"]
            ],
        )
        self.assertEqual(len(self.deck.cards_remaining), 51)


# ---------------------------------------------------------------------------
# Engine: table lifecycle (join/leave/start) and validation
# ---------------------------------------------------------------------------


class TableLifecycleTests(TestCase):
    def setUp(self):
        self.host = make_user("host")
        self.guest = make_user("guest")

    def test_join_deducts_chips_and_assigns_seats(self):
        game = ge.create_game(self.host, max_players=2, bet=50)
        ge.join_game(game, self.guest, bet=30)

        self.host.profile.refresh_from_db()
        self.guest.profile.refresh_from_db()
        self.assertEqual(self.host.profile.chips, 950)
        self.assertEqual(self.guest.profile.chips, 970)
        self.assertEqual(game.participations.get(player=self.guest).seat, 1)

    def test_join_full_table_is_rejected(self):
        game = ge.create_game(self.host, max_players=1, bet=10)
        with self.assertRaises(ge.IllegalMoveError):
            ge.join_game(game, self.guest, bet=10)

    def test_join_with_insufficient_chips_is_rejected(self):
        poor = make_user("poor", chips=5)
        game = ge.create_game(self.host, max_players=2, bet=10)
        with self.assertRaises(ge.IllegalMoveError):
            ge.join_game(game, poor, bet=10)

    def test_leave_before_start_refunds_bet(self):
        game = ge.create_game(self.host, max_players=2, bet=50)
        ge.join_game(game, self.guest, bet=30)
        ge.leave_game(game, self.guest)

        self.guest.profile.refresh_from_db()
        self.assertEqual(self.guest.profile.chips, 1000)
        self.assertFalse(game.participations.filter(player=self.guest).exists())

    def test_only_host_can_start(self):
        game = ge.create_game(self.host, max_players=2, bet=10)
        ge.join_game(game, self.guest, bet=10)
        with self.assertRaises(ge.IllegalMoveError):
            ge.start_game(game, self.guest)

    def test_start_deals_two_cards_and_moves_to_en_cours(self):
        game = ge.create_game(self.host, max_players=1, bet=10)
        ge.start_game(game, self.host)
        game.refresh_from_db()

        participation = game.participations.get(player=self.host)
        self.assertIn(game.status, {GameStatus.EN_COURS, GameStatus.TERMINEE})
        self.assertEqual(len(participation.hand), 2)
        self.assertEqual(len(game.dealer_hand), 2)

    def test_cannot_start_twice(self):
        game = ge.create_game(self.host, max_players=1, bet=10)
        ge.start_game(game, self.host)
        game.refresh_from_db()
        with self.assertRaises(ge.IllegalMoveError):
            ge.start_game(game, self.host)


# ---------------------------------------------------------------------------
# Engine: turn validation and full-round settlement (deterministic hands)
# ---------------------------------------------------------------------------


class RoundSettlementTests(TestCase):
    """Drives rounds with hands forced to known values (bypassing the random
    deal) so score calculation and chip settlement are exercised
    deterministically, independent of shuffle order.
    """

    def setUp(self):
        self.host = make_user("player", chips=1000)
        self.game = ge.create_game(self.host, max_players=1, bet=100)
        Deck.objects.create(game=self.game)
        self.participation = self.game.participations.get(player=self.host)

    def _force_round(self, player_hand, dealer_hand):
        self.participation.hand = player_hand
        self.participation.status = SeatStatus.PLAYING
        self.participation.result = RoundResult.PENDING
        self.participation.save()

        self.game.dealer_hand = dealer_hand
        self.game.status = GameStatus.EN_COURS
        self.game.current_turn_seat = self.participation.seat
        self.game.save()

    def test_stand_out_of_turn_is_rejected(self):
        self._force_round(["10S", "9S"], ["10H", "9H"])
        self.game.current_turn_seat = 5
        self.game.save()
        with self.assertRaises(ge.IllegalMoveError):
            ge.player_stand(self.game, self.host)

    def test_player_wins_against_lower_dealer_total(self):
        self._force_round(["10S", "9S"], ["10H", "8H"])  # 19 vs 17
        ge.player_stand(self.game, self.host)

        self.participation.refresh_from_db()
        self.host.profile.refresh_from_db()
        self.assertEqual(self.participation.result, RoundResult.WIN)
        self.assertEqual(self.host.profile.chips, 1000 - 100 + 200)
        self.assertEqual(self.host.profile.games_won, 1)

    def test_push_refunds_the_bet(self):
        self._force_round(["10S", "9S"], ["10H", "9H"])  # 19 vs 19
        ge.player_stand(self.game, self.host)

        self.participation.refresh_from_db()
        self.host.profile.refresh_from_db()
        self.assertEqual(self.participation.result, RoundResult.PUSH)
        self.assertEqual(self.host.profile.chips, 1000)
        self.assertEqual(self.host.profile.games_pushed, 1)

    def test_lower_total_loses_the_bet(self):
        self._force_round(["10S", "7S"], ["10H", "9H"])  # 17 vs 19
        ge.player_stand(self.game, self.host)

        self.participation.refresh_from_db()
        self.host.profile.refresh_from_db()
        self.assertEqual(self.participation.result, RoundResult.LOSE)
        self.assertEqual(self.host.profile.chips, 900)
        self.assertEqual(self.host.profile.games_lost, 1)

    def test_hit_past_twenty_one_busts_and_settles_immediately(self):
        self._force_round(["10S", "9S"], ["2H", "3H"])
        deck = self.game.deck
        deck.cards_remaining = ["KD"]  # 19 + King -> 29, guaranteed bust
        deck.save()

        ge.player_hit(self.game, self.host)

        self.participation.refresh_from_db()
        self.host.profile.refresh_from_db()
        self.assertEqual(self.participation.status, SeatStatus.BUST)
        self.assertEqual(self.participation.result, RoundResult.LOSE)
        self.assertEqual(self.host.profile.chips, 900)
        self.assertEqual(self.game.status, GameStatus.TERMINEE)

    def test_dealer_hits_until_seventeen(self):
        self._force_round(["10S", "9S"], ["2H", "3H"])  # dealer at 5
        deck = self.game.deck
        deck.cards_remaining = ["9C"]  # dealer draws 9 -> 14, still < 17...
        deck.save()
        # Force dealer path directly: stand immediately so dealer must act.
        ge.player_stand(self.game, self.host)

        self.game.refresh_from_db()
        dealer_total = ge.hand_value(self.game.dealer_hand)
        self.assertGreaterEqual(dealer_total, 17)
        self.assertTrue(self.game.dealer_revealed)

    def test_double_requires_first_action(self):
        self._force_round(["10S", "9S"], ["10H", "9H"])
        ge.player_hit(self.game, self.host)  # hand now has 3 cards
        self.game.refresh_from_db()
        self.participation.refresh_from_db()
        if self.participation.status == SeatStatus.PLAYING:
            with self.assertRaises(ge.IllegalMoveError):
                ge.player_double(self.game, self.host)

    def test_moves_are_logged_for_traceability(self):
        self._force_round(["10S", "9S"], ["10H", "8H"])
        ge.player_stand(self.game, self.host)
        actions = list(self.game.moves.values_list("action", flat=True))
        self.assertIn("STAND", actions)
        self.assertIn("ROUND_END", actions)


# ---------------------------------------------------------------------------
# Views: auth, permissions, and the AJAX action endpoint
# ---------------------------------------------------------------------------


class ViewPermissionTests(TestCase):
    def setUp(self):
        self.host = make_user("viewhost")
        self.guest = make_user("viewguest")

    def test_lobby_requires_login(self):
        response = self.client.get(reverse("blackjack:lobby"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("blackjack:login"), response.url)

    def test_signup_creates_profile_with_starting_chips(self):
        response = self.client.post(
            reverse("blackjack:signup"),
            {
                "username": "newplayer",
                "email": "",
                "password1": "S3curePass!23",
                "password2": "S3curePass!23",
            },
        )
        self.assertEqual(response.status_code, 302)
        user = User.objects.get(username="newplayer")
        self.assertEqual(user.profile.chips, 1000)

    def test_create_game_view_redirects_to_table(self):
        self.client.login(username="viewhost", password="testpass123")
        response = self.client.post(reverse("blackjack:lobby"), {"max_players": 3, "bet": 10})
        self.assertEqual(response.status_code, 302)
        game = Game.objects.get(host=self.host)
        self.assertRedirects(response, reverse("blackjack:table", args=[game.code]))

    def test_non_host_cannot_start_game(self):
        game = ge.create_game(self.host, max_players=2, bet=10)
        ge.join_game(game, self.guest, bet=10)

        self.client.login(username="viewguest", password="testpass123")
        self.client.post(reverse("blackjack:game_start", args=[game.code]))

        game.refresh_from_db()
        self.assertEqual(game.status, GameStatus.EN_ATTENTE)

    def test_join_with_invalid_bet_shows_error_and_does_not_seat_player(self):
        game = ge.create_game(self.host, max_players=2, bet=10)
        self.client.login(username="viewguest", password="testpass123")

        response = self.client.post(
            reverse("blackjack:game_join", args=[game.code]), {"bet": "abc"}
        )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(game.participations.filter(player=self.guest).exists())
        rendered = [m.message for m in get_messages(response.wsgi_request)]
        self.assertTrue(any("mise" in m.lower() for m in rendered))

    def test_action_endpoint_rejects_illegal_move_as_json_400(self):
        game = ge.create_game(self.host, max_players=1, bet=10)
        self.client.login(username="viewhost", password="testpass123")

        response = self.client.post(
            reverse("blackjack:game_action", args=[game.code]),
            data=json.dumps({"action": "hit"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.json())

    def test_action_endpoint_requires_login(self):
        game = ge.create_game(self.host, max_players=1, bet=10)
        response = self.client.post(
            reverse("blackjack:game_action", args=[game.code]),
            data=json.dumps({"action": "hit"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 302)

    def test_table_view_404_for_unknown_code(self):
        self.client.login(username="viewhost", password="testpass123")
        response = self.client.get(reverse("blackjack:table", args=["NOTAREAL"]))
        self.assertEqual(response.status_code, 404)
