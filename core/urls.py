from django.urls import path

from core.views import (
    register_view,
    login_view,
    password_reset_confirm_view,
    password_reset_request_view,
    logout_view,
    dashboard_view,
)

from core.views.client_views import (
    client_list,
    client_detail,
    client_create,
    client_update,
    client_approve,
    client_activate,
    client_deactivate,
    client_delete,
    client_assign_staff,
    client_pay_registration_fee,
    client_statement,
)
from core.views.client_ajax_views import (
    client_validate_tab,
    client_create_ajax,
    client_update_ajax,
    client_savings_accounts,
    client_details,
)

from core.views.branch_views import (
    branch_list,
    branch_detail,
    branch_create,
    branch_update,
    branch_activate,
    branch_deactivate,
    branch_delete,
)

from core.views.savings_product_views import (
    savings_product_list,
    savings_product_detail,
    savings_product_create,
    savings_product_update,
    savings_product_activate,
    savings_product_deactivate,
    savings_product_delete,
)

from core.views.savings_views import (
    savings_account_list,
    savings_account_detail,
    savings_account_create,
    savings_account_approve,
    savings_deposit_post,
    savings_deposit_post_bulk,
    savings_withdrawal_post,
    savings_withdrawal_post_bulk,
    savings_transaction_list,
    savings_transaction_approve,
    savings_transaction_approve_bulk,
    savings_transaction_detail,
    savings_product_api,
    savings_products_for_client,
)

from core.views.loan_product_views import (
    loan_product_list,
    loan_product_detail,
    loan_product_create,
    loan_product_update,
    loan_product_activate,
    loan_product_deactivate,
    loan_product_delete,
)

from core.views.group_views import (
    group_list,
    group_detail,
    group_create,
    group_update,
    group_approve,
    group_add_member,
    group_add_members_bulk,
    group_approve_member,
    group_approve_members_bulk,
    group_remove_member,
    group_update_member_role,
)

from core.views.group_collection_views import (
    group_collection_list,
    group_collection_detail,
    group_collection_post,
    group_collection_session_detail,
    group_collection_approve,
    group_savings_collection,
    group_combined_collection,
    group_combined_collection_post,
    group_combined_session_detail,
    group_combined_collection_approve,
    group_savings_collection_post,
    group_savings_session_detail,
    group_savings_collection_approve,
)

from core.views.user_views import (
    user_list,
    user_create,
    user_detail,
    user_edit,
    user_delete,
    user_assign_branch,
    user_profile,
    user_profile_edit,
    user_change_password,
)

from core.views.transaction_views import (
    transaction_detail,
)

from core.views.accounting_views import (
    # Dashboard
    accounting_dashboard,
    # Chart of Accounts
    chart_of_accounts_list,
    chart_of_accounts_detail,
    chart_of_accounts_create,
    chart_of_accounts_edit,
    coa_post_opening_balance,
    # Journal Entries
    journal_entry_list,
    journal_entry_detail,
    journal_entry_create,
    journal_entry_post,
    journal_entry_reverse,
    # Financial Reports
    report_trial_balance,
    report_profit_loss,
    report_balance_sheet,
    report_general_ledger,
    report_cash_flow,
    report_transaction_audit,
    report_par_aging,
    report_loan_officer_performance,
    report_savings_maturity,
    audit_log,
    subsidiary_ledger,
)

from core.views.loan_views import (
    loan_list,
    loan_detail,
    loan_create,
    loan_pay_fees,
    loan_approve,
    loan_disburse,
    loan_repayment_post,
    loan_repayment_post_bulk,
    loan_repayment_list,
    loan_repayment_approve,
    loan_repayment_approve_bulk,
    loan_product_api,
    loan_guarantors,
    loan_add_guarantor,
    loan_edit_guarantor,
    loan_delete_guarantor,
    loan_write_off,
)

from core.views.notification_views import (
    notification_list,
    notification_data,
    notification_mark_read,
    notification_mark_all_read,
)

from core.views.collateral_views import (
    loan_collaterals,
    loan_add_collateral,
    loan_edit_collateral,
    loan_verify_collateral,
    loan_release_collateral,
    loan_delete_collateral,
)

from core.views.loan_penalty_views import (
    loan_penalties,
    loan_add_penalty,
    loan_waive_penalty,
    loan_mark_penalty_paid,
)

from core.views.followup_views import (
    followup_list,
    loan_add_followup,
    followup_update,
    followup_complete,
    followup_cancel,
)

