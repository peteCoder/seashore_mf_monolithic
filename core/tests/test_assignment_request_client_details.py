"""
Tests for AssignmentRequest.get_affected_clients() and its use on the
assignment review/detail pages.

Previously those pages showed only a bare count (`affected_count`) plus a
collapsed raw JSON blob of client UUIDs — a manager reviewing a bulk client
transfer (e.g. staff_portfolio_transfer) had no way to see WHO was actually
being moved without decoding UUIDs by hand. This adds a proper, paginated,
human-readable table of the actual Client records on both pages.
"""
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from core.models import AssignmentRequest, Client
from core.tests.factories import make_branch, make_user, make_client


def make_request(requested_by, **kwargs):
    defaults = dict(
        assignment_type='bulk_clients_to_staff',
        assignment_data={},
        description='test request',
        requested_by=requested_by,
    )
    defaults.update(kwargs)
    return AssignmentRequest.objects.create(**defaults)


class GetAffectedClientsResolutionTests(TestCase):
    """Unit tests for the model method across every assignment_type shape."""

    @classmethod
    def setUpTestData(cls):
        cls.branch = make_branch(code='ARQ001')
        cls.staff_a = make_user(cls.branch, role='staff', email='arq_a@test.com')
        cls.staff_b = make_user(cls.branch, role='staff', email='arq_b@test.com')
        cls.c1 = make_client(cls.branch, cls.staff_a, email='arq_c1@test.com')
        cls.c2 = make_client(cls.branch, cls.staff_a, email='arq_c2@test.com')
        cls.c3 = make_client(cls.branch, cls.staff_a, email='arq_c3@test.com')

    def test_single_client_id_resolves_to_one_client(self):
        req = make_request(
            self.staff_a,
            assignment_type='client_to_staff',
            assignment_data={'client_id': str(self.c1.id), 'staff_id': str(self.staff_b.id)},
        )
        self.assertEqual(list(req.get_affected_clients()), [self.c1])

    def test_bulk_client_ids_resolve_to_all_clients(self):
        req = make_request(
            self.staff_a,
            assignment_type='bulk_clients_to_staff',
            assignment_data={'client_ids': [str(self.c1.id), str(self.c2.id)], 'staff_id': str(self.staff_b.id)},
        )
        self.assertEqual(set(req.get_affected_clients()), {self.c1, self.c2})

    def test_unassign_type_resolves_single_client(self):
        req = make_request(
            self.staff_a,
            assignment_type='unassign_client_from_staff',
            assignment_data={'client_id': str(self.c3.id)},
        )
        self.assertEqual(list(req.get_affected_clients()), [self.c3])

    def test_group_to_branch_resolves_group_members_not_client_ids(self):
        from core.tests.factories import make_branch as mb
        other_branch = mb(name='ARQ001 Other', code='ARQ001B')
        from core.models import ClientGroup
        group = ClientGroup.objects.create(name='Test Group', branch=self.branch, loan_officer=self.staff_a)
        self.c1.group = group
        self.c1.save(update_fields=['group'])
        self.c2.group = group
        self.c2.save(update_fields=['group'])

        req = make_request(
            self.staff_a,
            assignment_type='group_to_branch',
            assignment_data={'group_id': str(group.id), 'branch_id': str(other_branch.id)},
            target_group=group,
        )
        self.assertEqual(set(req.get_affected_clients()), {self.c1, self.c2})

    def test_no_client_data_and_no_group_returns_empty(self):
        req = make_request(self.staff_a, assignment_type='bulk_clients_to_staff', assignment_data={})
        self.assertEqual(list(req.get_affected_clients()), [])

    def test_unknown_or_stale_client_ids_do_not_error(self):
        import uuid
        req = make_request(
            self.staff_a,
            assignment_type='bulk_clients_to_staff',
            assignment_data={'client_ids': [str(uuid.uuid4())]},
        )
        self.assertEqual(list(req.get_affected_clients()), [])


class AssignmentReviewPageShowsClientDetailsTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.branch = make_branch(code='ARQ002')
        cls.manager = make_user(cls.branch, role='manager', email='arq2_mgr@test.com')
        cls.staff_a = make_user(cls.branch, role='staff', email='arq2_a@test.com')
        cls.staff_b = make_user(cls.branch, role='staff', email='arq2_b@test.com')
        cls.clients = [
            make_client(cls.branch, cls.staff_a, email=f'arq2_c{i}@test.com')
            for i in range(3)
        ]
        cls.req = AssignmentRequest.objects.create(
            assignment_type='bulk_clients_to_staff',
            assignment_data={'client_ids': [str(c.id) for c in cls.clients], 'staff_id': str(cls.staff_b.id)},
            description=f'Transfer {len(cls.clients)} client(s) from Staff A to Staff B',
            requested_by=cls.staff_a,
            branch=cls.branch,
            affected_count=len(cls.clients),
        )

    def setUp(self):
        self.client.force_login(self.manager)

    def test_detail_page_shows_client_names_not_only_ids(self):
        response = self.client.get(reverse('core:assignment_detail', args=[self.req.id]))
        for c in self.clients:
            self.assertContains(response, c.get_full_name())
            self.assertContains(response, c.client_id)

    def test_review_page_shows_client_names_before_approving(self):
        response = self.client.get(reverse('core:assignment_approve', args=[self.req.id]))
        for c in self.clients:
            self.assertContains(response, c.get_full_name())

    def test_detail_page_context_has_paginated_affected_clients(self):
        response = self.client.get(reverse('core:assignment_detail', args=[self.req.id]))
        page = response.context['affected_clients']
        self.assertEqual(page.paginator.count, 3)

    def test_large_bulk_transfer_is_paginated_not_truncated(self):
        many_clients = [
            make_client(self.branch, self.staff_a, email=f'arq2_bulk{i}@test.com')
            for i in range(60)
        ]
        req = AssignmentRequest.objects.create(
            assignment_type='bulk_clients_to_staff',
            assignment_data={'client_ids': [str(c.id) for c in many_clients], 'staff_id': str(self.staff_b.id)},
            description='Transfer 60 clients',
            requested_by=self.staff_a,
            branch=self.branch,
            affected_count=60,
        )
        response = self.client.get(reverse('core:assignment_detail', args=[req.id]))
        page = response.context['affected_clients']
        self.assertEqual(page.paginator.count, 60)
        self.assertEqual(len(page.object_list), 50)  # page size

        response2 = self.client.get(reverse('core:assignment_detail', args=[req.id]), {'clients_page': 2})
        self.assertEqual(len(response2.context['affected_clients'].object_list), 10)

    def test_client_name_links_to_client_detail_page(self):
        response = self.client.get(reverse('core:assignment_detail', args=[self.req.id]))
        expected_url = reverse('core:client_detail', args=[self.clients[0].id])
        self.assertContains(response, expected_url)
