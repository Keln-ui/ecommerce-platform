from django import forms
from django.core.exceptions import ValidationError

from catalog.models import Product

from .models import Order


class CartAddForm(forms.Form):
    product_id = forms.IntegerField()
    quantity = forms.IntegerField(min_value=1, max_value=99, initial=1)

    def clean_product_id(self):
        product = Product.objects.filter(
            pk=self.cleaned_data["product_id"]
        ).first()
        if product is None:
            raise ValidationError("That product does not exist.")
        if not product.is_purchasable:
            raise ValidationError("This product is not available right now.")
        return product


class CartUpdateForm(forms.Form):
    item_id = forms.IntegerField()
    quantity = forms.IntegerField(min_value=0, max_value=99)


class CheckoutForm(forms.ModelForm):
    """Delivery details, prefilled from the buyer's saved profile."""

    name = forms.CharField(max_length=150)
    phone = forms.CharField(max_length=32, required=False)
    address = forms.CharField(
        widget=forms.Textarea(
            attrs={"rows": 3, "placeholder": "Street, city, postal code, country"}
        )
    )
    payment_method = forms.ChoiceField(
        choices=[
            ("COD", "Cash on delivery"),
            ("BANK", "Bank transfer"),
            ("CARD", "Card (demo)"),
        ],
        initial="COD",
    )
    notes = forms.CharField(
        max_length=255, required=False, widget=forms.TextInput(attrs={"placeholder": "Optional"})
    )

    class Meta:
        model = Order
        fields = ("name", "phone", "address", "payment_method", "notes")

    def __init__(self, *args, **kwargs):
        user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)
        if user is not None and not self.is_bound:
            self.fields["name"].initial = user.display_name
            self.fields["phone"].initial = user.phone
            self.fields["address"].initial = user.shipping_address

    def clean_address(self):
        address = self.cleaned_data["address"].strip()
        if len(address) < 10:
            raise ValidationError("Please enter a complete delivery address.")
        return address
