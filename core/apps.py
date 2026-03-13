from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'core'

    def ready(self):
        from auditlog.registry import auditlog
        from core.models import (
            Client,
            Loan,
            SavingsAccount,
            User,
            LoanPenalty,
            LoanRestructureRequest,
            AssignmentRequest,
            Collateral,
            Branch,
            LoanProduct,
            SavingsProduct,
            BankReconciliation,
            BankStatementLine,
            LoanInsuranceClaim,
            InterBranchTransfer,
        )

        # Financial core — track every create/update/delete
        auditlog.register(Loan, serialize_data=True)
        auditlog.register(Client, serialize_data=True)
        auditlog.register(SavingsAccount, serialize_data=True)

        # Operational models
        auditlog.register(LoanPenalty, serialize_data=True)
        auditlog.register(LoanRestructureRequest, serialize_data=True)
        auditlog.register(AssignmentRequest, serialize_data=True)
        auditlog.register(Collateral, serialize_data=True)

        # Configuration / setup
        # Exclude profile_picture: ImageField uploads are InMemoryUploadedFile
        # objects that are not JSON-serializable during the pre_save audit hook.
        auditlog.register(User, serialize_data=True, exclude_fields=['profile_picture'])
        auditlog.register(Branch, serialize_data=True)
        auditlog.register(LoanProduct, serialize_data=True)
        auditlog.register(SavingsProduct, serialize_data=True)

        # Financial operations
        auditlog.register(BankReconciliation, serialize_data=True)
        auditlog.register(BankStatementLine, serialize_data=True)
        auditlog.register(LoanInsuranceClaim, serialize_data=True)
        auditlog.register(InterBranchTransfer, serialize_data=True)
