"""
Builds the management Excel report pack from the data dict assembled by
core.management.commands.generate_management_report.

Formatting conventions (per the house style for this kind of workbook):
  - Arial throughout.
  - Amber header bands (matches this app's existing exports in excel_export.py).
  - Every total/subtotal is a real SUM() formula over the rows above it, not
    a hardcoded Python value, so the sheet recalculates if a row is edited.
  - Every percentage is a formula (balance / total) formatted as 0.0%, not a
    pre-divided hardcoded fraction.
  - Currency columns use a Naira-prefixed accounting format; zero renders as
    "-".
"""
import datetime
import os
from decimal import Decimal

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

FONT_NAME = 'Arial'
HEADER_FILL = PatternFill(start_color='D97706', end_color='D97706', fill_type='solid')
HEADER_FONT = Font(name=FONT_NAME, bold=True, color='FFFFFF', size=11)
TITLE_FONT = Font(name=FONT_NAME, bold=True, size=14)
SUBTITLE_FONT = Font(name=FONT_NAME, italic=True, size=10, color='555555')
SECTION_FONT = Font(name=FONT_NAME, bold=True, size=12, color='B45309')
NOTE_FONT = Font(name=FONT_NAME, italic=True, size=9, color='555555')
BOLD = Font(name=FONT_NAME, bold=True)
NORMAL = Font(name=FONT_NAME)
TOTAL_FILL = PatternFill(start_color='FEF3C7', end_color='FEF3C7', fill_type='solid')
HIGHLIGHT_FILL = PatternFill(start_color='EFF6FF', end_color='EFF6FF', fill_type='solid')
THIN = Side(style='thin', color='D1D5DB')
BOX = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)

CURRENCY_FMT = '"₦"#,##0;("₦"#,##0);"-"'
PCT_FMT = '0.0%'
INT_FMT = '#,##0'


def _set_col_widths(ws, widths):
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w


def _title(ws, text, row=1, span=6):
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=span)
    cell = ws.cell(row=row, column=1, value=text)
    cell.font = TITLE_FONT


def _subtitle(ws, text, row=2, span=6):
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=span)
    cell = ws.cell(row=row, column=1, value=text)
    cell.font = SUBTITLE_FONT


def _header_row(ws, row, headers, start_col=1):
    for i, h in enumerate(headers, start=start_col):
        cell = ws.cell(row=row, column=i, value=h)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
        cell.border = BOX


def _data_row(ws, row, values, start_col=1, bold=False, fill=None, number_formats=None):
    for i, v in enumerate(values, start=start_col):
        cell = ws.cell(row=row, column=i, value=v)
        cell.font = BOLD if bold else NORMAL
        cell.border = BOX
        if fill:
            cell.fill = fill
        if number_formats and i in number_formats:
            cell.number_format = number_formats[i]


def _note(ws, row, text, span=6):
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=span)
    cell = ws.cell(row=row, column=1, value=text)
    cell.font = NOTE_FONT
    cell.alignment = Alignment(wrap_text=True, vertical='top')


def write_management_report_workbook(report):
    wb = Workbook()
    wb.remove(wb.active)

    cutoff = report['cutoff']
    month_start = report['month_start']
    month_end = report['month_end']
    ytd_start = report['ytd_start']
    today = report['today']
    branches = report['branches']

    _write_cover_sheet(wb, report)
    _write_portfolio_sheet(wb, report)
    _write_customers_savings_sheet(wb, report)
    _write_portfolio_quality_sheet(wb, report)
    _write_operations_sheet(wb, report)
    _write_income_statement_sheet(wb, report)
    _write_balance_sheet_sheet(wb, report)

    out_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'excel_for_management')
    os.makedirs(out_dir, exist_ok=True)
    filename = f"Seashore_Management_Report_{cutoff.strftime('%b%Y')}.xlsx"
    out_path = os.path.join(out_dir, filename)
    wb.save(out_path)
    return out_path


# =============================================================================
# 0. COVER & METHODOLOGY
# =============================================================================

