"""
Email Service for Seashore Microfinance
========================================

Handles all email sending functionality using SMTP
"""

import smtplib
import random
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from django.conf import settings
from django.utils import timezone
from datetime import timedelta
import logging

logger = logging.getLogger(__name__)


def generate_verification_code():
    """Generate a random 6-digit verification code"""
    return str(random.randint(100000, 999999))


def send_email(to_email, subject, html_content):
    """
    Send HTML email using SMTP
    
    Args:
        to_email: Recipient email address
        subject: Email subject
        html_content: HTML content of the email
    
    Returns:
        bool: True if email sent successfully, False otherwise
    """
    try:
        # Email configuration from settings
        smtp_host = getattr(settings, 'EMAIL_HOST', 'smtp.gmail.com')
        smtp_port = getattr(settings, 'EMAIL_PORT', 587)
        smtp_username = getattr(settings, 'EMAIL_HOST_USER', '')
        smtp_password = getattr(settings, 'EMAIL_HOST_PASSWORD', '')
        from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', smtp_username)
        
        if not smtp_username or not smtp_password:
            logger.warning("Email credentials not configured. Email not sent.")
            return False
        
        # Create message
        message = MIMEMultipart('alternative')
        message['Subject'] = subject
        message['From'] = from_email
        message['To'] = to_email
        
        # Attach HTML content
        html_part = MIMEText(html_content, 'html')
        message.attach(html_part)
        
        # Connect to SMTP server and send email
        use_tls = getattr(settings, 'EMAIL_USE_TLS', True)
        
        if use_tls:
            server = smtplib.SMTP(smtp_host, smtp_port)
            server.starttls()
        else:
            server = smtplib.SMTP_SSL(smtp_host, smtp_port)
        
        server.login(smtp_username, smtp_password)
        server.sendmail(from_email, to_email, message.as_string())
        server.quit()
        
        logger.info(f"Email sent successfully to {to_email}")
        return True
        
    except Exception as e:
        logger.error(f"Failed to send email to {to_email}: {str(e)}")
        return False


def send_password_reset_email(user, reset_token):
    """
    Send password reset email with reset link.

    Args:
        user: User instance
        reset_token: Password reset token

    Returns:
        bool: Success status
    """
    site_url  = getattr(settings, 'SITE_URL', 'http://localhost:8000')
    reset_url = f"{site_url}/reset-password/{reset_token}/"
    name      = user.get_full_name() or user.email
    year      = timezone.now().year

    # ── Seashore brand colours ──────────────────────────────────────────────
    AMBER     = "#f59e0b"
    AMBER_DK  = "#d97706"
    DARK      = "#111827"   # gray-900
    DARK2     = "#1f2937"   # gray-800
    BODY_BG   = "#f3f4f6"   # gray-100
    CARD_BG   = "#ffffff"
    TXT       = "#111827"
    MUTED     = "#6b7280"
    BORDER    = "#e5e7eb"

    subject = "Reset Your Seashore Microfinance Password"

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{subject}</title>
  <style>
    @media only screen and (max-width:600px){{
      .email-wrap{{width:100%!important;}}
      .pad{{padding:24px 16px!important;}}
    }}
    body{{margin:0;padding:0;background-color:{BODY_BG};
         font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;
         -webkit-text-size-adjust:100%;}}
    table{{border-collapse:collapse;}}
    a{{color:{AMBER};text-decoration:none;}}
    .preheader{{display:none!important;visibility:hidden;font-size:1px;line-height:1px;
                max-height:0;max-width:0;opacity:0;overflow:hidden;}}
  </style>
</head>
<body>
<span class="preheader">Reset your Seashore Microfinance password — link expires in 1 hour.</span>

