"""
Authentication Views
====================

Login, Logout, Register, Password Reset
"""

from django.shortcuts import render, redirect
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from django.utils.crypto import get_random_string
from datetime import timedelta
from django import forms
from django.contrib.auth.forms import PasswordResetForm as DjangoPasswordResetForm
from django.core.exceptions import ValidationError

from core.models import User, Branch
from core.email_service import send_password_reset_email, send_welcome_email


# =============================================================================
# FORMS
# =============================================================================

class LoginForm(forms.Form):
    """Login form"""
    email = forms.EmailField(
        label='Email Address',
        widget=forms.EmailInput(attrs={
            'class': 'peer w-full px-4 pt-6 pb-2 rounded-lg border border-gray-300 dark:border-dark-600 bg-white dark:bg-dark-700 text-gray-900 dark:text-white focus:border-primary-500 dark:focus:border-primary-500 focus:ring-2 focus:ring-primary-200 dark:focus:ring-primary-900/30 transition-all placeholder-transparent',
            'placeholder': 'Email Address',
            'id': 'email'
        })
    )
    password = forms.CharField(
        label='Password',
        widget=forms.PasswordInput(attrs={
            'class': 'peer w-full px-4 pt-6 pb-2 rounded-lg border border-gray-300 dark:border-dark-600 bg-white dark:bg-dark-700 text-gray-900 dark:text-white focus:border-primary-500 dark:focus:border-primary-500 focus:ring-2 focus:ring-primary-200 dark:focus:ring-primary-900/30 transition-all placeholder-transparent',
            'placeholder': 'Password',
            'id': 'password'
        })
    )
    remember_me = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(attrs={
            'class': 'w-4 h-4 text-primary-600 bg-white dark:bg-dark-700 border-gray-300 dark:border-dark-600 rounded focus:ring-primary-500 dark:focus:ring-primary-500'
        })
    )