def _write_cover_sheet(wb, report):
    ws = wb.create_sheet('Cover & Notes')
    _set_col_widths(ws, [95])
    r = 1
    cell = ws.cell(row=r, column=1, value='Seashore Microfinance — Management Report'); cell.font = TITLE_FONT
    r += 1
    cell = ws.cell(row=r, column=1, value=f"As at {report['cutoff']:%d %B %Y}  ·  Month covered: {report['month_start']:%B %Y}  ·  YTD from {report['ytd_start']:%d %b %Y}")
    cell.font = SUBTITLE_FONT
    r += 1
    cell = ws.cell(row=r, column=1, value=f"Generated from the live Seashore system on {report['today']:%d %B %Y}.")
    cell.font = SUBTITLE_FONT
    r += 2

    cell = ws.cell(row=r, column=1, value='Contents'); cell.font = SECTION_FONT
    r += 1
    for label in [
        '1. Loan Portfolio by Branch',
        '2. Customers & Savings',
        '3. Portfolio Quality (PAR / Overdue / Recoveries / Write-offs)',
        '4. Loan Operations by Branch',
        '5. Income Statement (Month & YTD)',
        '6-7. Balance Sheet / Financial Position',
    ]:
        ws.cell(row=r, column=1, value='  •  ' + label).font = NORMAL
        r += 1
    r += 1

    cell = ws.cell(row=r, column=1, value='Methodology & Assumptions — please read before using these figures'); cell.font = SECTION_FONT
    r += 1
    notes = [
        "GENERAL LEDGER FIGURES (Loan Portfolio, Savings Balance, Income Statement, Balance Sheet) are "
        "exact as at the stated cutoff date. The ledger is append-only — journal lines are never rewritten "
        "for a past date — so summing posted journal lines up to the cutoff reproduces the true historical "
        "balance regardless of what has happened in the system since.",

        "ACTIVE BORROWER / ACTIVE SAVER COUNTS (sheet 2) are reconstructed from recorded status-change "
        "events: a loan's disbursement date, completion date, or the date its write-off journal entry was "
        "posted; a savings account's opening date and closed_at date. These are discrete recorded events, "
        "so the reconstruction is sound, but it is a best-effort estimate, not a stored historical snapshot.",

        "PORTFOLIO-AT-RISK / OVERDUE FIGURES (sheet 3) CANNOT be reconstructed as at a past cutoff with "
        "this system's data model: the loan repayment schedule's outstanding-amount is a live, continuously "
        "updated balance with no historical snapshot, and days-overdue is computed against today's date. "
        f"These figures are therefore reported AS AT THE REPORT'S GENERATION DATE ({report['today']:%d %B %Y}), "
        f"NOT {report['cutoff']:%d %B %Y} — this is flagged again directly on that sheet. Write-offs and "
        "recoveries on that same sheet ARE exact for the stated month, because they are period flows (things "
        "that happened during the month), not a point-in-time balance.",

        "RECOVERIES (sheet 3) are defined as loan-repayment transactions posted during the month against "
        "loans whose status is (now) 'written off'. There is no dedicated recovery-tracking field in this "
        "system; this is the closest available proxy.",

        "EXPENSE CATEGORIES — Personnel / Administrative / Operating / Head Office (sheet 5) — are mapped "
        "from this system's actual chart-of-accounts categories (Staff Costs, Administrative, Operating "
        "Expenses, Maintenance, Other Expenses, Loan Loss Provisions, Interest Expense). Salaries & Wages "
        "and Salary to Casual are tagged 'Operating Expenses' in the chart of accounts itself but have been "
        "placed under Personnel here, as they are personnel costs in substance. The full account-by-account "
        "mapping is shown in the appendix at the foot of sheet 5. THERE IS NO HEAD OFFICE COST CENTRE "
        "anywhere in this system — every posted transaction is attributed to one of the three operating "
        "branches — so Head Office is always reported as ₦0 / not tracked.",

        "OUTSTANDING BORROWINGS (sheet 6-7) is shown as the balance of GL account 2958 'Overdraft Facility' "
        "— the only account in this chart of accounts resembling external borrowings. There is no dedicated "
        "loans-payable / DFI-borrowings account in the system.",

        "Branches covered: " + ', '.join(b.name for b in report['branches']) + ".",
    ]
    for n in notes:
        ws.cell(row=r, column=1, value=n).alignment = Alignment(wrap_text=True, vertical='top')
        ws.row_dimensions[r].height = 60
        r += 1