<table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:{BODY_BG};padding:32px 0;">
<tr><td align="center">
<table width="600" class="email-wrap" cellpadding="0" cellspacing="0" border="0">

  <!-- ── HEADER ─────────────────────────────────────────────────────────── -->
  <tr>
    <td style="background:{DARK};border-radius:12px 12px 0 0;padding:36px 40px 32px;">

      <!-- Logo row -->
      <table cellpadding="0" cellspacing="0" border="0" width="100%">
        <tr>
          <td>
            <table cellpadding="0" cellspacing="0" border="0">
              <tr>
                <!-- Amber water-drop icon box -->
                <td style="background:{AMBER};border-radius:10px;width:44px;height:44px;
                            text-align:center;vertical-align:middle;font-size:22px;line-height:44px;">
                  &#127754;
                </td>
                <td style="padding-left:12px;vertical-align:middle;">
                  <span style="font-size:17px;font-weight:700;color:#ffffff;letter-spacing:-0.3px;">SEASHORE</span>
                  <span style="font-size:10px;font-weight:500;color:{MUTED};letter-spacing:2px;
                               display:block;margin-top:1px;">MICROFINANCE</span>
                </td>
              </tr>
            </table>
          </td>
          <td align="right" valign="middle">
            <span style="font-size:10px;color:{MUTED};background:{DARK2};padding:4px 10px;
                         border-radius:20px;letter-spacing:1px;font-weight:600;">SECURE</span>
          </td>
        </tr>
      </table>

      <!-- Divider -->
      <table cellpadding="0" cellspacing="0" border="0" width="100%" style="margin-top:24px;">
        <tr><td style="height:1px;background:linear-gradient(to right,{AMBER},{DARK2},transparent);"></td></tr>
      </table>

      <!-- Title -->
      <table cellpadding="0" cellspacing="0" border="0" width="100%" style="margin-top:24px;">
        <tr>
          <td>
            <p style="margin:0;font-size:24px;font-weight:700;color:#ffffff;line-height:1.2;letter-spacing:-0.4px;">
              Password Reset
            </p>
            <p style="margin:6px 0 0;font-size:13px;color:{MUTED};">
              We received a request to reset your account password.
            </p>
          </td>
        </tr>
      </table>
    </td>
  </tr>

  <!-- ── BODY ──────────────────────────────────────────────────────────── -->
  <tr>
    <td style="background:{CARD_BG};padding:36px 40px 28px;" class="pad">

      <!-- Greeting -->
      <p style="margin:0 0 6px;font-size:17px;font-weight:700;color:{TXT};">Hello, {name}.</p>
      <p style="margin:0 0 28px;font-size:14px;color:{MUTED};line-height:1.7;">
        We received a password reset request for the Seashore Microfinance account associated with
        <strong style="color:{TXT};">{user.email}</strong>.
        Click the button below to choose a new password. This link is valid for <strong>1&nbsp;hour</strong>.
      </p>

      <!-- CTA block -->
      <table cellpadding="0" cellspacing="0" border="0" width="100%"
             style="background:{DARK};border-radius:10px;margin-bottom:24px;">
        <tr>
          <td align="center" style="padding:36px 32px;">
            <a href="{reset_url}"
               style="display:inline-block;background:{AMBER};color:#ffffff;
                      font-size:15px;font-weight:700;text-decoration:none;
                      padding:15px 44px;border-radius:8px;letter-spacing:0.3px;">
              Reset My Password &rarr;
            </a>
            <p style="margin:18px 0 0;font-size:12px;color:{MUTED};">
              &#9203;&nbsp;This link expires in <strong style="color:{AMBER};">1 hour</strong>
            </p>
          </td>
        </tr>
      </table>

      <!-- Fallback URL -->
      <table cellpadding="0" cellspacing="0" border="0" width="100%"
             style="border:1px solid {BORDER};border-radius:8px;margin-bottom:24px;">
        <tr>
          <td style="padding:20px 24px;">
            <p style="margin:0 0 8px;font-size:11px;font-weight:700;color:{MUTED};
                      letter-spacing:1.5px;text-transform:uppercase;">
              Button not working? Copy this link:
            </p>
            <p style="margin:0;font-size:12px;color:{AMBER};word-break:break-all;
                      background:{BODY_BG};padding:10px 14px;border-radius:6px;
                      font-family:'Courier New',monospace;line-height:1.6;">
              {reset_url}
            </p>
          </td>
        </tr>
      </table>

      <!-- Security notice -->
      <table cellpadding="0" cellspacing="0" border="0" width="100%"
             style="background:#fffbeb;border:1px solid #fcd34d;border-radius:8px;margin-bottom:8px;">
        <tr>
          <td style="padding:16px 20px;">
            <p style="margin:0 0 4px;font-size:12px;font-weight:700;color:#b45309;letter-spacing:0.5px;">
              &#9888; SECURITY NOTICE
            </p>
            <p style="margin:0;font-size:13px;color:#78350f;line-height:1.6;">
              If you did not request a password reset, ignore this email — your account remains secure.
              Never share your password with anyone. Seashore staff will never ask for it.
            </p>
          </td>
        </tr>
      </table>

    </td>
  </tr>

  <!-- ── FOOTER ─────────────────────────────────────────────────────────── -->
  <tr>
    <td style="background:{DARK};border-radius:0 0 12px 12px;padding:28px 40px;
               border-top:1px solid {DARK2};">
      <table cellpadding="0" cellspacing="0" border="0" width="100%">
        <tr>
          <td align="center">
            <p style="margin:0 0 4px;font-size:12px;font-weight:700;color:{MUTED};letter-spacing:1px;">
              SEASHORE MICROFINANCE
            </p>
            <p style="margin:0 0 14px;font-size:11px;color:#374151;">
              Professional Microfinance Solutions
            </p>
            <p style="margin:0;font-size:11px;color:#374151;line-height:1.7;">
              &copy; {year} Seashore Microfinance. All rights reserved.<br>
              This is an automated message — please do not reply to this email.<br>
              Sent to {user.email}
            </p>
          </td>
        </tr>
      </table>
    </td>
  </tr>

