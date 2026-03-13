"""
Seashore Microfinance - Complete Models Package
================================================

This file imports and exposes all models for Django.
"""

# First, import base classes and utilities
from .base import (
    BaseModel,
    AuditedModel, 
    ApprovalWorkflowMixin,
    StatusTrackingMixin
)

# Import all models from the consolidated models module
from .all_models import (

    # Constants
    LOAN_TYPE_CHOICES,
    REPAYMENT_FREQUENCY_MAP,
    MONTHLY_INTEREST_RATE,
    LOAN_FORM_FEE,
    CLIENT_REGISTRATION_FEE,
    CLIENT_REGISTRATION_FEE_BREAKDOWN,


    # Core Models
    Branch,
    User,
    UserManager,
    ClientGroup,
    GroupMembershipRequest,
    Client,

    # Product Models
    LoanProduct,
    SavingsProduct,
    
    # Account Models
    SavingsAccount,
    Loan,
    LoanRepaymentPosting,

    # Transaction & Accounting
    Transaction,
    AccountType,
    AccountCategory,
    ChartOfAccounts,
    JournalEntry,
    JournalEntryLine,
    
    # Supporting Models
    Notification,
    Guarantor,
    NextOfKin,
    Collateral,
    AssignmentRequest,
    LoanRepaymentSchedule,
    LoanPenalty,


    FollowUpTask,
    PaymentPromise,
    LoanRestructureRequest,

    GroupCollectionSession,
    GroupCollectionItem,
    GroupSavingsCollectionItem,
    GroupSavingsCollectionSession,

    GroupCombinedSession,
    GroupCombinedLoanItem,
    GroupCombinedSavingsItem,

    SavingsDepositPosting,
    SavingsWithdrawalPosting,

    # Financial Operations
    BankReconciliation,
    BankStatementLine,
    LoanInsuranceClaim,
    InterBranchTransfer,




    
)

__all__ = [
    # Base Classes
    'BaseModel',
    'AuditedModel',
    'ApprovalWorkflowMixin',
    'StatusTrackingMixin',
    
    # Core Models
    'Branch',
    'User',
    'UserManager',
    'ClientGroup',
    'GroupMembershipRequest',
    'Client',

    # Product Models
    'LoanProduct',
    'SavingsProduct',
    
    # Account Models
    'SavingsAccount',
    'Loan',
    'LoanRepaymentPosting',

    # Transaction & Accounting
    'Transaction',
    'AccountType',
    'AccountCategory',
    'ChartOfAccounts',
    'JournalEntry',
    'JournalEntryLine',
    
    # Supporting Models
    'Notification',
    'Guarantor',
    'NextOfKin',
    'Collateral',
    'AssignmentRequest',
    'LoanRepaymentSchedule',
    'LoanPenalty',

    'SavingsDepositPosting',
    'SavingsWithdrawalPosting',
    
    # Constants
    'LOAN_TYPE_CHOICES',
    'REPAYMENT_FREQUENCY_MAP',
    'MONTHLY_INTEREST_RATE',
    'LOAN_FORM_FEE',
    'CLIENT_REGISTRATION_FEE',
    'CLIENT_REGISTRATION_FEE_BREAKDOWN',


    'FollowUpTask',
    'PaymentPromise',
    'LoanRestructureRequest',


    'GroupCollectionSession',
    'GroupCollectionItem',
    'GroupSavingsCollectionItem',
    'GroupSavingsCollectionSession',

    'GroupCombinedSession',
    'GroupCombinedLoanItem',
    'GroupCombinedSavingsItem',

    # Financial Operations
    'BankReconciliation',
    'BankStatementLine',
    'LoanInsuranceClaim',
    'InterBranchTransfer',
]













