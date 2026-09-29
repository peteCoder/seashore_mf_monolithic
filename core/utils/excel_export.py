"""
Excel/CSV Export Utilities using Pandas
========================================

Professional Excel exports for accounting reports
"""

from django.http import HttpResponse
from django.utils import timezone
import pandas as pd
from io import BytesIO
from datetime import datetime
from decimal import Decimal


def create_excel_response(filename='report.xlsx'):
    """Create an HTTP response for Excel file download"""
    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


def create_csv_response(filename='report.csv'):
    """Create an HTTP response for CSV file download"""
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


def export_trial_balance_excel(report_data, form_data):
    """Export Trial Balance to Excel"""
    # Create Excel writer
    output = BytesIO()
    writer = pd.ExcelWriter(output, engine='openpyxl')

    # Prepare data
    trial_balance_data = []
    for item in report_data['trial_balance']:
        trial_balance_data.append({
            'GL Code': item['account'].gl_code,
            'Account Name': item['account'].account_name,
            'Account Type': item['account'].account_type.get_name_display(),
            'Debit (₦)': float(item['debit']) if item['debit'] > 0 else 0,
            'Credit (₦)': float(item['credit']) if item['credit'] > 0 else 0,
        })

    # Create DataFrame
    df = pd.DataFrame(trial_balance_data)

    # Add totals row
    totals_row = pd.DataFrame([{
        'GL Code': '',
        'Account Name': 'TOTAL',
        'Account Type': '',
        'Debit (₦)': float(report_data['total_debits']),
        'Credit (₦)': float(report_data['total_credits']),
    }])
    df = pd.concat([df, totals_row], ignore_index=True)

    # Write to Excel
    df.to_excel(writer, sheet_name='Trial Balance', index=False)

    # Get workbook and worksheet
    workbook = writer.book
    worksheet = writer.sheets['Trial Balance']

    # Apply styling
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter

    # Header styling
    header_fill = PatternFill(start_color='D97706', end_color='D97706', fill_type='solid')
    header_font = Font(bold=True, color='FFFFFF', size=11)

    for col_num, col in enumerate(df.columns, 1):
        cell = worksheet.cell(row=1, column=col_num)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal='center', vertical='center')

    # Totals row styling
    totals_fill = PatternFill(start_color='FEF3C7', end_color='FEF3C7', fill_type='solid')
    totals_font = Font(bold=True, size=11)
    last_row = len(df) + 1

    for col_num in range(1, len(df.columns) + 1):
        cell = worksheet.cell(row=last_row, column=col_num)
        cell.fill = totals_fill
        cell.font = totals_font

    # Number formatting for currency columns
    for row in range(2, last_row + 1):
        worksheet.cell(row=row, column=4).number_format = '#,##0.00'  # Debit
        worksheet.cell(row=row, column=5).number_format = '#,##0.00'  # Credit

    # Adjust column widths
    worksheet.column_dimensions['A'].width = 12  # GL Code
    worksheet.column_dimensions['B'].width = 40  # Account Name
    worksheet.column_dimensions['C'].width = 20  # Account Type
    worksheet.column_dimensions['D'].width = 18  # Debit
    worksheet.column_dimensions['E'].width = 18  # Credit

    # Add report header information
    worksheet.insert_rows(1, 3)
    worksheet.merge_cells('A1:E1')
    worksheet.merge_cells('A2:E2')
    worksheet.merge_cells('A3:E3')

    title_cell = worksheet['A1']
    title_cell.value = 'TRIAL BALANCE'
    title_cell.font = Font(bold=True, size=16, color='D97706')
    title_cell.alignment = Alignment(horizontal='center')

    period_cell = worksheet['A2']
    period_cell.value = f'Period: {report_data["date_from"].strftime("%B %d, %Y")} to {report_data["date_to"].strftime("%B %d, %Y")}'
    period_cell.alignment = Alignment(horizontal='center')

    balance_cell = worksheet['A3']
    balance_status = 'BALANCED ✓' if report_data['is_balanced'] else 'NOT BALANCED ✗'
    balance_cell.value = f'Status: {balance_status}'
    balance_cell.font = Font(bold=True, color='059669' if report_data['is_balanced'] else 'DC2626')
    balance_cell.alignment = Alignment(horizontal='center')

    # Save
    writer.close()
    output.seek(0)

    filename = f'trial_balance_{report_data["date_from"].strftime("%Y%m%d")}_{report_data["date_to"].strftime("%Y%m%d")}.xlsx'
    response = create_excel_response(filename)
    response.write(output.read())
    return response


def export_profit_loss_excel(report_data, form_data):
    """Export Profit & Loss to Excel"""
    output = BytesIO()
    writer = pd.ExcelWriter(output, engine='openpyxl')

    # Income section
    income_data = []
    for item in report_data['income_items']:
        income_data.append({
            'GL Code': item['account'].gl_code,
            'Account': item['account'].account_name,
            'Amount (₦)': float(item['amount']),
        })

    # Expense section
    expense_data = []
    for item in report_data['expense_items']:
        expense_data.append({
            'GL Code': item['account'].gl_code,
            'Account': item['account'].account_name,
            'Amount (₦)': float(item['amount']),
        })

    # Create DataFrames
    df_income = pd.DataFrame(income_data)
    df_expense = pd.DataFrame(expense_data)

    # Write to separate sheets
    df_income.to_excel(writer, sheet_name='Income', index=False)
    df_expense.to_excel(writer, sheet_name='Expenses', index=False)

    # Create summary sheet
    summary_data = pd.DataFrame([
        {'Item': 'Total Income', 'Amount (₦)': float(report_data['total_income'])},
        {'Item': 'Total Expenses', 'Amount (₦)': float(report_data['total_expenses'])},
        {'Item': 'Net Profit/Loss', 'Amount (₦)': float(report_data['net_profit'])},
    ])
    summary_data.to_excel(writer, sheet_name='Summary', index=False)

    # Apply styling (similar to trial balance)
    from openpyxl.styles import Font, PatternFill, Alignment

    for sheet_name in writer.sheets:
        worksheet = writer.sheets[sheet_name]

        # Header styling
        for col_num in range(1, 4):
            cell = worksheet.cell(row=1, column=col_num)
            cell.fill = PatternFill(start_color='D97706', end_color='D97706', fill_type='solid')
            cell.font = Font(bold=True, color='FFFFFF')
            cell.alignment = Alignment(horizontal='center')

        # Column widths
        worksheet.column_dimensions['A'].width = 15
        worksheet.column_dimensions['B'].width = 40
        worksheet.column_dimensions['C'].width = 18

    writer.close()
    output.seek(0)

    filename = f'profit_loss_{report_data["date_from"].strftime("%Y%m%d")}_{report_data["date_to"].strftime("%Y%m%d")}.xlsx'
    response = create_excel_response(filename)
    response.write(output.read())
    return response


