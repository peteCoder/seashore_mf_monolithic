"""
Management command: migrate_cloudinary_assets
=============================================

Migrates Cloudinary assets by reading public_ids directly from the database
(bypasses the old account's Admin API which is disabled) then fetching each
asset from the old CDN and re-uploading to the new account.

public_ids are preserved exactly, so no database changes are needed after migration.

Usage
-----
    # Dry run — shows every public_id found, no uploads
    python manage.py migrate_cloudinary_assets --dry-run \\
        --old-cloud daf9tr3lf \\
        --new-cloud dhv0ynkbz \\
        --new-key 881112252394229 \\
        --new-secret IM22O3IonQ8WnTvaRXNTq6BVzPA

    # Commit
    python manage.py migrate_cloudinary_assets --commit \\
        --old-cloud daf9tr3lf \\
        --new-cloud dhv0ynkbz \\
        --new-key 881112252394229 \\
        --new-secret IM22O3IonQ8WnTvaRXNTq6BVzPA

    # Resume — skips assets already in new account
    python manage.py migrate_cloudinary_assets --commit --skip-existing \\
        --old-cloud daf9tr3lf \\
        --new-cloud dhv0ynkbz \\
        --new-key 881112252394229 \\
        --new-secret IM22O3IonQ8WnTvaRXNTq6BVzPA
"""

import requests
import cloudinary
import cloudinary.api
import cloudinary.uploader
import cloudinary.exceptions

from django.core.management.base import BaseCommand
from django.apps import apps


# All (model_label, field_name) pairs with a CloudinaryField
CLOUDINARY_FIELDS = [
    ('core.User',        'profile_picture'),
    ('core.User',        'id_card_front'),
    ('core.User',        'id_card_back'),
    ('core.User',        'cv_document'),
    ('core.Client',      'profile_picture'),
    ('core.Client',      'id_card_front'),
    ('core.Client',      'id_card_back'),
    ('core.Client',      'signature'),
    ('core.Loan',        'client_signature'),
    ('core.Loan',        'union_leader_signature'),
    ('core.Loan',        'union_secretary_signature'),
    ('core.Loan',        'union_member1_signature'),
    ('core.Loan',        'union_member2_signature'),
    ('core.Loan',        'union_member3_signature'),
    ('core.Loan',        'credit_officer_signature'),
    ('core.Guarantor',   'id_card_front'),
    ('core.Guarantor',   'id_card_back'),
    ('core.Guarantor',   'signature'),
    ('core.Collateral',  'document'),
    ('core.Collateral',  'photo'),
]


def _cdn_url(cloud_name, public_id):
    """Construct a plain CDN URL for an asset without using the Admin API."""
    return f'https://res.cloudinary.com/{cloud_name}/image/upload/{public_id}'


