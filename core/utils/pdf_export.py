"""
PDF Export Utilities using WeasyPrint
=====================================

Beautiful PDF generation for accounting reports
"""

from django.template.loader import render_to_string
from django.http import HttpResponse
import io


def render_to_pdf(template_name, context, filename='report.pdf'):
    """
    Render a Django template to PDF using WeasyPrint

    Args:
        template_name: Path to the template
        context: Context dictionary for the template
        filename: Name of the PDF file to download

    Returns:
        HttpResponse with PDF content
    """
    # Lazy import - only load when function is called
    try:
        from weasyprint import HTML, CSS
        from weasyprint.text.fonts import FontConfiguration
    except (ImportError, OSError) as e:
        # Fallback for Vercel/environments without system dependencies
        return HttpResponse(
            f"PDF generation is not available in this environment. "
            f"This feature requires deployment on a platform with full system library support. "
            f"Error: {str(e)}",
            status=503,
            content_type='text/plain'
        )
    
    # Render HTML template
    html_string = render_to_string(template_name, context)

    # Configure fonts
    font_config = FontConfiguration()

    # Custom CSS for PDF styling
    pdf_css = CSS(string='''
        @page {
            size: A4;
            margin: 2cm 1.5cm;

            @top-center {
                content: "Seashore Microfinance";
                font-size: 10pt;
                color: #6B7280;
            }

            @bottom-right {
                content: "Page " counter(page) " of " counter(pages);
                font-size: 9pt;
                color: #6B7280;
            }
        }

        body {
            font-family: 'Arial', sans-serif;
            font-size: 10pt;
            line-height: 1.4;
            color: #1F2937;
        }

        h1, h2, h3 {
            color: #111827;
            page-break-after: avoid;
        }

        table {
            width: 100%;
            border-collapse: collapse;
            page-break-inside: avoid;
            margin-bottom: 1rem;
        }

        thead {
            display: table-header-group;
        }

        tfoot {
            display: table-footer-group;
        }

        tr {
            page-break-inside: avoid;
        }

        th {
            background-color: #F3F4F6;
            border-bottom: 2px solid #D1D5DB;
            padding: 8px 12px;
            text-align: left;
            font-weight: 600;
            font-size: 9pt;
            text-transform: uppercase;
            color: #374151;
        }

        td {
            border-bottom: 1px solid #E5E7EB;
            padding: 6px 12px;
        }

        .text-right {
            text-align: right;
        }

        .text-center {
            text-align: center;
        }

        .font-bold {
            font-weight: 700;
        }

        .bg-gray-100 {
            background-color: #F3F4F6;
        }

        .text-green-600 {
            color: #059669;
        }

        .text-red-600 {
            color: #DC2626;
        }

        .text-blue-600 {
            color: #2563EB;
        }

        .header-section {
            margin-bottom: 2rem;
            padding-bottom: 1rem;
            border-bottom: 2px solid #D97706;
        }

        .report-title {
            font-size: 18pt;
            font-weight: 700;
            color: #D97706;
            margin-bottom: 0.5rem;
        }

        .report-subtitle {
            font-size: 11pt;
            color: #6B7280;
        }

        .summary-box {
            background-color: #FEF3C7;
            border-left: 4px solid #D97706;
            padding: 1rem;
            margin: 1rem 0;
        }

        .alert-box {
            background-color: #FEE2E2;
            border-left: 4px solid #DC2626;
            padding: 1rem;
            margin: 1rem 0;
        }

        .info-grid {
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 1rem;
            margin-bottom: 1.5rem;
        }

        .info-item {
            padding: 0.5rem;
        }

        .info-label {
            font-size: 9pt;
            color: #6B7280;
            text-transform: uppercase;
            font-weight: 600;
        }

        .info-value {
            font-size: 11pt;
            color: #111827;
            font-weight: 500;
        }
    ''', font_config=font_config)

    # Generate PDF
    html = HTML(string=html_string)
    pdf_file = html.write_pdf(stylesheets=[pdf_css], font_config=font_config)

    # Create response
    response = HttpResponse(pdf_file, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'

    return response


def generate_trial_balance_pdf(report_data, form_data):
    """Generate Trial Balance PDF"""
    context = {
        'report_data': report_data,
        'form_data': form_data,
        'report_type': 'Trial Balance',
    }

    filename = f'trial_balance_{report_data["date_from"].strftime("%Y%m%d")}_{report_data["date_to"].strftime("%Y%m%d")}.pdf'
    return render_to_pdf('accounting/pdf/trial_balance_pdf.html', context, filename)


def generate_profit_loss_pdf(report_data, form_data):
    """Generate Profit & Loss PDF"""
    context = {
        'report_data': report_data,
        'form_data': form_data,
        'report_type': 'Profit & Loss Statement',
    }

    filename = f'profit_loss_{report_data["date_from"].strftime("%Y%m%d")}_{report_data["date_to"].strftime("%Y%m%d")}.pdf'
    return render_to_pdf('accounting/pdf/profit_loss_pdf.html', context, filename)


def generate_balance_sheet_pdf(report_data, form_data):
    """Generate Balance Sheet PDF"""
    context = {
        'report_data': report_data,
        'form_data': form_data,
        'report_type': 'Balance Sheet',
    }

    filename = f'balance_sheet_{report_data["as_of_date"].strftime("%Y%m%d")}.pdf'
    return render_to_pdf('accounting/pdf/balance_sheet_pdf.html', context, filename)


def generate_general_ledger_pdf(report_data, form_data):
    """Generate General Ledger PDF"""
    context = {
        'report_data': report_data,
        'form_data': form_data,
        'report_type': 'General Ledger',
    }

    filename = f'general_ledger_{report_data["account"].gl_code}_{report_data["date_from"].strftime("%Y%m%d")}.pdf'
    return render_to_pdf('accounting/pdf/general_ledger_pdf.html', context, filename)


def generate_cash_flow_pdf(report_data, form_data):
    """Generate Cash Flow Statement PDF"""
    context = {
        'report_data': report_data,
        'form_data': form_data,
        'report_type': 'Cash Flow Statement',
    }

    filename = f'cash_flow_{report_data["date_from"].strftime("%Y%m%d")}_{report_data["date_to"].strftime("%Y%m%d")}.pdf'
    return render_to_pdf('accounting/pdf/cash_flow_pdf.html', context, filename)


def generate_transaction_audit_pdf(report_data, form_data=None):
    """Generate Transaction Audit PDF"""
    context = {
        'report_data': report_data,
        'form_data': form_data,
        'report_type': 'Transaction Audit Log',
    }

    from datetime import datetime
    filename = f'transaction_audit_{datetime.now().strftime("%Y%m%d_%H%M%S")}.pdf'
    return render_to_pdf('accounting/pdf/transaction_audit_pdf.html', context, filename)