def export_general_ledger_excel(report_data, form_data):
    """Export General Ledger to Excel"""
    output = BytesIO()
    writer = pd.ExcelWriter(output, engine='openpyxl')

    # Prepare transaction data
    transactions_data = []
    for txn in report_data['transactions']:
        transactions_data.append({
            'Date': txn['line'].journal_entry.transaction_date.strftime('%Y-%m-%d'),
            'Journal Number': txn['line'].journal_entry.journal_number,
            'Description': txn['line'].description,
            'Debit (₦)': float(txn['line'].debit_amount) if txn['line'].debit_amount > 0 else 0,
            'Credit (₦)': float(txn['line'].credit_amount) if txn['line'].credit_amount > 0 else 0,
            'Balance (₦)': float(txn['running_balance']),
        })

    df = pd.DataFrame(transactions_data)
    df.to_excel(writer, sheet_name='General Ledger', index=False)

    # Styling
    worksheet = writer.sheets['General Ledger']
    from openpyxl.styles import Font, PatternFill, Alignment

    # Add header info
    worksheet.insert_rows(1, 4)
    worksheet.merge_cells('A1:F1')
    worksheet.merge_cells('A2:F2')
    worksheet.merge_cells('A3:F3')

    worksheet['A1'] = 'GENERAL LEDGER'
    worksheet['A1'].font = Font(bold=True, size=16, color='D97706')
    worksheet['A1'].alignment = Alignment(horizontal='center')

    worksheet['A2'] = f'{report_data["account"].gl_code} - {report_data["account"].account_name}'
    worksheet['A2'].font = Font(bold=True, size=12)
    worksheet['A2'].alignment = Alignment(horizontal='center')

    worksheet['A3'] = f'Period: {report_data["date_from"].strftime("%B %d, %Y")} to {report_data["date_to"].strftime("%B %d, %Y")}'
    worksheet['A3'].alignment = Alignment(horizontal='center')

    worksheet['A4'] = f'Opening Balance: ₦{report_data["opening_balance"]:,.2f}'
    worksheet['A4'].font = Font(bold=True)

    writer.close()
    output.seek(0)

    filename = f'general_ledger_{report_data["account"].gl_code}_{report_data["date_from"].strftime("%Y%m%d")}.xlsx'
    response = create_excel_response(filename)
    response.write(output.read())
    return response


def export_balance_sheet_excel(report_data, form_data):
    """Export Balance Sheet to Excel"""
    output = BytesIO()
    writer = pd.ExcelWriter(output, engine='openpyxl')

    def _acct_row(item):
        acct = item.get('account')
        return {
            'GL Code': acct.gl_code if acct else '',
            'Account': acct.account_name if acct else item.get('account_name', ''),
            'Balance (₦)': float(item['balance']),
        }

    # Assets section
    assets_data = [_acct_row(i) for i in report_data['assets']]

    # Liabilities section
    liabilities_data = [_acct_row(i) for i in report_data['liabilities']]

    # Equity section
    equity_data = [_acct_row(i) for i in report_data['equity']]

    # Create DataFrames
    df_assets = pd.DataFrame(assets_data)
    df_liabilities = pd.DataFrame(liabilities_data)
    df_equity = pd.DataFrame(equity_data)

    # Write to separate sheets
    df_assets.to_excel(writer, sheet_name='Assets', index=False)
    df_liabilities.to_excel(writer, sheet_name='Liabilities', index=False)
    df_equity.to_excel(writer, sheet_name='Equity', index=False)

    # Create summary sheet
    summary_data = pd.DataFrame([
        {'Category': 'Total Assets', 'Amount (₦)': float(report_data['total_assets'])},
        {'Category': 'Total Liabilities', 'Amount (₦)': float(report_data['total_liabilities'])},
        {'Category': 'Total Equity', 'Amount (₦)': float(report_data['total_equity'])},
        {'Category': 'Total Liabilities + Equity', 'Amount (₦)': float(report_data['total_liabilities_equity'])},
    ])
    summary_data.to_excel(writer, sheet_name='Summary', index=False)

    # Apply styling
    from openpyxl.styles import Font, PatternFill, Alignment

    for sheet_name in writer.sheets:
        worksheet = writer.sheets[sheet_name]

        # Header styling
        for col_num in range(1, 4):
            cell = worksheet.cell(row=1, column=col_num)
            cell.fill = PatternFill(start_color='D97706', end_color='D97706', fill_type='solid')
            cell.font = Font(bold=True, color='FFFFFF')
            cell.alignment = Alignment(horizontal='center')

        # Column widths
        worksheet.column_dimensions['A'].width = 15
        worksheet.column_dimensions['B'].width = 40
        worksheet.column_dimensions['C'].width = 18

    writer.close()
    output.seek(0)

    filename = f'balance_sheet_{report_data["as_of_date"].strftime("%Y%m%d")}.xlsx'
    response = create_excel_response(filename)
    response.write(output.read())
    return response


def export_cash_flow_excel(report_data, form_data):
    """Export Cash Flow Statement to Excel"""
    output = BytesIO()
    writer = pd.ExcelWriter(output, engine='openpyxl')

    # Operating activities
    operating_data = []
    for item in report_data['operating_activities']:
        operating_data.append({
            'Date': item['line'].journal_entry.transaction_date.strftime('%Y-%m-%d'),
            'Description': item['line'].description,
            'Amount (₦)': float(item['amount']),
        })

    # Investing activities
    investing_data = []
    for item in report_data['investing_activities']:
        investing_data.append({
            'Date': item['line'].journal_entry.transaction_date.strftime('%Y-%m-%d'),
            'Description': item['line'].description,
            'Amount (₦)': float(item['amount']),
        })

    # Create DataFrames
    df_operating = pd.DataFrame(operating_data) if operating_data else pd.DataFrame(columns=['Date', 'Description', 'Amount (₦)'])
    df_investing = pd.DataFrame(investing_data) if investing_data else pd.DataFrame(columns=['Date', 'Description', 'Amount (₦)'])

    # Write to separate sheets
    df_operating.to_excel(writer, sheet_name='Operating Activities', index=False)
    df_investing.to_excel(writer, sheet_name='Investing Activities', index=False)

    # Create summary sheet
    summary_data = pd.DataFrame([
        {'Activity Type': 'Operating Activities', 'Total (₦)': float(report_data['operating_total'])},
        {'Activity Type': 'Investing Activities', 'Total (₦)': float(report_data['investing_total'])},
        {'Activity Type': 'Financing Activities', 'Total (₦)': float(report_data['financing_total'])},
        {'Activity Type': 'Net Cash Flow', 'Total (₦)': float(report_data['net_cash_flow'])},
    ])
    summary_data.to_excel(writer, sheet_name='Summary', index=False)

    # Apply styling
    from openpyxl.styles import Font, PatternFill, Alignment

    for sheet_name in writer.sheets:
        worksheet = writer.sheets[sheet_name]

        # Header styling
        for col_num in range(1, 4):
            cell = worksheet.cell(row=1, column=col_num)
            cell.fill = PatternFill(start_color='D97706', end_color='D97706', fill_type='solid')
            cell.font = Font(bold=True, color='FFFFFF')
            cell.alignment = Alignment(horizontal='center')

        # Column widths
        worksheet.column_dimensions['A'].width = 15
        worksheet.column_dimensions['B'].width = 50
        worksheet.column_dimensions['C'].width = 18

    writer.close()
    output.seek(0)

    filename = f'cash_flow_{report_data["date_from"].strftime("%Y%m%d")}_{report_data["date_to"].strftime("%Y%m%d")}.xlsx'
    response = create_excel_response(filename)
    response.write(output.read())
    return response