class StaffRegistrationForm(forms.ModelForm):
    """Staff registration form"""
    password1 = forms.CharField(
        label='Password',
        widget=forms.PasswordInput(attrs={
            'class': 'peer w-full px-4 pt-6 pb-2 rounded-lg border border-gray-300 dark:border-dark-600 bg-white dark:bg-dark-700 text-gray-900 dark:text-white focus:border-primary-500 dark:focus:border-primary-500 focus:ring-2 focus:ring-primary-200 dark:focus:ring-primary-900/30 transition-all placeholder-transparent',
            'placeholder': 'Password',
            'id': 'password1'
        })
    )
    password2 = forms.CharField(
        label='Confirm Password',
        widget=forms.PasswordInput(attrs={
            'class': 'peer w-full px-4 pt-6 pb-2 rounded-lg border border-gray-300 dark:border-dark-600 bg-white dark:bg-dark-700 text-gray-900 dark:text-white focus:border-primary-500 dark:focus:border-primary-500 focus:ring-2 focus:ring-primary-200 dark:focus:ring-primary-900/30 transition-all placeholder-transparent',
            'placeholder': 'Confirm Password',
            'id': 'password2'
        })
    )
    
    class Meta:
        model = User
        fields = ['email', 'first_name', 'last_name', 'phone', 'user_role', 
                 'designation', 'department', 'branch']
        widgets = {
            'email': forms.EmailInput(attrs={
                'class': 'peer w-full px-4 pt-6 pb-2 rounded-lg border border-gray-300 dark:border-dark-600 bg-white dark:bg-dark-700 text-gray-900 dark:text-white focus:border-primary-500 dark:focus:border-primary-500 focus:ring-2 focus:ring-primary-200 dark:focus:ring-primary-900/30 transition-all placeholder-transparent',
                'placeholder': 'Email Address',
                'id': 'email'
            }),
            'first_name': forms.TextInput(attrs={
                'class': 'peer w-full px-4 pt-6 pb-2 rounded-lg border border-gray-300 dark:border-dark-600 bg-white dark:bg-dark-700 text-gray-900 dark:text-white focus:border-primary-500 dark:focus:border-primary-500 focus:ring-2 focus:ring-primary-200 dark:focus:ring-primary-900/30 transition-all placeholder-transparent',
                'placeholder': 'First Name',
                'id': 'first_name'
            }),
            'last_name': forms.TextInput(attrs={
                'class': 'peer w-full px-4 pt-6 pb-2 rounded-lg border border-gray-300 dark:border-dark-600 bg-white dark:bg-dark-700 text-gray-900 dark:text-white focus:border-primary-500 dark:focus:border-primary-500 focus:ring-2 focus:ring-primary-200 dark:focus:ring-primary-900/30 transition-all placeholder-transparent',
                'placeholder': 'Last Name',
                'id': 'last_name'
            }),
            'phone': forms.TextInput(attrs={
                'class': 'peer w-full px-4 pt-6 pb-2 rounded-lg border border-gray-300 dark:border-dark-600 bg-white dark:bg-dark-700 text-gray-900 dark:text-white focus:border-primary-500 dark:focus:border-primary-500 focus:ring-2 focus:ring-primary-200 dark:focus:ring-primary-900/30 transition-all placeholder-transparent',
                'placeholder': 'Phone Number',
                'id': 'phone'
            }),
            'user_role': forms.Select(attrs={
                'class': 'peer w-full px-4 pt-6 pb-2 rounded-lg border border-gray-300 dark:border-dark-600 bg-white dark:bg-dark-700 text-gray-900 dark:text-white focus:border-primary-500 dark:focus:border-primary-500 focus:ring-2 focus:ring-primary-200 dark:focus:ring-primary-900/30 transition-all',
                'id': 'user_role'
            }),
            'designation': forms.TextInput(attrs={
                'class': 'peer w-full px-4 pt-6 pb-2 rounded-lg border border-gray-300 dark:border-dark-600 bg-white dark:bg-dark-700 text-gray-900 dark:text-white focus:border-primary-500 dark:focus:border-primary-500 focus:ring-2 focus:ring-primary-200 dark:focus:ring-primary-900/30 transition-all placeholder-transparent',
                'placeholder': 'Designation',
                'id': 'designation'
            }),
            'department': forms.TextInput(attrs={
                'class': 'peer w-full px-4 pt-6 pb-2 rounded-lg border border-gray-300 dark:border-dark-600 bg-white dark:bg-dark-700 text-gray-900 dark:text-white focus:border-primary-500 dark:focus:border-primary-500 focus:ring-2 focus:ring-primary-200 dark:focus:ring-primary-900/30 transition-all placeholder-transparent',
                'placeholder': 'Department',
                'id': 'department'
            }),
            'branch': forms.Select(attrs={
                'class': 'peer w-full px-4 pt-6 pb-2 rounded-lg border border-gray-300 dark:border-dark-600 bg-white dark:bg-dark-700 text-gray-900 dark:text-white focus:border-primary-500 dark:focus:border-primary-500 focus:ring-2 focus:ring-primary-200 dark:focus:ring-primary-900/30 transition-all',
                'id': 'branch'
            }),
        }
    
    def clean_password2(self):
        password1 = self.cleaned_data.get('password1')
        password2 = self.cleaned_data.get('password2')
        
        if password1 and password2 and password1 != password2:
            raise ValidationError("Passwords don't match")
        
        if len(password1) < 8:
            raise ValidationError("Password must be at least 8 characters long")
        
        return password2
    
    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data['password1'])
        user.is_approved = False  # Requires admin approval
        
        if commit:
            user.save()
        
        return user


class PasswordResetRequestForm(forms.Form):
    """Password reset request form"""
    email = forms.EmailField(
        label='Email Address',
        widget=forms.EmailInput(attrs={
            'class': 'peer w-full px-4 pt-6 pb-2 rounded-lg border border-gray-300 dark:border-dark-600 bg-white dark:bg-dark-700 text-gray-900 dark:text-white focus:border-primary-500 dark:focus:border-primary-500 focus:ring-2 focus:ring-primary-200 dark:focus:ring-primary-900/30 transition-all placeholder-transparent',
            'placeholder': 'Email Address',
            'id': 'email'
        })
    )