# =============================================================================
# 1. LOAN PORTFOLIO BY BRANCH
# =============================================================================

def _write_portfolio_sheet(wb, report):
    ws = wb.create_sheet('1. Loan Portfolio')
    _set_col_widths(ws, [28, 26])
    _title(ws, 'Gross Outstanding Loan Portfolio by Branch', span=2)
    _subtitle(ws, f"As at {report['cutoff']:%d %B %Y} — General Ledger basis (exact)", span=2)

    header_row = 4
    _header_row(ws, header_row, ['Branch', 'Gross Outstanding Principal (₦)'])

    r = header_row + 1
    first_data_row = r
    for row in report['portfolio_by_branch']:
        _data_row(ws, r, [row['branch'], float(row['balance'])], number_formats={2: CURRENCY_FMT})
        r += 1
    last_data_row = r - 1

    total_cell = ws.cell(row=r, column=1, value='TOTAL')
    total_cell.font = BOLD
    total_cell.fill = TOTAL_FILL
    sum_cell = ws.cell(row=r, column=2, value=f'=SUM(B{first_data_row}:B{last_data_row})')
    sum_cell.font = BOLD
    sum_cell.fill = TOTAL_FILL
    sum_cell.number_format = CURRENCY_FMT
    for c in (1, 2):
        ws.cell(row=r, column=c).border = BOX

    _note(ws, r + 2, "Source: Chart-of-accounts loan-receivable control accounts (1810 Loan Receivable - Principal, "
                      "1840 Loan Receivable - MED Clients, 1850 Loan Receivable - Betnaija Clients), summed from "
                      "posted journal entries up to the cutoff date, by branch.", span=2)


# =============================================================================
# 2. CUSTOMERS & SAVINGS
# =============================================================================

def _write_customers_savings_sheet(wb, report):
    ws = wb.create_sheet('2. Customers & Savings')
    _set_col_widths(ws, [26, 20, 18, 16, 24])
    _title(ws, 'Customers & Savings', span=5)
    _subtitle(ws, f"As at {report['cutoff']:%d %B %Y}", span=5)

    header_row = 4
    _header_row(ws, header_row, ['Branch', 'Registered Customers', 'Active Borrowers', 'Active Savers', 'Outstanding Savings Balance (₦)'])

    r = header_row + 1
    first_data_row = r
    for row in report['customers_savings_by_branch']:
        _data_row(ws, r, [
            row['branch'], row['registered_customers'], row['active_borrowers'],
            row['active_savers'], float(row['savings_balance']),
        ], number_formats={2: INT_FMT, 3: INT_FMT, 4: INT_FMT, 5: CURRENCY_FMT})
        r += 1
    last_data_row = r - 1

    ws.cell(row=r, column=1, value='TOTAL').font = BOLD
    ws.cell(row=r, column=1).fill = TOTAL_FILL
    for col, fmt in [(2, INT_FMT), (3, INT_FMT), (4, INT_FMT), (5, CURRENCY_FMT)]:
        letter = get_column_letter(col)
        cell = ws.cell(row=r, column=col, value=f'=SUM({letter}{first_data_row}:{letter}{last_data_row})')
        cell.font = BOLD
        cell.fill = TOTAL_FILL
        cell.number_format = fmt
    for c in range(1, 6):
        ws.cell(row=r, column=c).border = BOX

    _note(ws, r + 2,
          "Registered Customers: cumulative approved clients registered on/before the cutoff. "
          "Active Borrowers / Active Savers: reconstructed as at the cutoff from disbursement/completion/"
          "write-off dates and savings opened/closed dates — see 'Cover & Notes' for the full methodology. "
          "Outstanding Savings Balance: General Ledger savings-deposit control accounts (2010-2050), exact.",
          span=5)


# =============================================================================
# 3. PORTFOLIO QUALITY
# =============================================================================