def export_transaction_audit_excel(report_data, form_data):
    """Export Transaction Audit Log to Excel"""
    output = BytesIO()
    writer = pd.ExcelWriter(output, engine='openpyxl')

    # Prepare audit data
    audit_data_list = []
    for item in report_data['audit_data']:
        txn = item['transaction']
        journal_status = 'Yes' if item['has_journal'] else 'NO - MISSING ⚠️'

        audit_data_list.append({
            'Date': txn.transaction_date.strftime('%Y-%m-%d'),
            'Transaction Ref': txn.transaction_ref,
            'Type': txn.transaction_type,
            'Client': txn.client.get_full_name() if txn.client else 'N/A',
            'Amount (₦)': float(txn.amount),
            'Branch': txn.branch.name if txn.branch else 'N/A',
            'Has Journal Entry': journal_status,
        })

    df = pd.DataFrame(audit_data_list)
    df.to_excel(writer, sheet_name='Audit Log', index=False)

    # Styling
    worksheet = writer.sheets['Audit Log']
    from openpyxl.styles import Font, PatternFill, Alignment

    # Add header info
    worksheet.insert_rows(1, 3)
    worksheet.merge_cells('A1:G1')
    worksheet.merge_cells('A2:G2')

    worksheet['A1'] = 'TRANSACTION AUDIT LOG'
    worksheet['A1'].font = Font(bold=True, size=16, color='D97706')
    worksheet['A1'].alignment = Alignment(horizontal='center')

    worksheet['A2'] = f'Total Transactions: {report_data["total_transactions"]} | Missing Journal Entries: {report_data["missing_journal_count"]}'
    worksheet['A2'].font = Font(bold=True, color='DC2626' if report_data["missing_journal_count"] > 0 else '059669')
    worksheet['A2'].alignment = Alignment(horizontal='center')

    # Header row styling
    header_fill = PatternFill(start_color='D97706', end_color='D97706', fill_type='solid')
    header_font = Font(bold=True, color='FFFFFF')

    for col_num in range(1, 8):
        cell = worksheet.cell(row=4, column=col_num)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal='center')

    # Highlight missing journal entries
    alert_fill = PatternFill(start_color='FEE2E2', end_color='FEE2E2', fill_type='solid')
    for row in range(5, len(audit_data_list) + 5):
        status_cell = worksheet.cell(row=row, column=7)
        if 'MISSING' in str(status_cell.value):
            for col in range(1, 8):
                worksheet.cell(row=row, column=col).fill = alert_fill

    # Column widths
    worksheet.column_dimensions['A'].width = 12
    worksheet.column_dimensions['B'].width = 20
    worksheet.column_dimensions['C'].width = 20
    worksheet.column_dimensions['D'].width = 30
    worksheet.column_dimensions['E'].width = 15
    worksheet.column_dimensions['F'].width = 20
    worksheet.column_dimensions['G'].width = 25

    writer.close()
    output.seek(0)

    filename = f'transaction_audit_{datetime.now().strftime("%Y%m%d_%H%M%S")}.xlsx'
    response = create_excel_response(filename)
    response.write(output.read())
    return response


def export_to_csv(data, columns, filename='export.csv'):
    """Generic CSV export function"""
    df = pd.DataFrame(data, columns=columns)

    response = create_csv_response(filename)
    df.to_csv(response, index=False)
    return response


# ---------------------------------------------------------------------------
# Shared styling helper
# ---------------------------------------------------------------------------

def _style_sheet(worksheet, header_col_count, title=None, subtitle=None,
                 currency_cols=None, col_widths=None):
    """Apply consistent header styling and optional title rows to a worksheet."""
    from openpyxl.styles import Font, PatternFill, Alignment

    from openpyxl.utils import get_column_letter
    BRAND_ORANGE = 'D97706'
    HEADER_FILL = PatternFill(start_color=BRAND_ORANGE, end_color=BRAND_ORANGE, fill_type='solid')
    HEADER_FONT = Font(bold=True, color='FFFFFF', size=11)
    TITLE_FONT  = Font(bold=True, size=14, color=BRAND_ORANGE)
    TOTAL_FILL  = PatternFill(start_color='FEF3C7', end_color='FEF3C7', fill_type='solid')

    insert_count = 0
    if title:
        insert_count += 1
    if subtitle:
        insert_count += 1

    if insert_count:
        worksheet.insert_rows(1, insert_count)
        row = 1
        col_letter = get_column_letter(header_col_count)
        if title:
            worksheet.merge_cells(f'A{row}:{col_letter}{row}')
            cell = worksheet[f'A{row}']
            cell.value = title
            cell.font = TITLE_FONT
            cell.alignment = Alignment(horizontal='center')
            row += 1
        if subtitle:
            worksheet.merge_cells(f'A{row}:{col_letter}{row}')
            cell = worksheet[f'A{row}']
            cell.value = subtitle
            cell.alignment = Alignment(horizontal='center')

    # Style header row (first row after title rows)
    header_row = insert_count + 1
    for col in range(1, header_col_count + 1):
        cell = worksheet.cell(row=header_row, column=col)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)

    # Style totals (last data row)
    last_row = worksheet.max_row
    if last_row > header_row + 1:
        for col in range(1, header_col_count + 1):
            cell = worksheet.cell(row=last_row, column=col)
            cell.fill = TOTAL_FILL
            cell.font = Font(bold=True)

    # Currency formatting
    if currency_cols:
        for row in range(header_row + 1, last_row + 1):
            for col in currency_cols:
                worksheet.cell(row=row, column=col).number_format = '#,##0.00'

    # Column widths
    if col_widths:
        for col_letter, width in col_widths.items():
            worksheet.column_dimensions[col_letter].width = width


# ---------------------------------------------------------------------------
# PAR Aging
# ---------------------------------------------------------------------------

def export_par_aging_excel(context):
    """Export PAR Aging Report to Excel."""
    output = BytesIO()
    writer = pd.ExcelWriter(output, engine='openpyxl')

    bucket_labels = {
        'current':  'Current (0 days)',
        'par_1_30': 'PAR 1-30 days',
        'par_31_60':'PAR 31-60 days',
        'par_61_90':'PAR 61-90 days',
        'par_90plus':'PAR 90+ days',
    }

    rows = []
    for key, label in bucket_labels.items():
        s = context['summary'][key]
        rows.append({
            'Bucket': label,
            'No. of Loans': s['count'],
            'Outstanding Balance (₦)': float(s['balance']),
            '% of Portfolio': s['pct'],
        })

    df_summary = pd.DataFrame(rows)
    totals = pd.DataFrame([{
        'Bucket': 'TOTAL',
        'No. of Loans': context['total_count'],
        'Outstanding Balance (₦)': float(context['total_balance']),
        '% of Portfolio': 100.0,
    }])
    df_summary = pd.concat([df_summary, totals], ignore_index=True)
    df_summary.to_excel(writer, sheet_name='Summary', index=False)

    # Loan detail sheet
    detail_rows = []
    for key, label in bucket_labels.items():
        for loan, days in context['summary'][key]['items']:
            detail_rows.append({
                'Bucket': label,
                'Loan No.': loan.loan_number,
                'Client': loan.client.get_full_name(),
                'Branch': loan.branch.name if loan.branch else '',
                'Product': loan.loan_product.name if loan.loan_product else '',
                'Outstanding Balance (₦)': float(loan.outstanding_balance),
                'Days Overdue': days,
            })

    df_detail = pd.DataFrame(detail_rows) if detail_rows else pd.DataFrame(
        columns=['Bucket','Loan No.','Client','Branch','Product','Outstanding Balance (₦)','Days Overdue'])
    df_detail.to_excel(writer, sheet_name='Loan Detail', index=False)

    _style_sheet(writer.sheets['Summary'], 4,
                 title='PORTFOLIO AT RISK (PAR) AGING REPORT',
                 subtitle=f'As of {context["today"].strftime("%B %d, %Y")}',
                 currency_cols=[3], col_widths={'A':22,'B':16,'C':25,'D':18})
    _style_sheet(writer.sheets['Loan Detail'], 7,
                 currency_cols=[6], col_widths={'A':22,'B':18,'C':30,'D':20,'E':25,'F':25,'G':14})

    writer.close()
    output.seek(0)
    response = create_excel_response(f'par_aging_{context["today"].strftime("%Y%m%d")}.xlsx')
    response.write(output.read())
    return response


# ---------------------------------------------------------------------------
# Loan Officer Performance
# ---------------------------------------------------------------------------

