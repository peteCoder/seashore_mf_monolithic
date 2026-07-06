"""
Tests for the loan-list date filter and querystring-preserving pagination.

Regression coverage for a FieldError caused by applying an invalid `__date`
transform to `Loan.application_date`, which is a DateField (not DateTimeField)
and therefore only supports direct `__gte`/`__lte` lookups.
"""
from django.test import TestCase
from django.urls import reverse

from core.tests.factories import make_branch, make_user


class TestLoanListDateFilter(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.branch = make_branch(code='LLF001')
        cls.staff = make_user(cls.branch, role='admin', email='llf_admin@test.com')

    def test_date_filter_does_not_raise_field_error(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse('core:loan_list'), {
            'search': '',
            'status': '',
            'branch': '',
            'loan_product': '',
            'date_from': '2026-07-01',
            'date_to': '2026-07-06',
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['summary']['total_count'], 0)
