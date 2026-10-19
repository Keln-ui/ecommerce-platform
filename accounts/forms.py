from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.password_validation import validate_password

from .models import SellerProfile, User


class UserRegistrationForm(forms.ModelForm):
    """Sign up with an email address; no username to invent."""

    password1 = forms.CharField(
        label="Password",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )
    password2 = forms.CharField(
        label="Confirm password",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
        help_text="Re-enter the password to confirm it.",
    )

    class Meta:
        model = User
        fields = ("first_name", "last_name", "email", "phone")
        widgets = {"email": forms.EmailInput(attrs={"autocomplete": "email"})}

    def clean_email(self):
        email = User.objects.normalize_email(self.cleaned_data["email"]).lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("An account with this email already exists.")
        return email

    def clean_password2(self):
        password1 = self.cleaned_data.get("password1")
        password2 = self.cleaned_data.get("password2")
        if password1 and password2 and password1 != password2:
            raise forms.ValidationError("Your two passwords do not match.")
        validate_password(password2, self.instance)
        return password2

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = User.objects.normalize_email(self.cleaned_data["email"]).lower()
        user.set_password(self.cleaned_data["password2"])
        user.role = User.Role.BUYER
        if commit:
            user.save()
        return user


class UserLoginForm(AuthenticationForm):
    """Django maps USERNAME_FIELD to email, so this authenticates by email."""

    username = forms.EmailField(
        label="Email",
        widget=forms.EmailInput(
            attrs={"autofocus": True, "autocomplete": "email", "placeholder": "you@example.com"}
        ),
    )
    password = forms.CharField(
        label="Password",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}),
    )


class UserProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = (
            "first_name",
            "last_name",
            "email",
            "phone",
            "address_line1",
            "address_line2",
            "city",
            "postal_code",
            "country",
        )
        widgets = {
            "email": forms.EmailInput(attrs={"readonly": True}),
            "address_line1": forms.TextInput(attrs={"placeholder": "Street and number"}),
            "address_line2": forms.TextInput(attrs={"placeholder": "Apartment, floor (optional)"}),
        }


class SellerOnboardingForm(forms.ModelForm):
    """Business details a seller submits to join the marketplace."""

    agree_terms = forms.BooleanField(
        label="I agree to the marketplace seller terms", required=True
    )

    class Meta:
        model = SellerProfile
        fields = (
            "business_name",
            "tagline",
            "description",
            "contact_email",
            "contact_phone",
            "business_address",
            "tax_id",
            "logo",
        )
        widgets = {
            "description": forms.Textarea(
                attrs={
                    "rows": 5,
                    "placeholder": "Tell shoppers what makes your store special.",
                }
            ),
            "business_address": forms.TextInput(
                attrs={"placeholder": "Street, city, country"}
            ),
            "logo": forms.ClearableFileInput(attrs={"accept": "image/*"}),
        }

    def clean_logo(self):
        logo = self.cleaned_data.get("logo")
        if logo and logo.size > 2 * 1024 * 1024:
            raise forms.ValidationError("Logo must be smaller than 2 MB.")
        return logo

    def clean_business_name(self):
        name = self.cleaned_data["business_name"].strip()
        qs = SellerProfile.objects.filter(business_name__iexact=name)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError("A store with this name already exists.")
        return name


class SellerSettingsForm(forms.ModelForm):
    """Store settings a seller can change after approval."""

    class Meta:
        model = SellerProfile
        fields = (
            "business_name",
            "tagline",
            "description",
            "contact_email",
            "contact_phone",
            "business_address",
            "tax_id",
            "logo",
            "banner",
        )
        widgets = {
            "description": forms.Textarea(attrs={"rows": 5}),
            "logo": forms.ClearableFileInput(attrs={"accept": "image/*"}),
            "banner": forms.ClearableFileInput(attrs={"accept": "image/*"}),
        }

    def clean_business_name(self):
        name = self.cleaned_data["business_name"].strip()
        qs = SellerProfile.objects.filter(business_name__iexact=name).exclude(
            pk=self.instance.pk
        )
        if qs.exists():
            raise forms.ValidationError("A store with this name already exists.")
        return name