def export_loan_officer_performance_excel(context):
    """Export Loan Officer Performance Report to Excel."""
    output = BytesIO()
    writer = pd.ExcelWriter(output, engine='openpyxl')

    rows = []
    for r in context['officers']:
        rows.append({
            'Officer': r['officer'].get_full_name(),
            'Branch': r['officer'].branch.name if r['officer'].branch else '',
            'Loans Disbursed': r['disbursed_count'],
            'Disbursed Amount (₦)': float(r['disbursed_amount']),
            'Repayments': r['repayment_count'],
            'Repayment Amount (₦)': float(r['repayment_amount']),
            'Active Clients': r['active_clients'],
            'Active Loans': r['active_loans'],
            'Overdue Loans': r['overdue_loans'],
        })

    totals = context['totals']
    rows.append({
        'Officer': 'TOTAL',
        'Branch': '',
        'Loans Disbursed': totals['disbursed_count'],
        'Disbursed Amount (₦)': float(totals['disbursed_amount']),
        'Repayments': totals['repayment_count'],
        'Repayment Amount (₦)': float(totals['repayment_amount']),
        'Active Clients': totals['active_clients'],
        'Active Loans': totals['active_loans'],
        'Overdue Loans': totals['overdue_loans'],
    })

    df = pd.DataFrame(rows)
    df.to_excel(writer, sheet_name='Performance', index=False)
    _style_sheet(writer.sheets['Performance'], 9,
                 title='LOAN OFFICER PERFORMANCE REPORT',
                 subtitle=f'Period: {context["date_from"]} to {context["date_to"]}',
                 currency_cols=[4, 6],
                 col_widths={'A':28,'B':20,'C':16,'D':22,'E':14,'F':22,'G':16,'H':14,'I':16})

    writer.close()
    output.seek(0)
    response = create_excel_response(f'loan_officer_performance_{context["date_from"]}_{context["date_to"]}.xlsx')
    response.write(output.read())
    return response


# ---------------------------------------------------------------------------
# Savings Maturity
# ---------------------------------------------------------------------------

def export_savings_maturity_excel(context):
    """Export Savings Maturity Report to Excel."""
    output = BytesIO()
    writer = pd.ExcelWriter(output, engine='openpyxl')

    def _rows(accounts):
        return [{
            'Account No.': r['account'].account_number,
            'Client': r['account'].client.get_full_name(),
            'Branch': r['account'].branch.name if r['account'].branch else '',
            'Product': r['account'].savings_product.name,
            'Balance (₦)': float(r['account'].balance),
            'Maturity Date': r['account'].maturity_date.strftime('%Y-%m-%d') if r['account'].maturity_date else '',
            'Days Remaining': r['days_left'],
        } for r in accounts]

    cols = ['Account No.','Client','Branch','Product','Balance (₦)','Maturity Date','Days Remaining']

    for label, data in [('Overdue', context['overdue']),
                        ('This Month', context['this_month']),
                        ('Next Month', context['next_month']),
                        ('Later', context['later'])]:
        df = pd.DataFrame(_rows(data)) if data else pd.DataFrame(columns=cols)
        df.to_excel(writer, sheet_name=label, index=False)
        _style_sheet(writer.sheets[label], 7,
                     currency_cols=[5],
                     col_widths={'A':18,'B':28,'C':18,'D':28,'E':18,'F':14,'G':16})

    writer.close()
    output.seek(0)
    response = create_excel_response(f'savings_maturity_{context["today"].strftime("%Y%m%d")}.xlsx')
    response.write(output.read())
    return response


# ---------------------------------------------------------------------------
# Loan Repayments — Principal vs Interest
# ---------------------------------------------------------------------------

def export_loan_repayments_excel(repayments_qs, context):
    """
    Export Loan Repayments Report to Excel.

    `repayments_qs` is the full (uncapped) filtered queryset — the on-screen
    table is capped for performance, but the export always contains every
    matching repayment.
    """
    output = BytesIO()
    writer = pd.ExcelWriter(output, engine='openpyxl')

    rows = []
    for txn in repayments_qs:
        rows.append({
            'Date': timezone.localtime(txn.transaction_date).strftime('%Y-%m-%d'),
            'Txn Ref': txn.transaction_ref,
            'Loan No.': txn.loan.loan_number if txn.loan else '',
            'Client': txn.client.get_full_name() if txn.client else '',
            'Branch': txn.branch.name if txn.branch else '',
            'Amount (₦)': float(txn.amount),
            'Principal (₦)': float(txn.principal_amount or 0),
            'Interest (₦)': float(txn.interest_amount or 0),
            'Processed By': txn.processed_by.get_full_name() if txn.processed_by else '',
        })

    rows.append({
        'Date': '', 'Txn Ref': '', 'Loan No.': '', 'Client': '', 'Branch': 'TOTAL',
        'Amount (₦)': float(context['total_amount']),
        'Principal (₦)': float(context['total_principal']),
        'Interest (₦)': float(context['total_interest']),
        'Processed By': '',
    })

    cols = ['Date','Txn Ref','Loan No.','Client','Branch','Amount (₦)','Principal (₦)','Interest (₦)','Processed By']
    df = pd.DataFrame(rows) if rows else pd.DataFrame(columns=cols)
    df.to_excel(writer, sheet_name='Loan Repayments', index=False)

    _style_sheet(writer.sheets['Loan Repayments'], 9,
                 title='LOAN REPAYMENTS — PRINCIPAL VS INTEREST',
                 subtitle=f'Period: {context["date_from"]} to {context["date_to"]}  |  {context["count"]} repayment(s)',
                 currency_cols=[6, 7, 8],
                 col_widths={'A':14,'B':24,'C':22,'D':26,'E':18,'F':16,'G':16,'H':16,'I':22})

    writer.close()
    output.seek(0)
    response = create_excel_response(f'loan_repayments_{context["date_from"]}_{context["date_to"]}.xlsx')
    response.write(output.read())
    return response


# ---------------------------------------------------------------------------
# Client Transactions (detail page tab)
# ---------------------------------------------------------------------------

def export_client_transactions_excel(client, transactions):
    """Export all transactions for a client (client detail → Transactions tab)."""
    output = BytesIO()
    writer = pd.ExcelWriter(output, engine='openpyxl')

    rows = []
    for t in transactions:
        rows.append({
            'Date': t.transaction_date.strftime('%Y-%m-%d %H:%M') if hasattr(t.transaction_date, 'strftime') else str(t.transaction_date),
            'Reference': t.transaction_ref or '',
            'Type': t.get_transaction_type_display(),
            'Description': t.description or '',
            'Amount (₦)': float(t.amount),
            'Status': t.get_status_display() if hasattr(t, 'get_status_display') else t.status,
            'Processed By': t.processed_by.get_full_name() if t.processed_by else '',
        })

    df = pd.DataFrame(rows) if rows else pd.DataFrame(
        columns=['Date','Reference','Type','Description','Amount (₦)','Status','Processed By'])
    df.to_excel(writer, sheet_name='Transactions', index=False)
    _style_sheet(writer.sheets['Transactions'], 7,
                 title=f'TRANSACTIONS — {client.get_full_name()} ({client.client_id})',
                 currency_cols=[5],
                 col_widths={'A':20,'B':20,'C':22,'D':40,'E':18,'F':14,'G':24})

    writer.close()
    output.seek(0)
    response = create_excel_response(f'transactions_{client.client_id}_{datetime.now().strftime("%Y%m%d")}.xlsx')
    response.write(output.read())
    return response


# ---------------------------------------------------------------------------
# Client Statement
# ---------------------------------------------------------------------------