from core.views.payment_promise_views import (
    payment_promise_list,
    loan_add_promise,
    promise_update,
    promise_update_status,
)

from core.views.restructure_views import (
    restructure_list,
    loan_restructure_request,
    restructure_detail,
    restructure_approve,
    restructure_reject,
)

from core.views.assignment_views import (
    assignment_list,
    assignment_create,
    assignment_detail,
    assignment_approve,
    assignment_reject,
    assignment_cancel,
)

from core.views.reconciliation_views import (
    reconciliation_list,
    reconciliation_create,
    reconciliation_detail,
    reconciliation_add_line,
    reconciliation_match,
    reconciliation_complete,
)

from core.views.insurance_views import (
    insurance_claim_list,
    loan_file_insurance_claim,
    insurance_claim_detail,
    insurance_claim_review,
    insurance_claim_record_payout,
)

from core.views.transfer_views import (
    transfer_list,
    transfer_create,
    transfer_detail,
    transfer_approve,
    transfer_complete,
)

from core.views.import_views import (
    import_clients,
    import_loans,
    import_savings,
)

from core.views.two_factor_views import (
    verify_2fa,
    setup_2fa,
    disable_2fa,
)


app_name = "core"

urlpatterns = [
    # =========================================================================
    # AUTHENTICATION
    # =========================================================================
    path('login/', login_view, name='login'),
    path('logout/', logout_view, name='logout'),
    path('register/', register_view, name='register'),
    path('password-reset/', password_reset_request_view, name='password_reset_request'),
    path('reset-password/<str:token>/', password_reset_confirm_view, name='password_reset_confirm'),
    # 2FA
    path('verify-2fa/', verify_2fa, name='verify_2fa'),
    path('setup-2fa/', setup_2fa, name='setup_2fa'),
    path('disable-2fa/', disable_2fa, name='disable_2fa'),

    # =========================================================================
    # DASHBOARD
    # =========================================================================
    path('', dashboard_view, name='dashboard'),
    path('dashboard/', dashboard_view, name='dashboard_alt'),

    # =========================================================================
    # CLIENTS
    # =========================================================================
    path('clients/', client_list, name='client_list'),
    path('clients/create/', client_create, name='client_create'),
    path('clients/ajax/validate-tab/', client_validate_tab, name='client_validate_tab'),
    path('clients/ajax/create/', client_create_ajax, name='client_create_ajax'),
    path('clients/ajax/savings-accounts/', client_savings_accounts, name='client_savings_accounts'),
    path('clients/ajax/details/', client_details, name='client_details'),
    path('clients/<uuid:client_id>/ajax/update/', client_update_ajax, name='client_update_ajax'),
    path('clients/<uuid:client_id>/', client_detail, name='client_detail'),
    path('clients/<uuid:client_id>/edit/', client_update, name='client_update'),
    path('clients/<uuid:client_id>/approve/', client_approve, name='client_approve'),
    path('clients/<uuid:client_id>/activate/', client_activate, name='client_activate'),
    path('clients/<uuid:client_id>/deactivate/', client_deactivate, name='client_deactivate'),
    path('clients/<uuid:client_id>/delete/', client_delete, name='client_delete'),
    path('clients/<uuid:client_id>/assign-staff/', client_assign_staff, name='client_assign_staff'),
    path('clients/<uuid:client_id>/pay-registration-fee/', client_pay_registration_fee, name='client_pay_registration_fee'),
    path('clients/<uuid:client_id>/statement/', client_statement, name='client_statement'),
    path('clients/<uuid:client_id>/subsidiary-ledger/', subsidiary_ledger, name='subsidiary_ledger'),

    # =========================================================================
    # BRANCHES
    # =========================================================================
    path('branches/', branch_list, name='branch_list'),
    path('branches/create/', branch_create, name='branch_create'),
    path('branches/<uuid:branch_id>/', branch_detail, name='branch_detail'),
    path('branches/<uuid:branch_id>/edit/', branch_update, name='branch_update'),
    path('branches/<uuid:branch_id>/activate/', branch_activate, name='branch_activate'),
    path('branches/<uuid:branch_id>/deactivate/', branch_deactivate, name='branch_deactivate'),
    path('branches/<uuid:branch_id>/delete/', branch_delete, name='branch_delete'),

    # =========================================================================
    # SAVINGS PRODUCTS
    # =========================================================================
    path('products/savings/', savings_product_list, name='savings_product_list'),
    path('products/savings/create/', savings_product_create, name='savings_product_create'),
    path('products/savings/<uuid:product_id>/', savings_product_detail, name='savings_product_detail'),
    path('products/savings/<uuid:product_id>/edit/', savings_product_update, name='savings_product_update'),
    path('products/savings/<uuid:product_id>/activate/', savings_product_activate, name='savings_product_activate'),
    path('products/savings/<uuid:product_id>/deactivate/', savings_product_deactivate, name='savings_product_deactivate'),
    path('products/savings/<uuid:product_id>/delete/', savings_product_delete, name='savings_product_delete'),

    # =========================================================================
    # SAVINGS ACCOUNTS
    # =========================================================================
    path('savings/', savings_account_list, name='savings_account_list'),
    path('savings/create/', savings_account_create, name='savings_account_create'),
    path('savings/<uuid:account_id>/', savings_account_detail, name='savings_account_detail'),
    path('savings/<uuid:account_id>/approve/', savings_account_approve, name='savings_account_approve'),

    # Savings Deposits
    path('savings/deposits/post/', savings_deposit_post, name='savings_deposit_post'),
    path('savings/deposits/post/<uuid:account_id>/', savings_deposit_post, name='savings_deposit_post_for_account'),
    path('savings/deposits/post/bulk/', savings_deposit_post_bulk, name='savings_deposit_post_bulk'),
    path('savings/deposits/<uuid:posting_id>/approve/', savings_transaction_approve, {'posting_type': 'deposit'}, name='savings_deposit_approve'),

    # Savings Withdrawals
    path('savings/withdrawals/post/', savings_withdrawal_post, name='savings_withdrawal_post'),
    path('savings/withdrawals/post/<uuid:account_id>/', savings_withdrawal_post, name='savings_withdrawal_post_for_account'),
    path('savings/withdrawals/post/bulk/', savings_withdrawal_post_bulk, name='savings_withdrawal_post_bulk'),
    path('savings/withdrawals/<uuid:posting_id>/approve/', savings_transaction_approve, {'posting_type': 'withdrawal'}, name='savings_withdrawal_approve'),

    # Combined Transaction Views
    path('savings/transactions/', savings_transaction_list, name='savings_transaction_list'),
    path('savings/transactions/approve/bulk/', savings_transaction_approve_bulk, name='savings_transaction_approve_bulk'),
    path('savings/transactions/<str:posting_type>/<uuid:posting_id>/', savings_transaction_detail, name='savings_transaction_detail'),

    # =========================================================================
    # LOAN PRODUCTS
    # =========================================================================
    path('products/loans/', loan_product_list, name='loan_product_list'),
    path('products/loans/create/', loan_product_create, name='loan_product_create'),
    path('products/loans/<uuid:product_id>/', loan_product_detail, name='loan_product_detail'),
    path('products/loans/<uuid:product_id>/edit/', loan_product_update, name='loan_product_update'),
    path('products/loans/<uuid:product_id>/activate/', loan_product_activate, name='loan_product_activate'),
    path('products/loans/<uuid:product_id>/deactivate/', loan_product_deactivate, name='loan_product_deactivate'),
    path('products/loans/<uuid:product_id>/delete/', loan_product_delete, name='loan_product_delete'),

    # =========================================================================
    # CLIENT GROUPS
    # =========================================================================
    path('groups/', group_list, name='group_list'),
    path('groups/create/', group_create, name='group_create'),
    path('groups/<uuid:group_id>/', group_detail, name='group_detail'),
    path('groups/<uuid:group_id>/edit/', group_update, name='group_update'),
    path('groups/<uuid:group_id>/approve/', group_approve, name='group_approve'),

    # Member Management
    path('groups/<uuid:group_id>/add-member/', group_add_member, name='group_add_member'),
    path('groups/<uuid:group_id>/add-members-bulk/', group_add_members_bulk, name='group_add_members_bulk'),
    path('groups/<uuid:group_id>/approve-members-bulk/', group_approve_members_bulk, name='group_approve_members_bulk'),
    path('groups/<uuid:group_id>/members/<uuid:client_id>/remove/', group_remove_member, name='group_remove_member'),
    path('groups/<uuid:group_id>/members/<uuid:client_id>/update-role/', group_update_member_role, name='group_update_member_role'),
    path('groups/membership-requests/<uuid:request_id>/approve/', group_approve_member, name='group_approve_member'),

    # Group Collections - Loan Repayments
    path('groups/collections/', group_collection_list, name='group_collection_list'),
    path('groups/<uuid:group_id>/collect/', group_collection_detail, name='group_collection_detail'),
    path('groups/<uuid:group_id>/collect/post/', group_collection_post, name='group_collection_post'),
    path('groups/collections/<uuid:session_id>/', group_collection_session_detail, name='group_collection_session_detail'),
    path('groups/collections/<uuid:session_id>/approve/', group_collection_approve, name='group_collection_approve'),

    # Group Collections - Savings
    path('groups/<uuid:group_id>/collect-savings/', group_savings_collection, name='group_savings_collection'),
    path('groups/<uuid:group_id>/collect-savings/post/', group_savings_collection_post, name='group_savings_collection_post'),
    path('groups/savings-collections/<uuid:session_id>/', group_savings_session_detail, name='group_savings_session_detail'),
    path('groups/savings-collections/<uuid:session_id>/approve/', group_savings_collection_approve, name='group_savings_collection_approve'),

    # Group Collections - Combined (Loans + Savings)
    path('groups/<uuid:group_id>/collect-all/', group_combined_collection, name='group_combined_collection'),
    path('groups/<uuid:group_id>/collect-all/post/', group_combined_collection_post, name='group_combined_collection_post'),
    path('groups/combined-collections/<uuid:session_id>/', group_combined_session_detail, name='group_combined_session_detail'),
    path('groups/combined-collections/<uuid:session_id>/approve/', group_combined_collection_approve, name='group_combined_collection_approve'),

    # =========================================================================
    # USERS/STAFF MANAGEMENT
    # =========================================================================
    path('staff/', user_list, name='user_list'),
    path('staff/create/', user_create, name='user_create'),
    path('staff/<uuid:user_id>/', user_detail, name='user_detail'),
    path('staff/<uuid:user_id>/edit/', user_edit, name='user_edit'),
    path('staff/<uuid:user_id>/delete/', user_delete, name='user_delete'),
    path('staff/<uuid:user_id>/assign-branch/', user_assign_branch, name='user_assign_branch'),
    path('staff/<uuid:user_id>/change-password/', user_change_password, name='user_change_password'),

    # User Profile (for logged-in user)
    path('profile/', user_profile, name='user_profile'),
    path('profile/edit/', user_profile_edit, name='user_profile_edit'),

    # =========================================================================
    # TRANSACTIONS
    # =========================================================================
    path('transactions/<uuid:transaction_id>/', transaction_detail, name='transaction_detail'),

    # =========================================================================
    # LOANS
    # =========================================================================
    path('loans/', loan_list, name='loan_list'),
    path('loans/create/', loan_create, name='loan_create'),
    path('loans/<uuid:loan_id>/', loan_detail, name='loan_detail'),
    path('loans/<uuid:loan_id>/pay-fees/', loan_pay_fees, name='loan_pay_fees'),
    path('loans/<uuid:loan_id>/approve/', loan_approve, name='loan_approve'),
    path('loans/<uuid:loan_id>/disburse/', loan_disburse, name='loan_disburse'),
    path('loans/<uuid:loan_id>/write-off/', loan_write_off, name='loan_write_off'),

    # Loan Guarantors
    path('loans/<uuid:loan_id>/guarantors/', loan_guarantors, name='loan_guarantors'),
    path('loans/<uuid:loan_id>/guarantors/add/', loan_add_guarantor, name='loan_add_guarantor'),
    path('loans/<uuid:loan_id>/guarantors/<uuid:guarantor_id>/edit/', loan_edit_guarantor, name='loan_edit_guarantor'),
    path('loans/<uuid:loan_id>/guarantors/<uuid:guarantor_id>/delete/', loan_delete_guarantor, name='loan_delete_guarantor'),

    # Loan Repayments
    path('loans/repayments/', loan_repayment_list, name='loan_repayment_list'),
    path('loans/repayments/post/', loan_repayment_post, name='loan_repayment_post'),
    path('loans/repayments/post/<uuid:loan_id>/', loan_repayment_post, name='loan_repayment_post_for_loan'),
    path('loans/repayments/post/bulk/', loan_repayment_post_bulk, name='loan_repayment_post_bulk'),
    path('loans/repayments/<uuid:posting_id>/approve/', loan_repayment_approve, name='loan_repayment_approve'),
    path('loans/repayments/approve/bulk/', loan_repayment_approve_bulk, name='loan_repayment_approve_bulk'),

    # Loan Collaterals
    path('loans/<uuid:loan_id>/collaterals/', loan_collaterals, name='loan_collaterals'),
    path('loans/<uuid:loan_id>/collaterals/add/', loan_add_collateral, name='loan_add_collateral'),
    path('loans/<uuid:loan_id>/collaterals/<uuid:collateral_id>/edit/', loan_edit_collateral, name='loan_edit_collateral'),
    path('loans/<uuid:loan_id>/collaterals/<uuid:collateral_id>/verify/', loan_verify_collateral, name='loan_verify_collateral'),
    path('loans/<uuid:loan_id>/collaterals/<uuid:collateral_id>/release/', loan_release_collateral, name='loan_release_collateral'),
    path('loans/<uuid:loan_id>/collaterals/<uuid:collateral_id>/delete/', loan_delete_collateral, name='loan_delete_collateral'),

    # Loan Penalties
    path('loans/<uuid:loan_id>/penalties/', loan_penalties, name='loan_penalties'),
    path('loans/<uuid:loan_id>/penalties/add/', loan_add_penalty, name='loan_add_penalty'),
    path('loans/<uuid:loan_id>/penalties/<uuid:penalty_id>/waive/', loan_waive_penalty, name='loan_waive_penalty'),
    path('loans/<uuid:loan_id>/penalties/<uuid:penalty_id>/mark-paid/', loan_mark_penalty_paid, name='loan_mark_penalty_paid'),

    # Loan Restructure Requests
    path('loans/<uuid:loan_id>/restructure/request/', loan_restructure_request, name='loan_restructure_request'),

    # Loan Follow-up Tasks
    path('loans/<uuid:loan_id>/follow-ups/add/', loan_add_followup, name='loan_add_followup'),

    # Loan Payment Promises
    path('loans/<uuid:loan_id>/payment-promises/add/', loan_add_promise, name='loan_add_promise'),

    # Internal product detail endpoints (used by form JS; must NOT start with api/ as
    # that prefix is claimed by the DRF router in seashore/urls.py)
    path('internal/loan-product/<uuid:product_id>/', loan_product_api, name='loan_product_api'),
    path('internal/savings-product/<uuid:product_id>/', savings_product_api, name='savings_product_api'),
    path('internal/savings-products-for-client/<uuid:client_id>/', savings_products_for_client, name='savings_products_for_client'),

    # =========================================================================
    # NOTIFICATIONS
    # =========================================================================
    path('notifications/', notification_list, name='notification_list'),
    path('notifications/data/', notification_data, name='notification_data'),
    path('notifications/<uuid:notification_id>/read/', notification_mark_read, name='notification_mark_read'),
    path('notifications/read-all/', notification_mark_all_read, name='notification_mark_all_read'),

    # =========================================================================
    # FOLLOW-UP TASKS
    # =========================================================================
    path('follow-ups/', followup_list, name='followup_list'),
    path('follow-ups/<uuid:task_id>/edit/', followup_update, name='followup_update'),
    path('follow-ups/<uuid:task_id>/complete/', followup_complete, name='followup_complete'),
    path('follow-ups/<uuid:task_id>/cancel/', followup_cancel, name='followup_cancel'),

    # =========================================================================
    # PAYMENT PROMISES
    # =========================================================================
    path('payment-promises/', payment_promise_list, name='payment_promise_list'),
    path('payment-promises/<uuid:promise_id>/edit/', promise_update, name='promise_update'),
    path('payment-promises/<uuid:promise_id>/update-status/', promise_update_status, name='promise_update_status'),

    # =========================================================================
    # LOAN RESTRUCTURE REQUESTS
    # =========================================================================
    path('restructures/', restructure_list, name='restructure_list'),
    path('restructures/<uuid:request_id>/', restructure_detail, name='restructure_detail'),
    path('restructures/<uuid:request_id>/approve/', restructure_approve, name='restructure_approve'),
    path('restructures/<uuid:request_id>/reject/', restructure_reject, name='restructure_reject'),

    # =========================================================================
    # ASSIGNMENT REQUESTS
    # =========================================================================
    path('assignments/', assignment_list, name='assignment_list'),
    path('assignments/create/', assignment_create, name='assignment_create'),
    path('assignments/<uuid:request_id>/', assignment_detail, name='assignment_detail'),
    path('assignments/<uuid:request_id>/approve/', assignment_approve, name='assignment_approve'),
    path('assignments/<uuid:request_id>/reject/', assignment_reject, name='assignment_reject'),
    path('assignments/<uuid:request_id>/cancel/', assignment_cancel, name='assignment_cancel'),

    # =========================================================================
    # ACCOUNTING MODULE
    # =========================================================================

    # Dashboard
    path('accounting/', accounting_dashboard, name='accounting_dashboard'),

    # Chart of Accounts
    path('accounting/coa/', chart_of_accounts_list, name='coa_list'),
    path('accounting/coa/create/', chart_of_accounts_create, name='coa_create'),
    path('accounting/coa/<uuid:account_id>/', chart_of_accounts_detail, name='coa_detail'),
    path('accounting/coa/<uuid:account_id>/edit/', chart_of_accounts_edit, name='coa_edit'),
    path('accounting/coa/<uuid:account_id>/opening-balance/', coa_post_opening_balance, name='coa_opening_balance'),

    # Journal Entries
    path('accounting/journals/', journal_entry_list, name='journal_entry_list'),
    path('accounting/journals/create/', journal_entry_create, name='journal_entry_create'),
    path('accounting/journals/<uuid:entry_id>/', journal_entry_detail, name='journal_entry_detail'),
    path('accounting/journals/<uuid:entry_id>/post/', journal_entry_post, name='journal_entry_post'),
    path('accounting/journals/<uuid:entry_id>/reverse/', journal_entry_reverse, name='journal_entry_reverse'),

    # Financial Reports
    path('accounting/reports/trial-balance/', report_trial_balance, name='report_trial_balance'),
    path('accounting/reports/profit-loss/', report_profit_loss, name='report_profit_loss'),
    path('accounting/reports/balance-sheet/', report_balance_sheet, name='report_balance_sheet'),
    path('accounting/reports/general-ledger/', report_general_ledger, name='report_general_ledger'),
    path('accounting/reports/cash-flow/', report_cash_flow, name='report_cash_flow'),
    path('accounting/reports/transaction-audit/', report_transaction_audit, name='report_transaction_audit'),
    path('accounting/reports/par-aging/', report_par_aging, name='report_par_aging'),
    path('accounting/reports/loan-officer-performance/', report_loan_officer_performance, name='report_loan_officer_performance'),
    path('accounting/reports/savings-maturity/', report_savings_maturity, name='report_savings_maturity'),
    path('accounting/audit-log/', audit_log, name='audit_log'),

    # =========================================================================
    # BANK / CASH RECONCILIATION
    # =========================================================================
    path('accounting/reconciliation/', reconciliation_list, name='reconciliation_list'),
    path('accounting/reconciliation/create/', reconciliation_create, name='reconciliation_create'),
    path('accounting/reconciliation/<uuid:recon_id>/', reconciliation_detail, name='reconciliation_detail'),
    path('accounting/reconciliation/<uuid:recon_id>/add-line/', reconciliation_add_line, name='reconciliation_add_line'),
    path('accounting/reconciliation/<uuid:recon_id>/match/', reconciliation_match, name='reconciliation_match'),
    path('accounting/reconciliation/<uuid:recon_id>/complete/', reconciliation_complete, name='reconciliation_complete'),

    # =========================================================================
    # LOAN INSURANCE CLAIMS
    # =========================================================================
    path('insurance/', insurance_claim_list, name='insurance_claim_list'),
    path('loans/<uuid:loan_id>/insurance/file/', loan_file_insurance_claim, name='loan_file_insurance_claim'),
    path('insurance/<uuid:claim_id>/', insurance_claim_detail, name='insurance_claim_detail'),
    path('insurance/<uuid:claim_id>/review/', insurance_claim_review, name='insurance_claim_review'),
    path('insurance/<uuid:claim_id>/payout/', insurance_claim_record_payout, name='insurance_claim_record_payout'),

    # =========================================================================
    # INTER-BRANCH TRANSFERS
    # =========================================================================
    path('transfers/', transfer_list, name='transfer_list'),
    path('transfers/create/', transfer_create, name='transfer_create'),
    path('transfers/<uuid:transfer_id>/', transfer_detail, name='transfer_detail'),
    path('transfers/<uuid:transfer_id>/approve/', transfer_approve, name='transfer_approve'),
    path('transfers/<uuid:transfer_id>/complete/', transfer_complete, name='transfer_complete'),

    # =========================================================================
    # BULK CSV IMPORTS
    # =========================================================================
    path('imports/clients/', import_clients, name='import_clients'),
    path('imports/loans/',   import_loans,   name='import_loans'),
    path('imports/savings/', import_savings, name='import_savings'),

]
