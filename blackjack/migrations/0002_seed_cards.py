from django.db import migrations


def seed_cards(apps, schema_editor):
    Card = apps.get_model("blackjack", "Card")
    suits = ["H", "D", "C", "S"]
    ranks = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"]
    Card.objects.bulk_create(
        [Card(suit=suit, rank=rank) for suit in suits for rank in ranks],
        ignore_conflicts=True,
    )


def unseed_cards(apps, schema_editor):
    Card = apps.get_model("blackjack", "Card")
    Card.objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [
        ("blackjack", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed_cards, unseed_cards),
    ]
