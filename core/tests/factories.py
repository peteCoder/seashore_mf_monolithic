"""
Test Factories
==============

Lightweight helper functions to create valid model instances for testing.
No third-party library required — just plain Django ORM.
"""

import random
from datetime import date
from decimal import Decimal

from core.models import (
    User, Branch, Client, LoanProduct, SavingsProduct,
    ChartOfAccounts,
)


def make_branch(name='Test Branch', code='TST001'):
    return Branch.objects.create(name=name, code=code, is_active=True)


def make_user(branch, role='staff', email=None, **kwargs):
    if email is None:
        email = f'{role}_{random.randint(10000, 99999)}@seashore.test'
    user = User.objects.create_user(
        email=email,
        password='TestPass123!',
        first_name='Test',
        last_name=role.title(),
        user_role=role,
        branch=branch,
        is_approved=True,
        is_active=True,
        **kwargs,
    )
    return user


def make_client(branch, assigned_staff, email=None, **kwargs):
    if email is None:
        email = f'client{random.randint(10000, 99999)}@seashore.test'
    return Client.objects.create(
        first_name='Test',
        last_name='Client',
        email=email,
        phone='+2348012345678',
        branch=branch,
        assigned_staff=assigned_staff,
        address='123 Test Street',
        city='Lagos',
        state='Lagos',
        date_of_birth=date(1990, 1, 1),
        gender='male',
        id_type='national_id',
        id_number='NIN12345678',
        approval_status='approved',
        is_active=True,
        **kwargs,
    )


def make_loan_product(branch=None, **kwargs):
    defaults = dict(
        name='Standard Business Loan',
        code='SBL001',
        loan_type='business',
        monthly_interest_rate=Decimal('0.03'),
        interest_calculation_method='flat',
        min_principal_amount=Decimal('10000.00'),
        max_principal_amount=Decimal('5000000.00'),
        min_duration_months=1,
        max_duration_months=24,
        is_active=True,
    )
    defaults.update(kwargs)
    return LoanProduct.objects.create(**defaults)


def make_savings_product(**kwargs):
    defaults = dict(
        name='Regular Savings',
        code='RS001',
        product_type='regular',
        interest_rate_annual=Decimal('4.00'),
        is_active=True,
    )
    defaults.update(kwargs)
    return SavingsProduct.objects.create(**defaults)


def make_gl_account(gl_code='1010', name='Cash In Hand', account_type=None, **kwargs):
    from core.models import AccountType
    if account_type is None:
        acc_type = AccountType.objects.filter(name='asset').first()
    else:
        acc_type = account_type
    return ChartOfAccounts.objects.get_or_create(
        gl_code=gl_code,
        defaults=dict(
            account_name=name,
            account_type=acc_type,
            is_active=True,
            **kwargs,
        ),
    )[0]