def _write_portfolio_quality_sheet(wb, report):
    ws = wb.create_sheet('3. Portfolio Quality')
    _set_col_widths(ws, [30, 22, 14, 16])
    _title(ws, 'Portfolio Quality — PAR, Overdue, Recoveries & Write-offs', span=4)

    warn = ws.cell(row=2, column=1,
                    value=f"⚠ Reported AS AT THE REPORT GENERATION DATE ({report['today']:%d %B %Y}), NOT "
                          f"{report['cutoff']:%d %B %Y} — this system has no historical snapshot of loan "
                          f"repayment schedules. See 'Cover & Notes'.")
    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=4)
    warn.font = Font(name=FONT_NAME, bold=True, italic=True, size=10, color='B91C1C')
    ws.row_dimensions[2].height = 28
    warn.alignment = Alignment(wrap_text=True, vertical='top')

    r = 4
    ws.cell(row=r, column=1, value='Total Outstanding Portfolio (live)').font = BOLD
    tp = ws.cell(row=r, column=2, value=float(report['total_outstanding_live']))
    tp.number_format = CURRENCY_FMT
    tp.font = BOLD
    r += 2

    header_row = r
    _header_row(ws, header_row, ['Metric', 'Outstanding Amount (₦)', 'Loan Count', '% of Total Portfolio'])
    r += 1
    par_first_row = r
    for label, key in [('PAR 1 (≥1 day overdue)', 'par1'), ('PAR 30 (≥30 days overdue)', 'par30'), ('PAR 90 (≥90 days overdue)', 'par90')]:
        data = report[key]
        row = r
        ws.cell(row=row, column=1, value=label).border = BOX
        amt_cell = ws.cell(row=row, column=2, value=float(data['balance']))
        amt_cell.number_format = CURRENCY_FMT
        amt_cell.border = BOX
        cnt_cell = ws.cell(row=row, column=3, value=data['count'])
        cnt_cell.number_format = INT_FMT
        cnt_cell.border = BOX
        # % of total portfolio, against the Total Outstanding Portfolio cell (B4)
        pct_cell = ws.cell(row=row, column=4, value=f'=B{row}/$B$4')
        pct_cell.number_format = PCT_FMT
        pct_cell.border = BOX
        r += 1

    ws.cell(row=r, column=1, value='Overdue Loans (= PAR 1 above)').font = Font(name=FONT_NAME, italic=True)
    ws.cell(row=r, column=1).border = BOX
    oc = ws.cell(row=r, column=2, value=f'=B{par_first_row}')
    oc.number_format = CURRENCY_FMT
    oc.border = BOX
    occ = ws.cell(row=r, column=3, value=f'=C{par_first_row}')
    occ.number_format = INT_FMT
    occ.border = BOX
    opc = ws.cell(row=r, column=4, value=f'=D{par_first_row}')
    opc.number_format = PCT_FMT
    opc.border = BOX
    r += 3

    ws.cell(row=r, column=1, value=f"Write-offs & Recoveries — {report['month_start']:%B %Y}").font = SECTION_FONT
    r += 1
    header2 = r
    _header_row(ws, header2, ['Metric', 'Amount (₦)', 'Count', ''])
    r += 1
    ws.cell(row=r, column=1, value='Loans Written Off').border = BOX
    wo = ws.cell(row=r, column=2, value=float(report['writeoff_total'])); wo.number_format = CURRENCY_FMT; wo.border = BOX
    woc = ws.cell(row=r, column=3, value=report['writeoff_count']); woc.number_format = INT_FMT; woc.border = BOX
    ws.cell(row=r, column=4).border = BOX
    r += 1
    ws.cell(row=r, column=1, value='Recoveries on Written-off Loans').border = BOX
    rec = ws.cell(row=r, column=2, value=float(report['recovery_total'])); rec.number_format = CURRENCY_FMT; rec.border = BOX
    recc = ws.cell(row=r, column=3, value=report['recovery_count']); recc.number_format = INT_FMT; recc.border = BOX
    ws.cell(row=r, column=4).border = BOX
    r += 2

    _note(ws, r, "Write-offs: sum of posted 'WRITE-OFF-*' journal entries dated within the month (exact). "
                 "Recoveries: loan-repayment transactions posted within the month against loans currently "
                 "flagged written off (best available proxy — no dedicated recovery field exists). Both are "
                 "period flows and are exact for the stated month regardless of today's date.", span=4)