</table>
</td></tr>
</table>
</body>
</html>"""

    return send_email(user.email, subject, html_content)


def send_welcome_email(user):
    """
    Send welcome email to new user
    
    Args:
        user: User instance
    
    Returns:
        bool: Success status
    """
    subject = "Welcome to Seashore Microfinance! 🎉"
    
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            body {{
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                line-height: 1.6;
                color: #333;
                margin: 0;
                padding: 0;
                background-color: #f4f4f4;
            }}
            .container {{
                max-width: 600px;
                margin: 0 auto;
                background-color: #ffffff;
                border-radius: 10px;
                overflow: hidden;
                box-shadow: 0 4px 6px rgba(0,0,0,0.1);
            }}
            .header {{
                background: linear-gradient(135deg, #eab308 0%, #ca8a04 100%);
                color: white;
                padding: 40px 20px;
                text-align: center;
            }}
            .header h1 {{
                margin: 0;
                font-size: 28px;
                font-weight: 700;
            }}
            .logo {{
                font-size: 64px;
                margin-bottom: 10px;
            }}
            .content {{
                padding: 40px 30px;
            }}
            .greeting {{
                font-size: 20px;
                font-weight: 600;
                color: #eab308;
                margin-bottom: 20px;
            }}
            .message {{
                font-size: 16px;
                color: #555;
                margin-bottom: 30px;
            }}
            .features {{
                background-color: #fefce8;
                border-left: 4px solid #eab308;
                padding: 20px;
                margin: 30px 0;
            }}
            .features h3 {{
                color: #eab308;
                margin-top: 0;
            }}
            .features ul {{
                margin: 10px 0;
                padding-left: 20px;
            }}
            .features li {{
                margin: 8px 0;
                color: #555;
            }}
            .footer {{
                background-color: #f8f9fa;
                padding: 30px;
                text-align: center;
                font-size: 14px;
                color: #666;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <div class="logo">🏦</div>
                <h1>Welcome to Seashore Microfinance</h1>
            </div>
            
            <div class="content">
                <div class="greeting">
                    Hello {user.get_full_name() or 'Team Member'}! 👋
                </div>
                
                <div class="message">
                    <p>Welcome to <strong>Seashore Microfinance Bank</strong>!</p>
                    
                    <p>Your account as <strong>{user.get_user_role_display()}</strong> has been created successfully. You're now part of our team!</p>
                </div>
                
                <div class="features">
                    <h3>🚀 Getting Started</h3>
                    <ul>
                        <li><strong>Log in</strong> with your credentials</li>
                        <li><strong>Complete your profile</strong> with required information</li>
                        <li><strong>Review your dashboard</strong> based on your role</li>
                        <li><strong>Access training materials</strong> in the knowledge base</li>
                    </ul>
                </div>
                
                <div class="message">
                    <p><strong>Your Role: {user.get_user_role_display()}</strong></p>
                    <p>Branch: {user.branch.name if user.branch else 'Not assigned'}</p>
                    <p>Employee ID: {user.employee_id}</p>
                </div>
            </div>
            
            <div class="footer">
                <p><strong>Seashore Microfinance Bank</strong></p>
                <p>Professional Microfinance Solutions</p>
            </div>
        </div>
    </body>
    </html>
    """
    
    return send_email(user.email, subject, html_content)


