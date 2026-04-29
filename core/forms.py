from django import forms
from .models import AppSettings, Campaign, Contact, ContactList, EmailTemplate


_INPUT = {'class': 'form-control'}
_CHECK = {'class': 'form-check-input'}


class ContactListForm(forms.ModelForm):
    class Meta:
        model = ContactList
        fields = ['name', 'description']
        widgets = {
            'name': forms.TextInput(attrs=_INPUT),
            'description': forms.TextInput(attrs=_INPUT),
        }


class EmailTemplateForm(forms.ModelForm):
    class Meta:
        model = EmailTemplate
        fields = ['name', 'subject', 'body_html', 'body_text']
        widgets = {
            'name': forms.TextInput(attrs=_INPUT),
            'subject': forms.TextInput(attrs={**_INPUT, 'placeholder': 'Hi {{ first_name|default:"there" }}!'}),
            'body_html': forms.Textarea(attrs={**_INPUT, 'rows': 14, 'class': 'form-control font-monospace'}),
            'body_text': forms.Textarea(attrs={**_INPUT, 'rows': 6, 'class': 'form-control font-monospace'}),
        }


class CampaignForm(forms.ModelForm):
    class Meta:
        model = Campaign
        fields = ['name', 'template', 'contact_list', 'from_name', 'from_email', 'reply_to']
        widgets = {
            'name': forms.TextInput(attrs=_INPUT),
            'template': forms.Select(attrs={'class': 'form-select'}),
            'contact_list': forms.Select(attrs={'class': 'form-select'}),
            'from_name': forms.TextInput(attrs=_INPUT),
            'from_email': forms.EmailInput(attrs=_INPUT),
            'reply_to': forms.EmailInput(attrs=_INPUT),
        }


class SendTestForm(forms.Form):
    to_email = forms.EmailField(widget=forms.EmailInput(attrs=_INPUT))
    from_name = forms.CharField(widget=forms.TextInput(attrs=_INPUT))
    from_email = forms.EmailField(widget=forms.EmailInput(attrs=_INPUT))


class ContactForm(forms.ModelForm):
    class Meta:
        model = Contact
        fields = ['email', 'first_name', 'last_name', 'tags', 'lists', 'is_suppressed', 'suppressed_reason']
        widgets = {
            'email': forms.EmailInput(attrs=_INPUT),
            'first_name': forms.TextInput(attrs=_INPUT),
            'last_name': forms.TextInput(attrs=_INPUT),
            'tags': forms.TextInput(attrs=_INPUT),
            'lists': forms.SelectMultiple(attrs={'class': 'form-select', 'size': 6}),
            'is_suppressed': forms.CheckboxInput(attrs=_CHECK),
            'suppressed_reason': forms.TextInput(attrs=_INPUT),
        }


class AppSettingsForm(forms.ModelForm):
    smtp_password = forms.CharField(
        required=False,
        widget=forms.PasswordInput(render_value=True, attrs=_INPUT),
    )

    class Meta:
        model = AppSettings
        fields = [
            'site_base_url',
            'default_from_name', 'default_from_email', 'default_reply_to',
            'email_backend',
            'smtp_host', 'smtp_port', 'smtp_username', 'smtp_password',
            'smtp_use_tls', 'smtp_use_ssl', 'smtp_timeout',
        ]
        widgets = {
            'site_base_url': forms.URLInput(attrs=_INPUT),
            'default_from_name': forms.TextInput(attrs=_INPUT),
            'default_from_email': forms.EmailInput(attrs=_INPUT),
            'default_reply_to': forms.EmailInput(attrs=_INPUT),
            'email_backend': forms.Select(attrs={'class': 'form-select'}),
            'smtp_host': forms.TextInput(attrs={**_INPUT, 'placeholder': 'smtp.gmail.com'}),
            'smtp_port': forms.NumberInput(attrs={**_INPUT, 'min': 1, 'max': 65535}),
            'smtp_username': forms.TextInput(attrs=_INPUT),
            'smtp_use_tls': forms.CheckboxInput(attrs=_CHECK),
            'smtp_use_ssl': forms.CheckboxInput(attrs=_CHECK),
            'smtp_timeout': forms.NumberInput(attrs={**_INPUT, 'min': 1, 'max': 300}),
        }


class SettingsTestForm(forms.Form):
    to_email = forms.EmailField(widget=forms.EmailInput(attrs=_INPUT))


class ImportContactsForm(forms.Form):
    list_name = forms.CharField(
        label='Add to list',
        widget=forms.TextInput(attrs={**_INPUT, 'placeholder': 'List name (created if new)'}),
    )
    emails = forms.CharField(
        label='Emails',
        widget=forms.Textarea(attrs={**_INPUT, 'rows': 8, 'placeholder': 'one email per line'}),
    )
