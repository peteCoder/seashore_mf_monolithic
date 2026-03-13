"""
API Views
=========

DRF ViewSets and APIViews for the Seashore Microfinance REST API.

All endpoints require authentication (Token or Session).
Role-based filtering is applied: managers see only their branch.
"""

from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db.models import Q, Sum

from drf_spectacular.utils import extend_schema, OpenApiParameter
from rest_framework import viewsets, status
from rest_framework.authentication import TokenAuthentication, SessionAuthentication
from rest_framework.authtoken.models import Token
from rest_framework.authtoken.serializers import AuthTokenSerializer
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.models import Client, Loan, SavingsAccount, Branch
from core.permissions import PermissionChecker
from .serializers import (
    ClientListSerializer, ClientDetailSerializer,
    LoanListSerializer, LoanDetailSerializer,
    SavingsAccountListSerializer, SavingsAccountDetailSerializer,
    PortfolioReportSerializer,
)

User = get_user_model()


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _branch_filter(queryset, request, field='branch'):
    """Limit queryset to the user's branch for managers; directors/admins see all."""
    checker = PermissionChecker(request.user)
    if not checker.can_view_all_branches():
        kwargs = {field: request.user.branch}
        queryset = queryset.filter(**kwargs)
    return queryset


# ─────────────────────────────────────────────────────────────────────────────
# Obtain Auth Token  (POST /api/auth/token/)
# ─────────────────────────────────────────────────────────────────────────────

@extend_schema(tags=['auth'], summary='Obtain authentication token')
class ObtainTokenView(APIView):
    """
    Exchange email + password for a DRF auth token.

    POST body: ``{"username": "<email>", "password": "<password>"}``
    Returns:   ``{"token": "<token>", "user_id": "...", "email": "..."}``
    """
    authentication_classes = []
    permission_classes     = []
    serializer_class       = AuthTokenSerializer

    def post(self, request, *args, **kwargs):
        serializer = AuthTokenSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        user  = serializer.validated_data['user']
        token, _ = Token.objects.get_or_create(user=user)
        return Response({
            'token':   token.key,
            'user_id': str(user.pk),
            'email':   user.email,
            'role':    user.user_role,
        })


# ─────────────────────────────────────────────────────────────────────────────
# Client ViewSet
# ─────────────────────────────────────────────────────────────────────────────

@extend_schema(tags=['clients'])
class ClientViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Read-only client endpoints.

    list   → GET /api/clients/
    detail → GET /api/clients/{id}/
    """
    authentication_classes = [TokenAuthentication, SessionAuthentication]
    permission_classes     = [IsAuthenticated]
    queryset               = Client.objects.all()

    def get_queryset(self):
        qs = Client.objects.select_related('branch', 'assigned_staff').order_by('-created_at')
        qs = _branch_filter(qs, self.request)

        # Optional filters from query params
        search = self.request.query_params.get('search', '').strip()
        if search:
            qs = qs.filter(
                Q(first_name__icontains=search) |
                Q(last_name__icontains=search) |
                Q(email__icontains=search) |
                Q(phone__icontains=search) |
                Q(client_id__icontains=search)
            )

        approval = self.request.query_params.get('approval_status')
        if approval:
            qs = qs.filter(approval_status=approval)

        level = self.request.query_params.get('level')
        if level:
            qs = qs.filter(level=level)

        return qs

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return ClientDetailSerializer
        return ClientListSerializer

    @extend_schema(
        parameters=[
            OpenApiParameter('search',          str, description='Name, email, phone or client ID'),
            OpenApiParameter('approval_status', str, description='pending / approved / rejected'),
            OpenApiParameter('level',           str, description='bronze / silver / gold / platinum'),
        ],
        summary='List clients',
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(summary='Retrieve a client')
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)


# ─────────────────────────────────────────────────────────────────────────────
# Loan ViewSet
# ─────────────────────────────────────────────────────────────────────────────

@extend_schema(tags=['loans'])
class LoanViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Read-only loan endpoints.

    list   → GET /api/loans/
    detail → GET /api/loans/{id}/
    """
    authentication_classes = [TokenAuthentication, SessionAuthentication]
    permission_classes     = [IsAuthenticated]
    queryset               = Loan.objects.all()

    def get_queryset(self):
        qs = (
            Loan.objects
            .select_related('client', 'loan_product', 'branch', 'created_by', 'approved_by')
            .order_by('-created_at')
        )
        qs = _branch_filter(qs, self.request)

        status_param = self.request.query_params.get('status')
        if status_param:
            qs = qs.filter(status=status_param)

        client_id = self.request.query_params.get('client')
        if client_id:
            qs = qs.filter(client_id=client_id)

        return qs

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return LoanDetailSerializer
        return LoanListSerializer

    @extend_schema(
        parameters=[
            OpenApiParameter('status',    str, description='pending_fees / active / completed / overdue / …'),
            OpenApiParameter('client',    str, description='Client UUID'),
        ],
        summary='List loans',
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(summary='Retrieve a loan')
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)