# =============================================================================
# 4. LOAN OPERATIONS BY BRANCH
# =============================================================================

def _write_operations_sheet(wb, report):
    ws = wb.create_sheet('4. Loan Operations')
    _set_col_widths(ws, [26, 16, 22, 18, 20])
    _title(ws, 'Loan Operations by Branch', span=5)
    _subtitle(ws, f"{report['month_start']:%B %Y} ({report['month_start']:%d %b} – {report['month_end']:%d %b %Y})", span=5)

    header_row = 4
    _header_row(ws, header_row, ['Branch', 'Loans Disbursed', 'Principal Disbursed (₦)', 'Repayments Posted', 'Principal Collected (₦)'])

    r = header_row + 1
    first_data_row = r
    for row in report['operations_by_branch']:
        _data_row(ws, r, [
            row['branch'], row['disbursement_count'], float(row['disbursement_amount']),
            row['repayment_count'], float(row['principal_collected']),
        ], number_formats={2: INT_FMT, 3: CURRENCY_FMT, 4: INT_FMT, 5: CURRENCY_FMT})
        r += 1
    last_data_row = r - 1

    ws.cell(row=r, column=1, value='TOTAL').font = BOLD
    ws.cell(row=r, column=1).fill = TOTAL_FILL
    for col, fmt in [(2, INT_FMT), (3, CURRENCY_FMT), (4, INT_FMT), (5, CURRENCY_FMT)]:
        letter = get_column_letter(col)
        cell = ws.cell(row=r, column=col, value=f'=SUM({letter}{first_data_row}:{letter}{last_data_row})')
        cell.font = BOLD
        cell.fill = TOTAL_FILL
        cell.number_format = fmt
    for c in range(1, 6):
        ws.cell(row=r, column=c).border = BOX

    _note(ws, r + 2, "Source: posted Transaction records (loan_disbursement / loan_repayment) dated within the "
                     "month, grouped by branch. Principal Collected excludes the interest portion of repayments "
                     "(interest is shown separately in the Income Statement sheet).", span=5)


# =============================================================================
# 5. INCOME STATEMENT
# =============================================================================

def _write_income_statement_sheet(wb, report):
    ws = wb.create_sheet('5. Income Statement')
    _set_col_widths(ws, [32, 22, 22])
    _title(ws, 'Income Statement', span=3)
    _subtitle(ws, f"Month: {report['month_start']:%B %Y}   ·   YTD: {report['ytd_start']:%d %b %Y} – {report['month_end']:%d %b %Y}", span=3)

    r = 4
    header_row = r
    _header_row(ws, header_row, ['', f"{report['month_start']:%B %Y} (₦)", 'YTD (₦)'])
    r += 1

    income_first = r
    for label in report['income_groups']:
        _data_row(ws, r, [label, float(report['income_statement']['month'][label]), float(report['income_statement']['ytd'][label])],
                   number_formats={2: CURRENCY_FMT, 3: CURRENCY_FMT})
        r += 1
    income_last = r - 1
    ws.cell(row=r, column=1, value='TOTAL INCOME').font = BOLD
    ws.cell(row=r, column=1).fill = TOTAL_FILL
    for col in (2, 3):
        letter = get_column_letter(col)
        cell = ws.cell(row=r, column=col, value=f'=SUM({letter}{income_first}:{letter}{income_last})')
        cell.font = BOLD
        cell.fill = TOTAL_FILL
        cell.number_format = CURRENCY_FMT
    total_income_row = r
    for c in range(1, 4):
        ws.cell(row=r, column=c).border = BOX
    r += 2

    expense_first = r
    for label in report['expense_buckets']:
        _data_row(ws, r, [label + (' (not tracked)' if label == 'Head Office' else ''),
                           float(report['income_statement']['month'][label]), float(report['income_statement']['ytd'][label])],
                   number_formats={2: CURRENCY_FMT, 3: CURRENCY_FMT})
        r += 1
    expense_last = r - 1
    ws.cell(row=r, column=1, value='TOTAL EXPENDITURE').font = BOLD
    ws.cell(row=r, column=1).fill = TOTAL_FILL
    for col in (2, 3):
        letter = get_column_letter(col)
        cell = ws.cell(row=r, column=col, value=f'=SUM({letter}{expense_first}:{letter}{expense_last})')
        cell.font = BOLD
        cell.fill = TOTAL_FILL
        cell.number_format = CURRENCY_FMT
    total_expense_row = r
    for c in range(1, 4):
        ws.cell(row=r, column=c).border = BOX
    r += 2

    ws.cell(row=r, column=1, value='NET SURPLUS / (DEFICIT)').font = BOLD
    ws.cell(row=r, column=1).fill = HIGHLIGHT_FILL
    for col in (2, 3):
        letter = get_column_letter(col)
        cell = ws.cell(row=r, column=col, value=f'={letter}{total_income_row}-{letter}{total_expense_row}')
        cell.font = BOLD
        cell.fill = HIGHLIGHT_FILL
        cell.number_format = CURRENCY_FMT
    for c in range(1, 4):
        ws.cell(row=r, column=c).border = BOX
    r += 3

    ws.cell(row=r, column=1, value='Appendix — GL account detail behind each bucket above').font = SECTION_FONT
    r += 1
    appendix_header = r
    _header_row(ws, appendix_header, ['Bucket / GL Code / Account', f"{report['month_start']:%b %Y} (₦)", 'YTD (₦)'])
    r += 1
    for row in report['income_statement_appendix']:
        _data_row(ws, r, [f"{row['bucket']} — {row['gl_code']} {row['name']}", float(row['month']), float(row['ytd'])],
                   number_formats={2: CURRENCY_FMT, 3: CURRENCY_FMT})
        r += 1
    r += 1
    _note(ws, r, "Personnel / Administrative / Operating / Head Office are management-reporting groupings "
                 "mapped from this system's chart-of-accounts categories — see 'Cover & Notes' for the full "
                 "mapping rationale, including why Head Office is always ₦0 (no such cost centre exists here).",
          span=3)


