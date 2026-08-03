from django.contrib import admin

from .models import Card, Deck, Game, MoveLog, Participation, Profile


@admin.register(Card)
class CardAdmin(admin.ModelAdmin):
    list_display = ("code", "suit", "rank", "blackjack_value")
    list_filter = ("suit", "rank")


class ParticipationInline(admin.TabularInline):
    model = Participation
    extra = 0
    readonly_fields = ("joined_at",)


@admin.register(Game)
class GameAdmin(admin.ModelAdmin):
    list_display = ("code", "host", "status", "current_turn_seat", "created_at")
    list_filter = ("status",)
    search_fields = ("code", "host__username")
    inlines = [ParticipationInline]


@admin.register(Participation)
class ParticipationAdmin(admin.ModelAdmin):
    list_display = ("game", "player", "seat", "status", "result", "bet")
    list_filter = ("status", "result")


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "chips", "games_played", "games_won", "games_lost", "win_rate")


@admin.register(MoveLog)
class MoveLogAdmin(admin.ModelAdmin):
    list_display = ("game", "player", "action", "card", "hand_total", "created_at")
    list_filter = ("action",)
    date_hierarchy = "created_at"


@admin.register(Deck)
class DeckAdmin(admin.ModelAdmin):
    list_display = ("game",)