def export_client_statement_excel(client, transactions, date_from, date_to,
                                   total_in, total_out, net_position):
    """Export client account statement to Excel."""
    output = BytesIO()
    writer = pd.ExcelWriter(output, engine='openpyxl')

    _OUTFLOW = {'loan_disbursement', 'withdrawal'}

    rows = []
    for t in transactions:
        # Reversed transactions (e.g. a duplicate corrected after the fact)
        # stay in the export for the audit trail but are flagged and don't
        # count toward Money In/Out, matching the on-screen statement.
        is_reversed = t.status == 'reversed'
        rows.append({
            'Date': t.transaction_date.strftime('%Y-%m-%d') if hasattr(t.transaction_date, 'strftime') else str(t.transaction_date),
            'Reference': t.transaction_ref or '',
            'Type': t.get_transaction_type_display(),
            'Description': t.description or '',
            'Status': 'Reversed' if is_reversed else '',
            'Money In (₦)': 0.0 if is_reversed else (float(t.amount) if t.transaction_type not in _OUTFLOW else 0.0),
            'Money Out (₦)': 0.0 if is_reversed else (float(t.amount) if t.transaction_type in _OUTFLOW else 0.0),
        })

    # Summary rows
    rows.append({'Date':'','Reference':'','Type':'','Description':'TOTAL IN','Status':'','Money In (₦)':float(total_in),'Money Out (₦)':''})
    rows.append({'Date':'','Reference':'','Type':'','Description':'TOTAL OUT','Status':'','Money In (₦)':'','Money Out (₦)':float(total_out)})
    rows.append({'Date':'','Reference':'','Type':'','Description':'NET POSITION','Status':'','Money In (₦)':float(net_position),'Money Out (₦)':''})

    df = pd.DataFrame(rows)
    df.to_excel(writer, sheet_name='Statement', index=False)

    date_range = f'{date_from.strftime("%B %d, %Y")} to {date_to.strftime("%B %d, %Y")}'
    _style_sheet(writer.sheets['Statement'], 7,
                 title=f'ACCOUNT STATEMENT — {client.get_full_name()} ({client.client_id})',
                 subtitle=f'Period: {date_range}',
                 currency_cols=[6, 7],
                 col_widths={'A':14,'B':20,'C':22,'D':40,'E':12,'F':18,'G':18})

    writer.close()
    output.seek(0)
    response = create_excel_response(f'statement_{client.client_id}_{date_from.strftime("%Y%m%d")}_{date_to.strftime("%Y%m%d")}.xlsx')
    response.write(output.read())
    return response


# ---------------------------------------------------------------------------
# Subsidiary Ledger
# ---------------------------------------------------------------------------

def export_subsidiary_ledger_excel(client, lines_qs, date_from, date_to,
                                    account_summary, totals):
    """Export subsidiary ledger to Excel."""
    output = BytesIO()
    writer = pd.ExcelWriter(output, engine='openpyxl')

    # Detail sheet
    rows = []
    for line in lines_qs:
        je = line.journal_entry
        rows.append({
            'Date': je.transaction_date.strftime('%Y-%m-%d'),
            'Journal No.': je.journal_number,
            'GL Code': line.account.gl_code,
            'Account': line.account.account_name,
            'Description': line.description or je.description or '',
            'Debit (₦)': float(line.debit_amount) if line.debit_amount else 0.0,
            'Credit (₦)': float(line.credit_amount) if line.credit_amount else 0.0,
            'Branch': je.branch.name if je.branch else '',
        })

    df = pd.DataFrame(rows) if rows else pd.DataFrame(
        columns=['Date','Journal No.','GL Code','Account','Description','Debit (₦)','Credit (₦)','Branch'])
    df.to_excel(writer, sheet_name='Ledger Lines', index=False)
    _style_sheet(writer.sheets['Ledger Lines'], 8,
                 title=f'SUBSIDIARY LEDGER — {client.get_full_name()} ({client.client_id})',
                 subtitle=f'Period: {date_from.strftime("%B %d, %Y")} to {date_to.strftime("%B %d, %Y")}',
                 currency_cols=[6, 7],
                 col_widths={'A':14,'B':18,'C':10,'D':30,'E':40,'F':16,'G':16,'H':18})

    # Account summary sheet
    summary_rows = [{
        'GL Code': s['account__gl_code'],
        'Account': s['account__account_name'],
        'Total Debit (₦)': float(s['total_debit'] or 0),
        'Total Credit (₦)': float(s['total_credit'] or 0),
    } for s in account_summary]
    if totals:
        summary_rows.append({
            'GL Code': '', 'Account': 'GRAND TOTAL',
            'Total Debit (₦)': float(totals.get('total_debit') or 0),
            'Total Credit (₦)': float(totals.get('total_credit') or 0),
        })

    df_sum = pd.DataFrame(summary_rows) if summary_rows else pd.DataFrame(
        columns=['GL Code','Account','Total Debit (₦)','Total Credit (₦)'])
    df_sum.to_excel(writer, sheet_name='Account Summary', index=False)
    _style_sheet(writer.sheets['Account Summary'], 4,
                 currency_cols=[3, 4],
                 col_widths={'A':12,'B':35,'C':20,'D':20})

    writer.close()
    output.seek(0)
    response = create_excel_response(f'subsidiary_ledger_{client.client_id}_{date_from.strftime("%Y%m%d")}_{date_to.strftime("%Y%m%d")}.xlsx')
    response.write(output.read())
    return response


# ---------------------------------------------------------------------------
# Client List
# ---------------------------------------------------------------------------

def export_client_list_excel(clients_qs):
    """Export full client list with all key details to Excel."""
    output = BytesIO()
    writer = pd.ExcelWriter(output, engine='openpyxl')

    rows = []
    for c in clients_qs.select_related('branch', 'assigned_staff', 'group'):
        rows.append({
            'Client ID': c.client_id,
            'First Name': c.first_name,
            'Last Name': c.last_name,
            'Gender': c.get_gender_display() if hasattr(c, 'get_gender_display') else (c.gender or ''),
            'Date of Birth': c.date_of_birth.strftime('%Y-%m-%d') if c.date_of_birth else '',
            'Phone': c.phone or '',
            'Alternate Phone': c.alternate_phone or '',
            'Email': c.email or '',
            'Address': c.address or '',
            'City': c.city or '',
            'State': c.state or '',
            'Branch': c.branch.name if c.branch else '',
            'Assigned Staff': c.assigned_staff.get_full_name() if c.assigned_staff else '',
            'Group': c.group.name if c.group else '',
            'Group Role': c.get_group_role_display() if c.group_role else '',
            'Occupation': c.occupation or '',
            'Business Name': c.business_name or '',
            'Monthly Income (₦)': float(c.monthly_income) if c.monthly_income else '',
            'ID Type': c.get_id_type_display() if c.id_type else '',
            'ID Number': c.id_number or '',
            'BVN': c.bvn or '',
            'Bank Name': c.bank_name or '',
            'Account Number': c.account_number or '',
            'Status': 'Active' if c.is_active else 'Inactive',
            'Approval Status': c.get_approval_status_display() if hasattr(c, 'get_approval_status_display') else (c.approval_status or ''),
            'Date Joined': c.created_at.strftime('%Y-%m-%d') if c.created_at else '',
        })

    df = pd.DataFrame(rows) if rows else pd.DataFrame()
    df.to_excel(writer, sheet_name='Clients', index=False)
    _style_sheet(writer.sheets['Clients'], 26,
                 title='CLIENT LIST — SEASHORE MICROFINANCE',
                 subtitle=f'Exported on {datetime.now().strftime("%B %d, %Y at %H:%M")}',
                 currency_cols=[18],
                 col_widths={
                    'A':14,'B':18,'C':18,'D':10,'E':14,'F':16,'G':16,'H':28,
                    'I':35,'J':16,'K':16,'L':20,'M':24,'N':20,'O':14,'P':20,
                    'Q':25,'R':18,'S':14,'T':20,'U':16,'V':18,'W':18,'X':12,
                    'Y':18,'Z':14,
                 })

    writer.close()
    output.seek(0)
    response = create_excel_response(f'clients_{datetime.now().strftime("%Y%m%d_%H%M%S")}.xlsx')
    response.write(output.read())
    return response


# ---------------------------------------------------------------------------
# Savings Transactions
# ---------------------------------------------------------------------------