class Command(BaseCommand):
    help = (
        'Migrate Cloudinary assets using DB public_ids (works even when '
        'old account Admin API is disabled).'
    )

    def add_arguments(self, parser):
        mode = parser.add_mutually_exclusive_group(required=True)
        mode.add_argument('--dry-run', action='store_true',
                          help='Show what would be migrated without uploading')
        mode.add_argument('--commit', action='store_true',
                          help='Perform the migration')

        parser.add_argument('--old-cloud',  required=True,
                            help='Old cloud_name (e.g. daf9tr3lf)')
        parser.add_argument('--new-cloud',  required=True,
                            help='New cloud_name')
        parser.add_argument('--new-key',    required=True,
                            help='New account API key')
        parser.add_argument('--new-secret', required=True,
                            help='New account API secret')
        parser.add_argument('--skip-existing', action='store_true', default=True,
                            help='Skip assets already in new account (default: on, safe to re-run)')

    def handle(self, *args, **options):
        dry_run       = options['dry_run']
        skip_existing = options['skip_existing']
        old_cloud     = options['old_cloud']
        new_config    = {
            'cloud_name': options['new_cloud'],
            'api_key':    options['new_key'],
            'api_secret': options['new_secret'],
        }
        mode = 'DRY RUN' if dry_run else 'COMMIT'

        self.stdout.write(self.style.WARNING(
            f'\n=== migrate_cloudinary_assets [{mode}] ===\n'
            f'  FROM (CDN only): {old_cloud}\n'
            f'  TO             : {new_config["cloud_name"]}\n'
        ))

        # ── Collect all unique public_ids from the database ───────────────
        self.stdout.write('Scanning database for Cloudinary public_ids...\n')
        seen       = set()   # deduplicate across rows/models
        all_assets = []      # list of (public_id,)

        for model_label, field_name in CLOUDINARY_FIELDS:
            try:
                Model = apps.get_model(model_label)
            except LookupError:
                self.stdout.write(self.style.WARNING(
                    f'  [SKIP] Model {model_label} not found'
                ))
                continue

            qs = Model.objects.exclude(
                **{f'{field_name}__isnull': True}
            ).exclude(
                **{f'{field_name}': ''}
            ).values_list(field_name, flat=True)

            count = 0
            for raw_value in qs:
                public_id = str(raw_value).strip()
                if not public_id or public_id in seen:
                    continue
                seen.add(public_id)
                all_assets.append(public_id)
                count += 1

            if count:
                self.stdout.write(f'  {model_label}.{field_name}: {count} asset(s)')

        self.stdout.write(f'\nTotal unique assets found in DB: {len(all_assets)}\n')

        if not all_assets:
            self.stdout.write(self.style.WARNING('No assets found. Nothing to migrate.'))
            return

        if dry_run:
            self.stdout.write('\nAssets that would be migrated:')
            for pid in all_assets:
                url = _cdn_url(old_cloud, pid)
                self.stdout.write(f'  {pid}\n    URL: {url}')
            self.stdout.write(self.style.SUCCESS(
                f'\nDry run complete — {len(all_assets)} asset(s) found.\n'
                'Re-run with --commit to migrate them.\n'
            ))
            return

        # ── Migrate each asset ────────────────────────────────────────────
        migrated = 0
        skipped  = 0
        cdn_fail = 0
        errors   = 0

        for public_id in all_assets:
            cdn_url = _cdn_url(old_cloud, public_id)

            # ── Skip if already in new account ────────────────────────────
            if skip_existing:
                try:
                    cloudinary.api.resource(public_id, resource_type='image', **new_config)
                    self.stdout.write(f'  [SKIP] Already in new account: {public_id}')
                    skipped += 1
                    continue
                except cloudinary.exceptions.NotFound:
                    pass
                except Exception:
                    pass

            # ── Check old CDN is still serving the file ───────────────────
            try:
                resp = requests.head(cdn_url, timeout=10, allow_redirects=True)
                if resp.status_code != 200:
                    self.stdout.write(self.style.WARNING(
                        f'  [CDN {resp.status_code}] Not accessible: {public_id}'
                    ))
                    cdn_fail += 1
                    continue
            except requests.RequestException as e:
                self.stdout.write(self.style.WARNING(
                    f'  [CDN ERR] {public_id}: {e}'
                ))
                cdn_fail += 1
                continue

            # ── Upload to new account from old CDN URL ────────────────────
            try:
                cloudinary.uploader.upload(
                    cdn_url,
                    public_id=public_id,
                    resource_type='image',
                    overwrite=True,
                    **new_config,
                )
                self.stdout.write(self.style.SUCCESS(f'  [OK] {public_id}'))
                migrated += 1
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'  [ERR] {public_id}: {e}'))
                errors += 1

        # ── Summary ───────────────────────────────────────────────────────
        self.stdout.write(f'\n{"=" * 60}')
        self.stdout.write(self.style.SUCCESS(f'Migrated      : {migrated}'))
        self.stdout.write(f'Skipped       : {skipped}')
        self.stdout.write(self.style.WARNING(f'CDN not served: {cdn_fail}'))
        if errors:
            self.stdout.write(self.style.ERROR(f'Errors        : {errors}'))
        else:
            self.stdout.write(self.style.SUCCESS('Errors        : 0'))

        self.stdout.write('')
        if cdn_fail:
            self.stdout.write(self.style.WARNING(
                f'{cdn_fail} asset(s) could not be fetched from the old CDN — '
                'those images were already inaccessible before migration.\n'
            ))

        if migrated > 0 and errors == 0:
            self.stdout.write(self.style.SUCCESS(
                'Migration complete!\n'
                'Update CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, and\n'
                'CLOUDINARY_API_SECRET in your .env to the new account values,\n'
                'then restart the server. All migrated images will display immediately.\n'
            ))
        elif errors > 0:
            self.stdout.write(self.style.WARNING(
                f'{errors} upload(s) failed. Re-run with --commit --skip-existing '
                'to retry only those.\n'
            ))
