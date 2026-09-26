import sys

from django.core.management.base import BaseCommand

from apps.payments.client import PayVesselClient, PayVesselError


class Command(BaseCommand):
    help = "Test the PayVessel sandbox API with a BVN or NIN number."

    def add_arguments(self, parser):
        parser.add_argument("id_type", choices=["bvn", "nin"], help="Which verification endpoint to test.")
        parser.add_argument("id_number", help="The BVN or NIN number to verify.")
        parser.add_argument("--first-name", default="Test")
        parser.add_argument("--last-name", default="User")
        parser.add_argument("--gender", default="MALE")
        parser.add_argument("--birthday", default="1990-01-01")
        parser.add_argument("--phone", default="08012345678")

    def handle(self, *args, **options):
        client = PayVesselClient()
        common = dict(
            first_name=options["first_name"],
            last_name=options["last_name"],
            middle_name="",
            gender=options["gender"],
            birthday=options["birthday"],
            phone_number=options["phone"],
        )

        self.stdout.write(f"Base URL: {client.base_url}")
        self.stdout.write(f"Testing {options['id_type'].upper()} verification for: {options['id_number']}")
        self.stdout.write("-" * 60)

        try:
            if options["id_type"] == "nin":
                data = client.verify_nin(nin=options["id_number"], **common)
            else:
                data = client.verify_bvn(bvn=options["id_number"], **common)
        except PayVesselError as exc:
            self.stderr.write(self.style.ERROR(f"PayVessel error: {exc}"))
            sys.exit(1)

        import json
        self.stdout.write(json.dumps(data, indent=2, default=str))
