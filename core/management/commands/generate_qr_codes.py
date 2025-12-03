"""
Management command to generate QR codes for tables.
Usage: python manage.py generate_qr_codes --business=bella-italia-doha
"""

import io
from django.core.management.base import BaseCommand
from django.core.files import File
from django.conf import settings
import qrcode
from core.models import Hotel, Table


class Command(BaseCommand):
    help = 'Generate QR codes for tables in a business'

    def add_arguments(self, parser):
        parser.add_argument(
            '--business',
            type=str,
            help='Business slug (e.g., bella-italia-doha)',
        )
        parser.add_argument(
            '--all',
            action='store_true',
            help='Generate QR codes for all businesses with table management',
        )
        parser.add_argument(
            '--regenerate',
            action='store_true',
            help='Regenerate QR codes even if they already exist',
        )

    def handle(self, *args, **options):
        if options['all']:
            businesses = Hotel.objects.filter(enable_table_management=True)
            self.stdout.write(self.style.SUCCESS(
                f"Generating QR codes for {businesses.count()} businesses with table management..."
            ))
        elif options['business']:
            businesses = Hotel.objects.filter(
                slug=options['business'],
                enable_table_management=True
            )
            if not businesses.exists():
                self.stdout.write(self.style.ERROR(
                    f"Business '{options['business']}' not found or doesn't have table management enabled"
                ))
                return
        else:
            self.stdout.write(self.style.ERROR(
                "Please specify --business=<slug> or --all"
            ))
            return

        regenerate = options['regenerate']
        total_generated = 0

        for business in businesses:
            self.stdout.write(f"\n📍 Processing: {business.name}")
            tables = Table.objects.filter(hotel=business)

            if not tables.exists():
                self.stdout.write(self.style.WARNING(
                    f"  No tables found for {business.name}"
                ))
                continue

            for table in tables:
                # Skip if QR code already exists and not regenerating
                if table.qr_code and not regenerate:
                    self.stdout.write(f"  ⏭️  Table {table.table_number}: QR code already exists (use --regenerate to update)")
                    continue

                # Generate QR code URL
                # In production, use settings.SITE_URL or similar
                base_url = "http://localhost:8000"  # Change this in production
                qr_url = f"{base_url}/menu/{business.slug}/?location={table.table_number}"

                # Create QR code
                qr = qrcode.QRCode(
                    version=1,
                    error_correction=qrcode.constants.ERROR_CORRECT_H,
                    box_size=10,
                    border=4,
                )
                qr.add_data(qr_url)
                qr.make(fit=True)

                # Create image
                img = qr.make_image(fill_color="black", back_color="white")

                # Save to BytesIO
                img_io = io.BytesIO()
                img.save(img_io, format='PNG')
                img_io.seek(0)

                # Save to model
                filename = f"table_{table.table_number}_qr.png"
                table.qr_code.save(filename, File(img_io), save=True)

                total_generated += 1
                self.stdout.write(self.style.SUCCESS(
                    f"  ✅ Table {table.table_number}: QR code generated"
                ))

        self.stdout.write(self.style.SUCCESS(
            f"\n\n✨ Complete! Generated {total_generated} QR codes"
        ))
        self.stdout.write(
            "\n💡 QR codes saved to database. You can download them from the admin panel."
        )