class PasswordResetConfirmForm(forms.Form):
    """Password reset confirmation form"""
    password1 = forms.CharField(
        label='New Password',
        widget=forms.PasswordInput(attrs={
            'class': 'peer w-full px-4 pt-6 pb-2 rounded-lg border border-gray-300 dark:border-dark-600 bg-white dark:bg-dark-700 text-gray-900 dark:text-white focus:border-primary-500 dark:focus:border-primary-500 focus:ring-2 focus:ring-primary-200 dark:focus:ring-primary-900/30 transition-all placeholder-transparent',
            'placeholder': 'New Password',
            'id': 'password1'
        })
    )
    password2 = forms.CharField(
        label='Confirm Password',
        widget=forms.PasswordInput(attrs={
            'class': 'peer w-full px-4 pt-6 pb-2 rounded-lg border border-gray-300 dark:border-dark-600 bg-white dark:bg-dark-700 text-gray-900 dark:text-white focus:border-primary-500 dark:focus:border-primary-500 focus:ring-2 focus:ring-primary-200 dark:focus:ring-primary-900/30 transition-all placeholder-transparent',
            'placeholder': 'Confirm Password',
            'id': 'password2'
        })
    )
    
    def clean_password2(self):
        password1 = self.cleaned_data.get('password1')
        password2 = self.cleaned_data.get('password2')
        
        if password1 and password2 and password1 != password2:
            raise ValidationError("Passwords don't match")
        
        if len(password1) < 8:
            raise ValidationError("Password must be at least 8 characters long")
        
        return password2


# =============================================================================
# VIEWS
# =============================================================================

def login_view(request):
    """
    Login view
    
    GET: Display login form
    POST: Process login
    """
    # Redirect if already logged in
    if request.user.is_authenticated:
        return redirect('core:dashboard')
    
    if request.method == 'POST':
        form = LoginForm(request.POST)
        
        if form.is_valid():
            email = form.cleaned_data['email']
            password = form.cleaned_data['password']
            remember_me = form.cleaned_data.get('remember_me', False)
            
            # Authenticate user
            user = authenticate(request, email=email, password=password)
            
            if user is not None:
                # Check if user is approved
                if not user.is_approved:
                    form.add_error(None, 'Your account is pending approval. Please wait for admin approval.')
                    return render(request, 'auth/login.html', {'form': form})
                
                # Set session expiry
                if not remember_me:
                    request.session.set_expiry(0)  # Session expires on browser close

                # Update last login
                user.last_login = timezone.now()
                user.save(update_fields=['last_login'])

                # If user has 2FA enabled, park the UID and redirect to verify
                if user.is_2fa_enabled:
                    request.session['_2fa_pending_uid'] = str(user.pk)
                    next_url = request.GET.get('next', '')
                    verify_url = '/verify-2fa/' + (f'?next={next_url}' if next_url else '')
                    return redirect(verify_url)

                # No 2FA — log in normally
                login(request, user)

                # Record login IP for IP-session locking (core.middleware.IPSessionLockMiddleware)
                x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR', '')
                login_ip = x_forwarded_for.split(',')[0].strip() if x_forwarded_for else request.META.get('REMOTE_ADDR', '')
                request.session['login_ip'] = login_ip

                messages.success(request, f'Welcome back, {user.get_full_name()}!')

                # Redirect to next or dashboard
                next_url = request.GET.get('next', 'core:dashboard')
                return redirect(next_url)
            else:
                # authenticate() returns None for wrong credentials AND for inactive users.
                # Check whether the credentials are correct but the account is inactive.
                from core.models import User as StaffUser
                try:
                    existing = StaffUser.objects.get(email=email)
                    if existing.check_password(password) and not existing.is_active:
                        form.add_error(None, 'Your account is inactive. Please contact the administrator to reactivate it.')
                    elif existing.check_password(password) and not existing.is_approved:
                        form.add_error(None, 'Your account is pending approval. Please wait for admin approval.')
                    else:
                        form.add_error(None, 'Invalid email or password. Please try again.')
                except StaffUser.DoesNotExist:
                    form.add_error(None, 'Invalid email or password. Please try again.')
    else:
        form = LoginForm()

    # django-axes redirects here with ?username=<email> when an account is locked out
    lockout_error = None
    if request.method == 'GET' and request.GET.get('username'):
        lockout_error = (
            'Too many failed login attempts. Your account has been locked for 1 hour. '
            'Please try again after 1 hour, or contact the administrator to unlock it immediately.'
        )

    context = {
        'form': form,
        'page_title': 'Login',
        'lockout_error': lockout_error,
    }

    return render(request, 'auth/login.html', context)