def send_client_approval_email(client):
    """
    Send email to client when their account is approved
    
    Args:
        client: Client instance
    
    Returns:
        bool: Success status
    """
    subject = "Your Seashore Account Has Been Approved! ✅"
    
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <style>
            body {{
                font-family: Arial, sans-serif;
                line-height: 1.6;
                color: #333;
            }}
            .container {{
                max-width: 600px;
                margin: 0 auto;
                padding: 20px;
            }}
            .header {{
                background: linear-gradient(135deg, #eab308 0%, #ca8a04 100%);
                color: white;
                padding: 30px;
                text-align: center;
                border-radius: 10px 10px 0 0;
            }}
            .content {{
                background: white;
                padding: 30px;
                border: 1px solid #ddd;
            }}
            .highlight {{
                background-color: #fefce8;
                padding: 15px;
                border-left: 4px solid #eab308;
                margin: 20px 0;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>🎉 Account Approved!</h1>
            </div>
            <div class="content">
                <p>Dear {client.get_full_name()},</p>
                
                <p>Congratulations! Your Seashore Microfinance account has been approved.</p>
                
                <div class="highlight">
                    <p><strong>Account Details:</strong></p>
                    <p>Client ID: {client.client_id}</p>
                    <p>Branch: {client.branch.name}</p>
                </div>
                
                <p>You can now:</p>
                <ul>
                    <li>Apply for loans</li>
                    <li>Open savings accounts</li>
                    <li>Access our full range of financial services</li>
                </ul>
                
                <p>Visit your nearest branch to get started!</p>
                
                <p>Best regards,<br>Seashore Microfinance Team</p>
            </div>
        </div>
    </body>
    </html>
    """
    
    return send_email(client.email, subject, html_content)


def send_loan_approval_email(loan):
    """
    Send email when loan is approved
    
    Args:
        loan: Loan instance
    
    Returns:
        bool: Success status
    """
    subject = "Your Loan Has Been Approved! 🎊"
    
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <style>
            body {{
                font-family: Arial, sans-serif;
                line-height: 1.6;
                color: #333;
            }}
            .container {{
                max-width: 600px;
                margin: 0 auto;
                padding: 20px;
            }}
            .header {{
                background: linear-gradient(135deg, #22c55e 0%, #16a34a 100%);
                color: white;
                padding: 30px;
                text-align: center;
                border-radius: 10px 10px 0 0;
            }}
            .content {{
                background: white;
                padding: 30px;
                border: 1px solid #ddd;
            }}
            .loan-details {{
                background-color: #f0fdf4;
                padding: 20px;
                border-left: 4px solid #22c55e;
                margin: 20px 0;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>✅ Loan Approved!</h1>
            </div>
            <div class="content">
                <p>Dear {loan.client.get_full_name()},</p>
                
                <p>Great news! Your loan application has been approved.</p>
                
                <div class="loan-details">
                    <p><strong>Loan Details:</strong></p>
                    <p>Loan Number: {loan.loan_number}</p>
                    <p>Principal Amount: ₦{loan.principal_amount:,.2f}</p>
                    <p>Total Repayment: ₦{loan.total_repayment:,.2f}</p>
                    <p>Monthly Installment: ₦{loan.installment_amount:,.2f}</p>
                    <p>Duration: {loan.duration_months} months</p>
                </div>
                
                <p>The funds will be disbursed to your account shortly.</p>
                
                <p>Best regards,<br>Seashore Microfinance Team</p>
            </div>
        </div>
    </body>
    </html>
    """
    
    return send_email(loan.client.email, subject, html_content)