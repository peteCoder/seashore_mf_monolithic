"""
Management command: create_betnaija_loan_products
=====================================================

Creates two new loan products for Betnaija (Bet9ja agent) clients, per
explicit user request. Scope was deliberately kept minimal (user's own
choice): these are plain LoanProduct rows using fields that already exist —
no new fields, no new workflow, no changes anywhere else in the app. The
Bet9ja agent-registration and guarantor rules from the policy document are
captured in each product's own `description` field, scoped to these two
products only, and are enforced by staff manually, not by the system.

Products created (financial terms mirror the existing Regular Loan /
Med Monthly Repayment Loan products exactly — no new numbers were invented):

  BETNAIJA-REG  Betnaija Regular Loan (Weekly Repayment)
                loan_type=regular, repayment_frequency=weekly
                same rates/limits as REG-LOAN

  BETNAIJA-MED  Betnaija Medloan (Monthly Repayment)
                loan_type=med, repayment_frequency=monthly
                same rates/limits as MED-MONTHLY-REPAY

Both post to GL 1850 — Loan Receivable - Betnaija Clients (see
init_chart_of_accounts.py), a dedicated receivable account so Betnaija
clients' loans are distinguishable from the general portfolio in reports,
mirroring the existing precedent for MED clients (GL 1840).

Both set required_guarantors=2, matching the policy's "two guarantors"
requirement — enforced today the same way it already is for every other
product (a count check at loan approval), not a new SA/MSA-specific check.

Usage:
    python manage.py create_betnaija_loan_products --dry-run
    python manage.py create_betnaija_loan_products --commit
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction as db_transaction


BETNAIJA_POLICY_NOTE = (
    "For Betnaija (Bet9ja agent) applicants only. Before disbursement, staff must "
    "record and verify: the agent's full name, Bet9ja username, Bet9ja User ID "
    "number, phone number, and business (outlet) location. The applicant must "
    "provide two (2) guarantors, each ideally a verified Super Agent (SA) or "
    "Master Super Agent (MSA) in the Bet9ja hierarchy (other verified personnel "
    "may complete the two if a second SA/MSA isn't available). Guarantor consent "
    "and identification must be documented and attached to the loan file. No "
    "disbursement until registration, guarantor verification, credit assessment, "
    "and management approval are all complete. This is enforced by staff "
    "following the Bet9ja Agent Registration and Loan Disbursement policy; the "
    "system records a standard loan application and 2 guarantors as usual."
)

PRODUCTS = [
    {
        'template_code': 'REG-LOAN',
        'code': 'BETNAIJA-REG',
        'name': 'Betnaija Regular Loan (Weekly Repayment)',
        'loan_type': 'regular',
        'repayment_frequency': 'weekly',
    },
    {
        'template_code': 'MED-MONTHLY-REPAY',
        'code': 'BETNAIJA-MED',
        'name': 'Betnaija Medloan (Monthly Repayment)',
        'loan_type': 'med',
        'repayment_frequency': 'monthly',
    },
]

COPIED_FIELDS = [
    'monthly_interest_rate', 'annual_interest_rate', 'interest_calculation_method',
    'risk_premium_enabled', 'risk_premium_rate', 'risk_premium_calculation',
    'rp_income_enabled', 'rp_income_rate', 'rp_income_calculation',
    'tech_fee_enabled', 'tech_fee_rate', 'tech_fee_calculation',
    'admin_fee_enabled', 'admin_fee_rate',
    'min_principal_amount', 'max_principal_amount',
    'min_duration_months', 'max_duration_months',
    'allow_early_repayment', 'early_repayment_penalty_rate', 'grace_period_days',
    'min_client_age', 'max_client_age', 'requires_business', 'min_membership_months',
    'auto_approve_under_amount', 'requires_director_approval',
    'requires_collateral', 'min_collateral_value_ratio', 'requires_insurance',
]


class Command(BaseCommand):
    help = 'Create the Betnaija Regular Loan and Betnaija Medloan products'

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument('--dry-run', action='store_true', help='Show what will be created without writing to the DB')
        group.add_argument('--commit', action='store_true', help='Apply the change')

    def handle(self, *args, **options):
        from core.models import LoanProduct, ChartOfAccounts

        dry_run = options['dry_run']
        mode = 'DRY RUN' if dry_run else 'COMMIT'
        self.stdout.write(self.style.WARNING(f'\n=== create_betnaija_loan_products [{mode}] ===\n'))

        try:
            gl_account = ChartOfAccounts.objects.get(gl_code='1850')
        except ChartOfAccounts.DoesNotExist:
            raise CommandError('GL 1850 (Loan Receivable - Betnaija Clients) not found — run init_chart_of_accounts first.')

        for spec in PRODUCTS:
            if LoanProduct.objects.filter(code=spec['code']).exists():
                self.stdout.write(f"  [*] {spec['code']} already exists — skipping")
                continue

            template = LoanProduct.objects.get(code=spec['template_code'])
            field_values = {f: getattr(template, f) for f in COPIED_FIELDS}

            self.stdout.write(f"\n{spec['code']} - {spec['name']}")
            self.stdout.write(f"  loan_type: {spec['loan_type']}  repayment_frequency: {spec['repayment_frequency']}")
            self.stdout.write(f"  gl_code: 1850  required_guarantors: 2")
            self.stdout.write(f"  financial terms copied from: {spec['template_code']}")
            self.stdout.write(f"    monthly_interest_rate={field_values['monthly_interest_rate']}  "
                               f"min={field_values['min_principal_amount']}  max={field_values['max_principal_amount']}")

            if dry_run:
                continue

            LoanProduct.objects.create(
                code=spec['code'],
                name=spec['name'],
                description=BETNAIJA_POLICY_NOTE,
                loan_type=spec['loan_type'],
                gl_code=gl_account.gl_code,
                repayment_frequency=spec['repayment_frequency'],
                required_guarantors=2,
                is_active=True,
                **field_values,
            )
            self.stdout.write(self.style.SUCCESS(f"  -> created {spec['code']}"))

        if dry_run:
            self.stdout.write(self.style.SUCCESS('\nDry run complete - no changes written. Re-run with --commit to apply.\n'))
            return

        self.stdout.write(self.style.SUCCESS('\nDone.\n'))
        self.stdout.write('FINAL STATE')
        for spec in PRODUCTS:
            p = LoanProduct.objects.get(code=spec['code'])
            self.stdout.write(
                f"  {p.code}: {p.name} | type={p.loan_type} | freq={p.repayment_frequency} | "
                f"guarantors={p.required_guarantors} | gl={p.gl_code} | active={p.is_active}"
            )