# ─────────────────────────────────────────────────────────────────────────────
# SavingsAccount ViewSet
# ─────────────────────────────────────────────────────────────────────────────

@extend_schema(tags=['savings'])
class SavingsAccountViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Read-only savings account endpoints.

    list   → GET /api/savings/
    detail → GET /api/savings/{id}/
    """
    authentication_classes = [TokenAuthentication, SessionAuthentication]
    permission_classes     = [IsAuthenticated]
    queryset               = SavingsAccount.objects.all()

    def get_queryset(self):
        qs = (
            SavingsAccount.objects
            .select_related('client', 'savings_product', 'branch')
            .order_by('-created_at')
        )
        qs = _branch_filter(qs, self.request)

        status_param = self.request.query_params.get('status')
        if status_param:
            qs = qs.filter(status=status_param)

        client_id = self.request.query_params.get('client')
        if client_id:
            qs = qs.filter(client_id=client_id)

        return qs

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return SavingsAccountDetailSerializer
        return SavingsAccountListSerializer

    @extend_schema(
        parameters=[
            OpenApiParameter('status', str, description='active / dormant / closed'),
            OpenApiParameter('client', str, description='Client UUID'),
        ],
        summary='List savings accounts',
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(summary='Retrieve a savings account')
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)


# ─────────────────────────────────────────────────────────────────────────────
# Portfolio Report Endpoint
# ─────────────────────────────────────────────────────────────────────────────

@extend_schema(
    tags=['reports'],
    summary='Portfolio at a glance',
    description=(
        'Returns key portfolio metrics: total active loans, outstanding balance, '
        'PAR buckets (1/30/60/90 days), total savings, and active client count. '
        'Director/Admin see all branches; Managers see their branch only.'
    ),
    parameters=[
        OpenApiParameter('branch', str, description='Branch UUID (director/admin only)'),
    ],
    responses={200: PortfolioReportSerializer},
)
class PortfolioReportView(APIView):
    authentication_classes = [TokenAuthentication, SessionAuthentication]
    permission_classes     = [IsAuthenticated]

    def get(self, request):
        checker = PermissionChecker(request.user)
        today   = date.today()

        # Base loan queryset
        loans_qs = Loan.objects.filter(status__in=['active', 'overdue'])
        if not checker.can_view_all_branches():
            loans_qs = loans_qs.filter(branch=request.user.branch)
        elif request.query_params.get('branch'):
            loans_qs = loans_qs.filter(branch_id=request.query_params['branch'])

        # Aggregate
        agg = loans_qs.aggregate(
            total=Sum('outstanding_balance'),
            par1=Sum('outstanding_balance', filter=Q(next_repayment_date__lt=today)),
            par30=Sum('outstanding_balance', filter=Q(
                next_repayment_date__lt=today,
                next_repayment_date__gte=today.__class__.fromordinal(today.toordinal() - 30)
            )),
        )

        # PAR buckets via days-overdue annotation is complex; use simpler query
        def _par(days):
            from datetime import timedelta
            cutoff = today - timedelta(days=days)
            return loans_qs.filter(
                status='overdue',
                next_repayment_date__lte=cutoff,
            ).aggregate(s=Sum('outstanding_balance'))['s'] or Decimal('0')

        total_port = loans_qs.aggregate(s=Sum('outstanding_balance'))['s'] or Decimal('0')
        par1_amt   = _par(1)
        par30_amt  = _par(30)
        par60_amt  = _par(60)
        par90_amt  = _par(90)

        def _pct(amt):
            if total_port == 0:
                return Decimal('0')
            return round(amt / total_port * 100, 2)

        # Savings
        savings_qs = SavingsAccount.objects.filter(status='active')
        if not checker.can_view_all_branches():
            savings_qs = savings_qs.filter(branch=request.user.branch)
        total_savings = savings_qs.aggregate(s=Sum('balance'))['s'] or Decimal('0')

        # Clients
        clients_qs = Client.objects.filter(approval_status='approved', is_active=True)
        if not checker.can_view_all_branches():
            clients_qs = clients_qs.filter(branch=request.user.branch)

        data = {
            'total_loans_active':    loans_qs.count(),
            'total_portfolio_value': total_port,
            'par_1_amount':          par1_amt,
            'par_30_amount':         par30_amt,
            'par_60_amount':         par60_amt,
            'par_90_amount':         par90_amt,
            'par_1_pct':             _pct(par1_amt),
            'par_30_pct':            _pct(par30_amt),
            'par_60_pct':            _pct(par60_amt),
            'par_90_pct':            _pct(par90_amt),
            'total_savings_balance': total_savings,
            'total_clients':         clients_qs.count(),
            'report_date':           today,
        }
        serializer = PortfolioReportSerializer(data)
        return Response(serializer.data)
