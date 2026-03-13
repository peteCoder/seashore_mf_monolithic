"""
API Serializers
===============

DRF serializers for the Seashore Microfinance REST API.
Covers: Client, Loan, SavingsAccount, Branch, User (read-only profile).
"""

from decimal import Decimal

from django.contrib.auth import get_user_model
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from core.models import (
    Branch, Client, Loan, LoanProduct,
    SavingsAccount, SavingsProduct,
    JournalEntry, JournalEntryLine,
    ChartOfAccounts,
)

User = get_user_model()


# ─────────────────────────────────────────────────────────────────────────────
# Shared / nested
# ─────────────────────────────────────────────────────────────────────────────

class BranchSerializer(serializers.ModelSerializer):
    class Meta:
        model = Branch
        fields = ['id', 'name', 'code', 'is_active']


class UserBriefSerializer(serializers.ModelSerializer):
    full_name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ['id', 'email', 'full_name', 'user_role']

    @extend_schema_field(serializers.CharField())
    def get_full_name(self, obj):
        return obj.get_full_name()


# ─────────────────────────────────────────────────────────────────────────────
# Client
# ─────────────────────────────────────────────────────────────────────────────

class ClientListSerializer(serializers.ModelSerializer):
    branch_name = serializers.CharField(source='branch.name', read_only=True)
    full_name   = serializers.SerializerMethodField()

    class Meta:
        model = Client
        fields = [
            'id', 'client_id', 'full_name',
            'phone', 'email',
            'branch', 'branch_name',
            'approval_status', 'level', 'is_active',
            'created_at',
        ]

    @extend_schema_field(serializers.CharField())
    def get_full_name(self, obj):
        return obj.get_full_name()


class ClientDetailSerializer(serializers.ModelSerializer):
    branch          = BranchSerializer(read_only=True)
    assigned_staff  = UserBriefSerializer(read_only=True)
    full_name       = serializers.SerializerMethodField()

    class Meta:
        model = Client
        fields = [
            'id', 'client_id', 'full_name',
            'first_name', 'last_name',
            'phone', 'email', 'date_of_birth', 'gender',
            'address', 'city', 'state',
            'id_type', 'id_number',
            'branch', 'assigned_staff',
            'approval_status', 'level', 'is_active',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'client_id', 'created_at', 'updated_at']

    @extend_schema_field(serializers.CharField())
    def get_full_name(self, obj):
        return obj.get_full_name()


# ─────────────────────────────────────────────────────────────────────────────
# Loan Product
# ─────────────────────────────────────────────────────────────────────────────

class LoanProductSerializer(serializers.ModelSerializer):
    class Meta:
        model = LoanProduct
        fields = [
            'id', 'name', 'code', 'loan_type',
            'monthly_interest_rate', 'interest_calculation_method',
            'min_principal_amount', 'max_principal_amount',
            'min_duration_months', 'max_duration_months',
            'is_active',
        ]


# ─────────────────────────────────────────────────────────────────────────────
# Loan
# ─────────────────────────────────────────────────────────────────────────────

class LoanListSerializer(serializers.ModelSerializer):
    client_name  = serializers.SerializerMethodField()
    product_name = serializers.CharField(source='loan_product.name', read_only=True)
    branch_name  = serializers.CharField(source='branch.name', read_only=True)

    class Meta:
        model = Loan
        fields = [
            'id', 'loan_number',
            'client', 'client_name',
            'loan_product', 'product_name',
            'branch', 'branch_name',
            'principal_amount', 'outstanding_balance',
            'status', 'disbursement_date', 'next_repayment_date',
            'created_at',
        ]

    @extend_schema_field(serializers.CharField())
    def get_client_name(self, obj):
        return obj.client.get_full_name() if obj.client else ''


class LoanDetailSerializer(serializers.ModelSerializer):
    client       = ClientListSerializer(read_only=True)
    loan_product = LoanProductSerializer(read_only=True)
    branch       = BranchSerializer(read_only=True)
    created_by   = UserBriefSerializer(read_only=True)
    approved_by  = UserBriefSerializer(read_only=True)

    class Meta:
        model = Loan
        fields = [
            'id', 'loan_number',
            'client', 'loan_product', 'branch',
            'principal_amount', 'duration_months',
            'monthly_interest_rate', 'interest_type',
            'total_interest', 'total_repayment', 'installment_amount',
            'outstanding_balance', 'amount_paid', 'accrued_interest_balance',
            'status', 'purpose',
            'application_date', 'approval_date',
            'disbursement_date', 'first_repayment_date',
            'next_repayment_date', 'final_repayment_date',
            'disbursement_method',
            'created_by', 'approved_by',
            'created_at', 'updated_at',
        ]
        read_only_fields = fields


# ─────────────────────────────────────────────────────────────────────────────
# Savings Product
# ─────────────────────────────────────────────────────────────────────────────

class SavingsProductSerializer(serializers.ModelSerializer):
    class Meta:
        model = SavingsProduct
        fields = [
            'id', 'name', 'code', 'product_type',
            'interest_rate_annual', 'interest_calculation_method',
            'is_active',
        ]


# ─────────────────────────────────────────────────────────────────────────────
# Savings Account
# ─────────────────────────────────────────────────────────────────────────────

class SavingsAccountListSerializer(serializers.ModelSerializer):
    client_name  = serializers.SerializerMethodField()
    product_name = serializers.CharField(source='savings_product.name', read_only=True)
    branch_name  = serializers.CharField(source='branch.name', read_only=True)

    class Meta:
        model = SavingsAccount
        fields = [
            'id', 'account_number',
            'client', 'client_name',
            'savings_product', 'product_name',
            'branch', 'branch_name',
            'balance', 'status', 'approval_status',
            'created_at',
        ]

    @extend_schema_field(serializers.CharField())
    def get_client_name(self, obj):
        return obj.client.get_full_name() if obj.client else ''


class SavingsAccountDetailSerializer(serializers.ModelSerializer):
    client         = ClientListSerializer(read_only=True)
    savings_product = SavingsProductSerializer(read_only=True)
    branch         = BranchSerializer(read_only=True)

    class Meta:
        model = SavingsAccount
        fields = [
            'id', 'account_number',
            'client', 'savings_product', 'branch',
            'balance', 'status', 'approval_status',
            'created_at', 'updated_at',
        ]
        read_only_fields = fields


# ─────────────────────────────────────────────────────────────────────────────
# Portfolio report (computed, not a model)
# ─────────────────────────────────────────────────────────────────────────────

class PortfolioReportSerializer(serializers.Serializer):
    total_loans_active    = serializers.IntegerField()
    total_portfolio_value = serializers.DecimalField(max_digits=18, decimal_places=2)
    par_1_amount          = serializers.DecimalField(max_digits=18, decimal_places=2)
    par_30_amount         = serializers.DecimalField(max_digits=18, decimal_places=2)
    par_60_amount         = serializers.DecimalField(max_digits=18, decimal_places=2)
    par_90_amount         = serializers.DecimalField(max_digits=18, decimal_places=2)
    par_1_pct             = serializers.DecimalField(max_digits=6, decimal_places=2)
    par_30_pct            = serializers.DecimalField(max_digits=6, decimal_places=2)
    par_60_pct            = serializers.DecimalField(max_digits=6, decimal_places=2)
    par_90_pct            = serializers.DecimalField(max_digits=6, decimal_places=2)
    total_savings_balance = serializers.DecimalField(max_digits=18, decimal_places=2)
    total_clients         = serializers.IntegerField()
    report_date           = serializers.DateField()