@login_required
def logout_view(request):
    """
    Logout view
    
    Logs out user and redirects to login page
    """
    logout(request)
    messages.success(request, 'You have been logged out successfully.')
    return redirect('core:login')


def register_view(request):
    """
    Staff registration view
    
    GET: Display registration form
    POST: Process registration
    """
    # Only show registration page if user is not logged in
    if request.user.is_authenticated:
        return redirect('core:dashboard')
    
    if request.method == 'POST':
        form = StaffRegistrationForm(request.POST)
        
        if form.is_valid():
            user = form.save()
            
            # Send welcome email
            try:
                send_welcome_email(user)
            except Exception as e:
                # Log error but don't fail registration
                print(f"Failed to send welcome email: {e}")
            
            messages.success(
                request,
                'Registration successful! Your account is pending approval. '
                'You will receive an email once approved.'
            )
            return redirect('core:login')
    else:
        form = StaffRegistrationForm()
    
    context = {
        'form': form,
        'page_title': 'Register'
    }
    
    return render(request, 'auth/register.html', context)


def password_reset_request_view(request):
    """
    Password reset request view
    
    GET: Display email form
    POST: Send reset email
    """
    if request.user.is_authenticated:
        return redirect('core:dashboard')
    
    if request.method == 'POST':
        form = PasswordResetRequestForm(request.POST)
        
        if form.is_valid():
            email = form.cleaned_data['email']
            
            try:
                user = User.objects.get(email=email, is_active=True)
                
                # Generate reset token
                reset_token = get_random_string(64)
                
                # Store token in user model (you'll need to add these fields)
                user.password_reset_token = reset_token
                user.password_reset_expires = timezone.now() + timedelta(hours=1)
                user.save(update_fields=['password_reset_token', 'password_reset_expires'])
                
                # Send email
                send_password_reset_email(user, reset_token)
                
                messages.success(
                    request,
                    'Password reset email sent! Please check your inbox.'
                )
                return redirect('core:login')
                
            except User.DoesNotExist:
                # Don't reveal if email exists or not (security)
                messages.success(
                    request,
                    'If an account with that email exists, you will receive a password reset email.'
                )
                return redirect('core:login')
    else:
        form = PasswordResetRequestForm()
    
    context = {
        'form': form,
        'page_title': 'Reset Password'
    }
    
    return render(request, 'auth/password_reset_request.html', context)


def password_reset_confirm_view(request, token):
    """
    Password reset confirmation view
    
    GET: Display new password form
    POST: Reset password
    """
    if request.user.is_authenticated:
        return redirect('core:dashboard')
    
    # Validate token
    try:
        user = User.objects.get(
            password_reset_token=token,
            password_reset_expires__gt=timezone.now()
        )
    except User.DoesNotExist:
        messages.error(request, 'Invalid or expired password reset link.')
        return redirect('core:password_reset_request')
    
    if request.method == 'POST':
        form = PasswordResetConfirmForm(request.POST)
        
        if form.is_valid():
            password = form.cleaned_data['password1']
            
            # Set new password
            user.set_password(password)
            user.password_reset_token = None
            user.password_reset_expires = None
            user.save()
            
            messages.success(
                request,
                'Password reset successful! You can now log in with your new password.'
            )
            return redirect('core:login')
    else:
        form = PasswordResetConfirmForm()
    
    context = {
        'form': form,
        'token': token,
        'page_title': 'Set New Password'
    }
    
    return render(request, 'auth/password_reset_confirm.html', context)