def export_savings_transactions_excel(postings):
    """Export savings deposit/withdrawal postings to Excel."""
    output = BytesIO()
    writer = pd.ExcelWriter(output, engine='openpyxl')

    rows = []
    for p in postings:
        is_deposit = hasattr(p, 'deposit_ref') or p.__class__.__name__ == 'SavingsDepositPosting'
        rows.append({
            'Date': p.submitted_at.strftime('%Y-%m-%d %H:%M') if p.submitted_at else '',
            'Reference': getattr(p, 'deposit_ref', None) or getattr(p, 'withdrawal_ref', '') or '',
            'Type': 'Deposit' if is_deposit else 'Withdrawal',
            'Client': p.client.get_full_name() if p.client else '',
            'Account No.': p.savings_account.account_number if p.savings_account else '',
            'Amount (₦)': float(p.amount),
            'Branch': p.branch.name if p.branch else '',
            'Status': p.get_status_display() if hasattr(p, 'get_status_display') else p.status,
            'Submitted By': p.submitted_by.get_full_name() if p.submitted_by else '',
            'Reviewed By': p.reviewed_by.get_full_name() if p.reviewed_by else '',
        })

    df = pd.DataFrame(rows) if rows else pd.DataFrame(
        columns=['Date','Reference','Type','Client','Account No.','Amount (₦)',
                 'Branch','Status','Submitted By','Reviewed By'])
    df.to_excel(writer, sheet_name='Transactions', index=False)
    _style_sheet(writer.sheets['Transactions'], 10,
                 title='SAVINGS TRANSACTIONS',
                 subtitle=f'Exported on {datetime.now().strftime("%B %d, %Y at %H:%M")}',
                 currency_cols=[6],
                 col_widths={'A':20,'B':20,'C':12,'D':28,'E':18,'F':18,
                             'G':18,'H':14,'I':24,'J':24})

    writer.close()
    output.seek(0)
    response = create_excel_response(f'savings_transactions_{datetime.now().strftime("%Y%m%d_%H%M%S")}.xlsx')
    response.write(output.read())
    return response


# ---------------------------------------------------------------------------
# Staff Reports
# ---------------------------------------------------------------------------

def export_loan_report_excel(context):
    """Export the Loan Report (per-staff NOL/Principal/Interest/Outstanding) to Excel."""
    output = BytesIO()
    writer = pd.ExcelWriter(output, engine='openpyxl')

    rows = []
    for r in context['rows']:
        rows.append({
            'Officer': r['officer'].get_full_name(),
            'Branch': r['officer'].branch.name if r['officer'].branch else '',
            'No. of Loans': r['nol'],
            'Principal (₦)': float(r['principal']),
            'Interest (₦)': float(r['interest']),
            'Outstanding (₦)': float(r['outstanding']),
            'Active': r['active'],
            'Overdue': r['overdue'],
            'Completed': r['completed'],
        })
    totals = context['totals']
    rows.append({
        'Officer': 'TOTAL', 'Branch': '',
        'No. of Loans': totals['nol'],
        'Principal (₦)': float(totals['principal']),
        'Interest (₦)': float(totals['interest']),
        'Outstanding (₦)': float(totals['outstanding']),
        'Active': totals['active'], 'Overdue': totals['overdue'], 'Completed': totals['completed'],
    })

    df = pd.DataFrame(rows)
    df.to_excel(writer, sheet_name='Loan Report', index=False)
    _style_sheet(writer.sheets['Loan Report'], 9,
                 title='LOAN REPORT',
                 subtitle=f'Period: {context["date_from"]} to {context["date_to"]}',
                 currency_cols=[4, 5, 6],
                 col_widths={'A':28,'B':18,'C':14,'D':18,'E':16,'F':18,'G':10,'H':10,'I':12})

    writer.close()
    output.seek(0)
    response = create_excel_response(f'loan_report_{context["date_from"]}_{context["date_to"]}.xlsx')
    response.write(output.read())
    return response


def export_staff_savings_portfolio_excel(context):
    """Export the Staff Savings Portfolio report to Excel."""
    output = BytesIO()
    writer = pd.ExcelWriter(output, engine='openpyxl')

    labels = [label for _key, label in context['categories']]
    rows = []
    for r in context['rows']:
        row = {'Officer': r['officer'].get_full_name(),
               'Branch': r['officer'].branch.name if r['officer'].branch else ''}
        for key, label in context['categories']:
            row[f'{label} (₦)'] = float(r['by_category'][key]['balance'])
        row['Total Accounts'] = r['total_accounts']
        row['Total Balance (₦)'] = float(r['total_balance'])
        rows.append(row)

    totals = context['totals']
    total_row = {'Officer': 'TOTAL', 'Branch': ''}
    for key, label in context['categories']:
        total_row[f'{label} (₦)'] = float(totals['by_category'][key]['balance'])
    total_row['Total Accounts'] = totals['total_accounts']
    total_row['Total Balance (₦)'] = float(totals['total_balance'])
    rows.append(total_row)

    ncols = 2 + len(labels) + 2
    currency_cols = list(range(3, 3 + len(labels))) + [ncols]

    df = pd.DataFrame(rows)
    df.to_excel(writer, sheet_name='Savings Portfolio', index=False)
    _style_sheet(writer.sheets['Savings Portfolio'], ncols,
                 title='STAFF SAVINGS PORTFOLIO',
                 subtitle=f'Period: {context["date_from"]} to {context["date_to"]}',
                 currency_cols=currency_cols,
                 col_widths={'A':28,'B':18})

    writer.close()
    output.seek(0)
    response = create_excel_response(f'staff_savings_portfolio_{context["date_from"]}_{context["date_to"]}.xlsx')
    response.write(output.read())
    return response


def export_disbursement_report_excel(context):
    """Export the Disbursement Report (loan volume + client reach) to Excel."""
    output = BytesIO()
    writer = pd.ExcelWriter(output, engine='openpyxl')

    rows = []
    for r in context['rows']:
        rows.append({
            'Officer': r['officer'].get_full_name(),
            'Branch': r['officer'].branch.name if r['officer'].branch else '',
            'Loans Disbursed': r['loans_disbursed'],
            'Principal Disbursed (₦)': float(r['principal_disbursed']),
            'Distinct Clients Disbursed': r['clients_disbursed'],
        })
    totals = context['totals']
    rows.append({
        'Officer': 'TOTAL', 'Branch': '',
        'Loans Disbursed': totals['loans_disbursed'],
        'Principal Disbursed (₦)': float(totals['principal_disbursed']),
        'Distinct Clients Disbursed': totals['clients_disbursed'],
    })

    df = pd.DataFrame(rows)
    df.to_excel(writer, sheet_name='Disbursement', index=False)
    _style_sheet(writer.sheets['Disbursement'], 5,
                 title='DISBURSEMENT REPORT',
                 subtitle=f'Period: {context["date_from"]} to {context["date_to"]}',
                 currency_cols=[4],
                 col_widths={'A':28,'B':18,'C':16,'D':22,'E':22})

    writer.close()
    output.seek(0)
    response = create_excel_response(f'disbursement_report_{context["date_from"]}_{context["date_to"]}.xlsx')
    response.write(output.read())
    return response


def export_registration_report_excel(context):
    """Export the Registration Report to Excel."""
    output = BytesIO()
    writer = pd.ExcelWriter(output, engine='openpyxl')

    rows = []
    for r in context['rows']:
        rows.append({
            'Officer': r['officer'].get_full_name(),
            'Branch': r['officer'].branch.name if r['officer'].branch else '',
            'Total Registered': r['total'],
            'Approved': r['approved'],
            'Pending': r['pending'],
            'Rejected': r['rejected'],
        })
    totals = context['totals']
    rows.append({
        'Officer': 'TOTAL', 'Branch': '',
        'Total Registered': totals['total'], 'Approved': totals['approved'],
        'Pending': totals['pending'], 'Rejected': totals['rejected'],
    })

    df = pd.DataFrame(rows)
    df.to_excel(writer, sheet_name='Registration', index=False)
    _style_sheet(writer.sheets['Registration'], 6,
                 title='REGISTRATION REPORT',
                 subtitle=f'Period: {context["date_from"]} to {context["date_to"]}',
                 col_widths={'A':28,'B':18,'C':16,'D':12,'E':12,'F':12})

    writer.close()
    output.seek(0)
    response = create_excel_response(f'registration_report_{context["date_from"]}_{context["date_to"]}.xlsx')
    response.write(output.read())
    return response


