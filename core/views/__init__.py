from .auth_views import (
    register_view,
    login_view,
    password_reset_confirm_view,
    password_reset_request_view,
    logout_view,
)

from .dashboard import (
    dashboard_view,
)

from .savings_product_views import (
    savings_product_list,
    savings_product_detail,
    savings_product_create,
    savings_product_update,
    savings_product_activate,
    savings_product_deactivate,
    savings_product_delete,
)

from .loan_product_views import (
    loan_product_list,
    loan_product_detail,
    loan_product_create,
    loan_product_update,
    loan_product_activate,
    loan_product_deactivate,
    loan_product_delete,
)

from .group_views import (
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

from .notification_views import (
    notification_list,
    notification_data,
    notification_mark_read,
    notification_mark_all_read,
)

from .collateral_views import (
    loan_collaterals,
    loan_add_collateral,
    loan_edit_collateral,
    loan_verify_collateral,
    loan_release_collateral,
    loan_delete_collateral,
)

from .loan_penalty_views import (
    loan_penalties,
    loan_add_penalty,
    loan_waive_penalty,
    loan_mark_penalty_paid,
)

from .followup_views import (
    followup_list,
    loan_add_followup,
    followup_update,
    followup_complete,
    followup_cancel,
)

from .payment_promise_views import (
    payment_promise_list,
    loan_add_promise,
    promise_update,
    promise_update_status,
)

from .restructure_views import (
    restructure_list,
    loan_restructure_request,
    restructure_detail,
    restructure_approve,
    restructure_reject,
)

from .assignment_views import (
    assignment_list,
    assignment_create,
    assignment_detail,
    assignment_approve,
    assignment_reject,
    assignment_cancel,
)


__all__ = [
    "register_view",
    "login_view",
    "password_reset_confirm_view",
    "password_reset_request_view",
    "logout_view",
    "dashboard_view",
    # Savings Product Views
    "savings_product_list",
    "savings_product_detail",
    "savings_product_create",
    "savings_product_update",
    "savings_product_activate",
    "savings_product_deactivate",
    "savings_product_delete",
    # Loan Product Views
    "loan_product_list",
    "loan_product_detail",
    "loan_product_create",
    "loan_product_update",
    "loan_product_activate",
    "loan_product_deactivate",
    "loan_product_delete",
    # Group Views
    "group_list",
    "group_detail",
    "group_create",
    "group_update",
    "group_approve",
    "group_add_member",
    "group_add_members_bulk",
    "group_approve_member",
    "group_approve_members_bulk",
    "group_remove_member",
    "group_update_member_role",
    # Notification Views
    "notification_list",
    "notification_data",
    "notification_mark_read",
    "notification_mark_all_read",
    # Collateral Views
    "loan_collaterals",
    "loan_add_collateral",
    "loan_edit_collateral",
    "loan_verify_collateral",
    "loan_release_collateral",
    "loan_delete_collateral",
    # Loan Penalty Views
    "loan_penalties",
    "loan_add_penalty",
    "loan_waive_penalty",
    "loan_mark_penalty_paid",
    # Follow-up Task Views
    "followup_list",
    "loan_add_followup",
    "followup_update",
    "followup_complete",
    "followup_cancel",
    # Payment Promise Views
    "payment_promise_list",
    "loan_add_promise",
    "promise_update",
    "promise_update_status",
    # Restructure Views
    "restructure_list",
    "loan_restructure_request",
    "restructure_detail",
    "restructure_approve",
    "restructure_reject",
    # Assignment Views
    "assignment_list",
    "assignment_create",
    "assignment_detail",
    "assignment_approve",
    "assignment_reject",
    "assignment_cancel",
]






























