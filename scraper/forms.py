from django import forms
from .models import ScrapeJob


class ScrapeJobForm(forms.ModelForm):
    class Meta:
        model = ScrapeJob
        fields = ['name', 'sites', 'max_pages', 'delay', 'respect_robots']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g. "Local coffee shops batch 1"',
            }),
            'sites': forms.Textarea(attrs={
                'class': 'form-control font-monospace',
                'rows': 10,
                'placeholder': 'https://example.com\nexample.org\n...',
            }),
            'max_pages': forms.NumberInput(attrs={'class': 'form-control', 'min': 1, 'max': 1000}),
            'delay': forms.NumberInput(attrs={'class': 'form-control', 'step': 0.1, 'min': 0}),
            'respect_robots': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