def export_unions_report_excel(context):
    """Export the Unions (ClientGroup) Report to Excel."""
    output = BytesIO()
    writer = pd.ExcelWriter(output, engine='openpyxl')

    rows = []
    for g in context['groups']:
        rows.append({
            'Union': g.name,
            'Branch': g.branch.name if g.branch else '',
            'Loan Officer': g.loan_officer.get_full_name() if g.loan_officer else '',
            'Active Members': g.active_members,
            'Total Members': g.total_members,
            'Total Savings (₦)': float(g.total_savings or 0),
            'Total Loans Outstanding (₦)': float(g.total_loans_outstanding or 0),
            'Status': g.get_status_display(),
            'Registered': g.registration_date.strftime('%Y-%m-%d') if g.registration_date else '',
        })
    totals = context['totals']
    rows.append({
        'Union': 'TOTAL', 'Branch': '', 'Loan Officer': '',
        'Active Members': totals['active_members'] or 0,
        'Total Members': totals['total_members'] or 0,
        'Total Savings (₦)': float(totals['total_savings'] or 0),
        'Total Loans Outstanding (₦)': float(totals['total_loans_outstanding'] or 0),
        'Status': '', 'Registered': '',
    })

    df = pd.DataFrame(rows)
    df.to_excel(writer, sheet_name='Unions', index=False)
    _style_sheet(writer.sheets['Unions'], 9,
                 title='UNIONS REPORT',
                 subtitle=f'Period: {context["date_from"]} to {context["date_to"]}',
                 currency_cols=[6, 7],
                 col_widths={'A':26,'B':18,'C':22,'D':14,'E':14,'F':18,'G':22,'H':14,'I':14})

    writer.close()
    output.seek(0)
    response = create_excel_response(f'unions_report_{context["date_from"]}_{context["date_to"]}.xlsx')
    response.write(output.read())
    return response


def export_overdue_by_staff_excel(context):
    """Export the staff-filterable Overdue Report to Excel."""
    output = BytesIO()
    writer = pd.ExcelWriter(output, engine='openpyxl')

    rows = []
    for r in context['rows']:
        b = r['buckets']
        rows.append({
            'Officer': r['officer'].get_full_name(),
            'Branch': r['officer'].branch.name if r['officer'].branch else '',
            'Current': b['current'],
            'PAR 1-30': b['par_1_30'],
            'PAR 31-60': b['par_31_60'],
            'PAR 61-90': b['par_61_90'],
            'PAR 90+': b['par_90plus'],
            'Total Overdue': r['total_count'],
            'Outstanding (₦)': float(r['outstanding']),
        })
    totals = context['totals']
    tb = totals['buckets']
    rows.append({
        'Officer': 'TOTAL', 'Branch': '',
        'Current': tb['current'], 'PAR 1-30': tb['par_1_30'], 'PAR 31-60': tb['par_31_60'],
        'PAR 61-90': tb['par_61_90'], 'PAR 90+': tb['par_90plus'],
        'Total Overdue': totals['total_count'], 'Outstanding (₦)': float(totals['outstanding']),
    })

    df = pd.DataFrame(rows)
    df.to_excel(writer, sheet_name='Overdue', index=False)
    _style_sheet(writer.sheets['Overdue'], 9,
                 title='OVERDUE REPORT',
                 subtitle=f'Due {context["date_from"]} to {context["date_to"]}',
                 currency_cols=[9],
                 col_widths={'A':28,'B':18,'C':10,'D':10,'E':10,'F':10,'G':10,'H':14,'I':18})

    writer.close()
    output.seek(0)
    response = create_excel_response(f'overdue_report_{context["date_from"]}_{context["date_to"]}.xlsx')
    response.write(output.read())
    return response


def export_officer_snapshot_excel(context):
    """Export the Officer Snapshot (at-a-glance per-officer summary) to Excel."""
    output = BytesIO()
    writer = pd.ExcelWriter(output, engine='openpyxl')

    rows = []
    for r in context['rows']:
        rows.append({
            'Officer': r['officer'].get_full_name(),
            'Role': r['officer'].get_user_role_display(),
            'Branch': r['officer'].branch.name if r['officer'].branch else '',
            'Loan Portfolio (₦)': float(r['loan_portfolio']),
            'Savers': r['savers'],
            'Clients': r['clients'],
            'Loans': r['loans'],
            'Overdue Loans': r['overdue_loans'],
            'Overdue (₦)': float(r['overdue_amount']),
            'Savings Portfolio (₦)': float(r['savings_portfolio']),
        })
    t = context['totals']
    rows.append({
        'Officer': 'TOTAL', 'Role': '', 'Branch': '',
        'Loan Portfolio (₦)': float(t['loan_portfolio']),
        'Savers': t['savers'], 'Clients': t['clients'], 'Loans': t['loans'],
        'Overdue Loans': t['overdue_loans'], 'Overdue (₦)': float(t['overdue_amount']),
        'Savings Portfolio (₦)': float(t['savings_portfolio']),
    })

    df = pd.DataFrame(rows)
    df.to_excel(writer, sheet_name='Officer Snapshot', index=False)
    _style_sheet(writer.sheets['Officer Snapshot'], 10,
                 title='OFFICER SNAPSHOT',
                 subtitle=f'As of {context["today"]}',
                 currency_cols=[4, 9, 10],
                 col_widths={'A':28,'B':12,'C':22,'D':20,'E':10,'F':10,'G':10,'H':14,'I':18,'J':22})

    writer.close()
    output.seek(0)
    response = create_excel_response(f'officer_snapshot_{context["today"]}.xlsx')
    response.write(output.read())
    return response


# ---------------------------------------------------------------------------
# Loan List (full register export)
# ---------------------------------------------------------------------------

def _loan_arrears_by_loan_id(loan_ids):
    """
    One query, not N+1: for every loan in loan_ids, sum up its overdue-and-
    unpaid installments (due_date in the past, not paid/waived, still owing)
    and bucket the total by how many days overdue the OLDEST such
    installment is. Mirrors the methodology already used by
    report_par_aging / the one-off aging report, just with finer buckets.

    Returns {loan_id: {'oldest_due': date, 'principal': Decimal,
                        'total': Decimal, 'days': int}}
    """
    from core.models import LoanRepaymentSchedule
    from collections import defaultdict

    today = timezone.now().date()
    rows = LoanRepaymentSchedule.objects.filter(
        loan_id__in=loan_ids,
        due_date__lt=today,
        outstanding_amount__gt=0,
    ).exclude(status__in=['paid', 'waived']).values(
        'loan_id', 'due_date', 'principal_amount', 'outstanding_amount'
    )

    agg = defaultdict(lambda: {'oldest_due': None, 'principal': Decimal('0.00'), 'total': Decimal('0.00')})
    for r in rows:
        a = agg[r['loan_id']]
        a['principal'] += r['principal_amount']
        a['total'] += r['outstanding_amount']
        if a['oldest_due'] is None or r['due_date'] < a['oldest_due']:
            a['oldest_due'] = r['due_date']

    result = {}
    for loan_id, a in agg.items():
        days = (today - a['oldest_due']).days if a['oldest_due'] else 0
        result[loan_id] = {**a, 'days': days}
    return result


def _arrears_bucket(days, amount):
    """Return (b_1_30, b_31_60, b_61_90, b_91_180, b_181_360) with `amount`
    placed in whichever single bucket matches `days`, zero elsewhere."""
    buckets = [Decimal('0.00')] * 5
    if days <= 0:
        return tuple(buckets)
    ranges = [(1, 30), (31, 60), (61, 90), (91, 180), (181, 360)]
    for i, (lo, hi) in enumerate(ranges):
        if lo <= days <= hi:
            buckets[i] = amount
            break
    return tuple(buckets)