# =============================================================================
# 6/7. BALANCE SHEET
# =============================================================================

def _write_balance_sheet_sheet(wb, report):
    ws = wb.create_sheet('6-7. Balance Sheet')
    _set_col_widths(ws, [34, 22])
    _title(ws, 'Statement of Financial Position', span=2)
    _subtitle(ws, f"As at {report['cutoff']:%d %B %Y}", span=2)

    bs = report['balance_sheet']

    r = 4
    ws.cell(row=r, column=1, value='Key Highlights').font = SECTION_FONT
    r += 1
    highlight_rows = {}
    for label, value in [
        ('Cash & Bank', bs['cash_bank_total']),
        ('Outstanding Borrowings (Overdraft Facility)', bs['borrowings_total']),
    ]:
        ws.cell(row=r, column=1, value=label).border = BOX
        c = ws.cell(row=r, column=2, value=float(value)); c.number_format = CURRENCY_FMT; c.border = BOX
        highlight_rows[label] = r
        r += 1
    # Shareholders' Funds is filled in later, once the Equity section below
    # gives us its total row — reserve the row now so the layout is fixed.
    ws.cell(row=r, column=1, value="Shareholders' Funds").border = BOX
    shareholders_funds_row = r
    r += 1
    r += 1

    ws.cell(row=r, column=1, value='ASSETS').font = SECTION_FONT
    r += 1
    header_row = r
    _header_row(ws, header_row, ['Account', 'Balance (₦)'])
    r += 1
    assets_first = r
    for row in bs['assets']:
        _data_row(ws, r, [f"{row['gl_code']} — {row['name']}", float(row['balance'])], number_formats={2: CURRENCY_FMT})
        r += 1
    assets_last = r - 1
    ws.cell(row=r, column=1, value='TOTAL ASSETS').font = BOLD
    ws.cell(row=r, column=1).fill = TOTAL_FILL
    ta_cell = ws.cell(row=r, column=2, value=f'=SUM(B{assets_first}:B{assets_last})')
    ta_cell.font = BOLD; ta_cell.fill = TOTAL_FILL; ta_cell.number_format = CURRENCY_FMT
    total_assets_row = r
    for c in (1, 2):
        ws.cell(row=r, column=c).border = BOX
    r += 2

    ws.cell(row=r, column=1, value='LIABILITIES').font = SECTION_FONT
    r += 1
    header_row2 = r
    _header_row(ws, header_row2, ['Account', 'Balance (₦)'])
    r += 1
    liab_first = r
    for row in bs['liabilities']:
        _data_row(ws, r, [f"{row['gl_code']} — {row['name']}", float(row['balance'])], number_formats={2: CURRENCY_FMT})
        r += 1
    liab_last = r - 1
    ws.cell(row=r, column=1, value='TOTAL LIABILITIES').font = BOLD
    ws.cell(row=r, column=1).fill = TOTAL_FILL
    tl_cell = ws.cell(row=r, column=2, value=f'=SUM(B{liab_first}:B{liab_last})')
    tl_cell.font = BOLD; tl_cell.fill = TOTAL_FILL; tl_cell.number_format = CURRENCY_FMT
    total_liab_row = r
    for c in (1, 2):
        ws.cell(row=r, column=c).border = BOX
    r += 2

    ws.cell(row=r, column=1, value='EQUITY').font = SECTION_FONT
    r += 1
    header_row3 = r
    _header_row(ws, header_row3, ['Account', 'Balance (₦)'])
    r += 1
    equity_first = r
    for row in bs['equity']:
        _data_row(ws, r, [f"{row['gl_code']} — {row['name']}", float(row['balance'])], number_formats={2: CURRENCY_FMT})
        r += 1
    ws.cell(row=r, column=1, value='Net Income (current period, not yet closed to Retained Earnings)').border = BOX
    ni_cell = ws.cell(row=r, column=2, value=float(bs['net_income_ytd'])); ni_cell.number_format = CURRENCY_FMT; ni_cell.border = BOX
    r += 1
    equity_last = r - 1
    ws.cell(row=r, column=1, value='TOTAL EQUITY').font = BOLD
    ws.cell(row=r, column=1).fill = TOTAL_FILL
    te_cell = ws.cell(row=r, column=2, value=f'=SUM(B{equity_first}:B{equity_last})')
    te_cell.font = BOLD; te_cell.fill = TOTAL_FILL; te_cell.number_format = CURRENCY_FMT
    total_equity_row = r
    for c in (1, 2):
        ws.cell(row=r, column=c).border = BOX
    r += 2

    # Fill in the Shareholders' Funds row reserved earlier in the Key
    # Highlights box, now that the Equity section's total row is known.
    sf_cell = ws.cell(row=shareholders_funds_row, column=2, value=f'=B{total_equity_row}')
    sf_cell.number_format = CURRENCY_FMT
    sf_cell.border = BOX
    sf_cell.font = Font(name=FONT_NAME, color='006100')  # cross-reference link colour

    ws.cell(row=r, column=1, value='TOTAL LIABILITIES + EQUITY').font = BOLD
    ws.cell(row=r, column=1).fill = HIGHLIGHT_FILL
    tle_cell = ws.cell(row=r, column=2, value=f'=B{total_liab_row}+B{total_equity_row}')
    tle_cell.font = BOLD; tle_cell.fill = HIGHLIGHT_FILL; tle_cell.number_format = CURRENCY_FMT
    tle_row = r
    for c in (1, 2):
        ws.cell(row=r, column=c).border = BOX
    r += 1

    ws.cell(row=r, column=1, value='Balance Check (Assets − (Liabilities + Equity))').font = Font(name=FONT_NAME, italic=True)
    bc_cell = ws.cell(row=r, column=2, value=f'=B{total_assets_row}-B{tle_row}')
    bc_cell.number_format = CURRENCY_FMT
    bc_cell.font = Font(name=FONT_NAME, italic=True)
    r += 2

    _note(ws, r, "Figures are General Ledger control-account balances summed from posted journal entries up "
                 "to the cutoff date (exact). 'Outstanding Borrowings' is GL 2958 Overdraft Facility — the "
                 "only account resembling external borrowings in this chart of accounts; there is no dedicated "
                 "loans-payable account. The Balance Check row should read ₦0 (or very close, to rounding); a "
                 "material non-zero figure indicates an unposted or miscategorised entry and should be "
                 "investigated before this statement is relied upon.", span=2)
