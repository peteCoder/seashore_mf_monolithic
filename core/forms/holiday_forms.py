from django import forms
from core.models import PublicHoliday


class PublicHolidayForm(forms.ModelForm):
    class Meta:
        model = PublicHoliday
        fields = ['date', 'name']
        widgets = {
            'date': forms.DateInput(
                attrs={
                    'type': 'date',
                    'class': 'w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg '
                             'bg-white dark:bg-gray-700 text-gray-900 dark:text-white '
                             'focus:outline-none focus:ring-2 focus:ring-primary-500',
                }
            ),
            'name': forms.TextInput(
                attrs={
                    'class': 'w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg '
                             'bg-white dark:bg-gray-700 text-gray-900 dark:text-white '
                             'focus:outline-none focus:ring-2 focus:ring-primary-500',
                    'placeholder': 'e.g. Independence Day',
                }
            ),
        }