def export_loan_list_excel(loans_qs):
    """Export the full loan list (respecting whatever filters were applied)
    to Excel — every vital field, not just what fits in the on-screen table,
    plus the standard loan aging/arrears schedule columns."""
    output = BytesIO()
    writer = pd.ExcelWriter(output, engine='openpyxl')

    loans = list(loans_qs.select_related('client', 'branch', 'loan_product', 'client__assigned_staff', 'created_by'))
    arrears = _loan_arrears_by_loan_id([l.id for l in loans])

    rows = []
    for l in loans:
        a = arrears.get(l.id, {})
        overdue_principal = a.get('principal', Decimal('0.00'))
        total_overdue = a.get('total', Decimal('0.00'))
        days_in_arrears = a.get('days', 0)
        b1, b2, b3, b4, b5 = _arrears_bucket(days_in_arrears, total_overdue)
        rows.append({
            'Loan Number': l.loan_number,
            'Client ID': l.client.client_id,
            'Client Name': l.client.get_full_name(),
            'Customer name': l.client.get_full_name(),
            'Branch': l.branch.name if l.branch else '',
            'Loan Officer': l.client.assigned_staff.get_full_name() if l.client.assigned_staff else '',
            'Product': l.loan_product.name if l.loan_product else '',
            'Loan product': l.loan_product.name if l.loan_product else '',
            'Status': l.get_status_display(),
            'Principal (₦)': float(l.principal_amount),
            'Amount disbursed (₦)': float(l.amount_disbursed) if l.amount_disbursed else 0,
            'Monthly Interest Rate (%)': float(l.monthly_interest_rate * 100) if l.monthly_interest_rate else 0,
            'Duration (months)': l.duration_months,
            'Total Interest (₦)': float(l.total_interest or 0),
            'Total Repayment (₦)': float(l.total_repayment or 0),
            'Repayment amount (₦)': float(l.total_repayment or 0),
            'Upfront Fees (₦)': float(l.total_upfront_fees or 0),
            'Admin Fee (₦)': float(l.admin_fee or 0),
            'Amount Paid (₦)': float(l.amount_paid or 0),
            'Amount paid already (₦)': float(l.amount_paid or 0),
            'Outstanding Balance (₦)': float(l.outstanding_balance or 0),
            'Overdue (P) (₦)': float(overdue_principal),
            'Total overdue (₦)': float(total_overdue),
            'Balance Default (what has not been paid) (₦)': float(l.outstanding_balance or 0),
            '1 to 30 (₦)': float(b1),
            '31 to 60 (₦)': float(b2),
            '61 to 90 (₦)': float(b3),
            '91 to 180 (₦)': float(b4),
            '181 to 360 (₦)': float(b5),
            'Days in Arrears': days_in_arrears,
            'Purpose': l.purpose or '',
            'Disbursement Method': l.get_disbursement_method_display() if l.disbursement_method else '',
            'Application Date': l.application_date.strftime('%Y-%m-%d') if l.application_date else '',
            'Approval Date': l.approval_date.strftime('%Y-%m-%d') if l.approval_date else '',
            'Disbursement Date': l.disbursement_date.strftime('%Y-%m-%d') if l.disbursement_date else '',
            'Date of disbursement': l.disbursement_date.strftime('%Y-%m-%d') if l.disbursement_date else '',
            'Next Repayment Date': l.next_repayment_date.strftime('%Y-%m-%d') if l.next_repayment_date else '',
            'Final Repayment Date': l.final_repayment_date.strftime('%Y-%m-%d') if l.final_repayment_date else '',
            'Completion Date': l.completion_date.strftime('%Y-%m-%d') if l.completion_date else '',
            'Created By': l.created_by.get_full_name() if l.created_by else '',
        })

    columns = [
        'Loan Number', 'Client ID', 'Client Name', 'Customer name', 'Branch', 'Loan Officer',
        'Product', 'Loan product', 'Status', 'Principal (₦)', 'Amount disbursed (₦)',
        'Monthly Interest Rate (%)', 'Duration (months)', 'Total Interest (₦)',
        'Total Repayment (₦)', 'Repayment amount (₦)', 'Upfront Fees (₦)', 'Admin Fee (₦)',
        'Amount Paid (₦)', 'Amount paid already (₦)', 'Outstanding Balance (₦)',
        'Overdue (P) (₦)', 'Total overdue (₦)', 'Balance Default (what has not been paid) (₦)',
        '1 to 30 (₦)', '31 to 60 (₦)', '61 to 90 (₦)', '91 to 180 (₦)', '181 to 360 (₦)',
        'Days in Arrears', 'Purpose', 'Disbursement Method', 'Application Date',
        'Approval Date', 'Disbursement Date', 'Date of disbursement', 'Next Repayment Date',
        'Final Repayment Date', 'Completion Date', 'Created By',
    ]
    df = pd.DataFrame(rows, columns=columns) if rows else pd.DataFrame(columns=columns)
    df.to_excel(writer, sheet_name='Loans', index=False)
    currency_col_names = [
        'Principal (₦)', 'Amount disbursed (₦)', 'Total Interest (₦)', 'Total Repayment (₦)',
        'Repayment amount (₦)', 'Upfront Fees (₦)', 'Admin Fee (₦)', 'Amount Paid (₦)',
        'Amount paid already (₦)', 'Outstanding Balance (₦)', 'Overdue (P) (₦)',
        'Total overdue (₦)', 'Balance Default (what has not been paid) (₦)',
        '1 to 30 (₦)', '31 to 60 (₦)', '61 to 90 (₦)', '91 to 180 (₦)', '181 to 360 (₦)',
    ]
    currency_cols = [columns.index(c) + 1 for c in currency_col_names]
    from openpyxl.utils import get_column_letter
    col_widths = {
        get_column_letter(i + 1): min(max(len(name) + 2, 12), 42)
        for i, name in enumerate(columns)
    }
    _style_sheet(writer.sheets['Loans'], len(columns),
                 title='LOAN LIST',
                 subtitle=(
                     f'Exported on {datetime.now().strftime("%B %d, %Y at %H:%M")} — '
                     f'{len(rows)} loan{"" if len(rows) == 1 else "s"} — arrears buckets as of '
                     f'{timezone.now().date().strftime("%B %d, %Y")}'
                 ),
                 currency_cols=currency_cols, col_widths=col_widths)

    writer.close()
    output.seek(0)
    response = create_excel_response(f'loans_{datetime.now().strftime("%Y%m%d_%H%M%S")}.xlsx')
    response.write(output.read())
    return response


# ---------------------------------------------------------------------------
# Assignment Request — Affected Clients
# ---------------------------------------------------------------------------

def export_assignment_affected_clients_excel(req):
    """Export every client affected by an AssignmentRequest to Excel —
    the same human-readable detail shown on the review/detail page, not just
    the raw client IDs stored in assignment_data."""
    output = BytesIO()
    writer = pd.ExcelWriter(output, engine='openpyxl')

    rows = []
    for c in req.get_affected_clients().order_by('first_name', 'last_name'):
        rows.append({
            'Client ID': c.client_id,
            'Name': c.get_full_name(),
            'Phone': c.phone or '',
            'Branch': c.branch.name if c.branch else '',
            'Assigned Staff': c.assigned_staff.get_full_name() if c.assigned_staff else '',
            'Group': c.group.name if c.group else '',
            'Status': 'Active' if c.is_active else 'Inactive',
        })

    df = pd.DataFrame(rows) if rows else pd.DataFrame(
        columns=['Client ID', 'Name', 'Phone', 'Branch', 'Assigned Staff', 'Group', 'Status'])
    df.to_excel(writer, sheet_name='Affected Clients', index=False)
    _style_sheet(writer.sheets['Affected Clients'], 7,
                 title=f'ASSIGNMENT REQUEST — {req.get_assignment_type_display().upper()}',
                 subtitle=f'{req.description} — {len(rows)} client{"" if len(rows) == 1 else "s"} — status: {req.get_status_display()}',
                 col_widths={'A': 16, 'B': 24, 'C': 16, 'D': 22, 'E': 22, 'F': 18, 'G': 12})

    writer.close()
    output.seek(0)
    response = create_excel_response(f'assignment_request_{req.id}_clients.xlsx')
    response.write(output.read())
    return response
