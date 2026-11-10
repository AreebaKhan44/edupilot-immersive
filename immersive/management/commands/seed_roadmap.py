"""python manage.py seed_roadmap -> markets from the roadmap (s.3 / s.14) and the extra roles (s.6)."""
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand

from immersive.models import MarketAssessment
from immersive.roles import ALL_GROUPS

MARKETS = [
    (1, "Pakistan", "Karachi private schools; selected local and Cambridge pathways; English and Urdu.", "Committed teachers, timetable space, and pilot schools.",
     "Applicable law and institutional policy, board adoption, permission arrangements, and procurement. Do not treat draft proposals as enacted law."),
    (2, "UAE", "Selected international schools; reuse verified packs and add local requirements.", "School partner and workable local support.",
     "Applicable data regime and local education authority; processing and international transfer conditions."),
    (3, "Oman", "Private school or vocational partner; English and Arabic; separate national mapping.", "Named institution and support arrangement.",
     "Child-data provisions and permits for relevant categories of data."),
    (4, "Saudi Arabia", "School group or training partner; Arabic lead and separate national/international packs.", "Local partner and country readiness review.",
     "PDPL, implementing rules, processing arrangements, and overseas transfers."),
    (5, "Qatar", "Selected private schools; school programme and Arabic requirements.", "Paying pilot and sustainable support.",
     "Child-facing notices and protected-data requirements."),
    (6, "Bahrain", "Private schools or training providers through regional partner.", "Demand supports delivery costs.",
     "Current local legal and education review remains required."),
    (7, "Kuwait", "Private school group with local procurement and programme review.", "Local partner and committed customer.",
     "Current local legal and education review remains required."),
]


class Command(BaseCommand):
    help = "Load the roadmap's market list (unscored) and create the role groups"

    def handle(self, *a, **o):
        for g in ALL_GROUPS:
            Group.objects.get_or_create(name=g)
        for seq, country, route, cond, verify in MARKETS:
            MarketAssessment.objects.get_or_create(country=country, defaults={
                "sequence": seq, "route": route, "entry_condition": cond, "readiness": {"verification": verify, "items": {}}})
        self.stdout.write(self.style.SUCCESS("Markets and role groups ready. Scores stay empty until you record evidence."))
