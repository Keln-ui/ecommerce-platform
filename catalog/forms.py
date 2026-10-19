from django import forms

from .models import Category, Product, ProductImage, Review


class CategoryForm(forms.ModelForm):
    class Meta:
        model = Category
        fields = ("name", "parent", "description", "icon", "display_order", "is_active")


class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = (
            "category",
            "name",
            "sku",
            "short_description",
            "description",
            "price",
            "compare_at_price",
            "stock",
            "low_stock_threshold",
            "free_shipping",
            "is_active",
            "is_featured",
        )
        widgets = {"description": forms.Textarea(attrs={"rows": 6})}

    def clean_sku(self):
        sku = self.cleaned_data["sku"].strip().upper()
        qs = Product.objects.filter(sku__iexact=sku)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError("This SKU is already used by another product.")
        return sku

    def clean(self):
        """Cross-field check.

        This must live in Form.clean(), not clean_price: Django cleans fields in
        declaration order, so compare_at_price is not yet in cleaned_data while
        clean_price runs, and a check there would silently never fire.
        """
        cleaned = super().clean()
        price = cleaned.get("price")
        compare_at = cleaned.get("compare_at_price")
        if price is not None and compare_at is not None and compare_at <= price:
            self.add_error(
                "compare_at_price",
                "The compare-at price must be higher than the selling price.",
            )
        return cleaned


class ProductImageForm(forms.ModelForm):
    class Meta:
        model = ProductImage
        fields = ("image", "alt_text", "is_primary", "display_order")
        widgets = {"image": forms.ClearableFileInput(attrs={"accept": "image/*"})}

    def clean_image(self):
        image = self.cleaned_data.get("image")
        if image and image.size > 5 * 1024 * 1024:
            raise forms.ValidationError("Image must be smaller than 5 MB.")
        return image


class ReviewForm(forms.ModelForm):
    class Meta:
        model = Review
        fields = ("rating", "title", "comment")
        widgets = {
            "comment": forms.Textarea(
                attrs={
                    "rows": 4,
                    "placeholder": "How was the product and the seller?",
                }
            )
        }

    def clean_rating(self):
        rating = self.cleaned_data["rating"]
        if not 1 <= rating <= 5:
            raise forms.ValidationError("Rating must be between 1 and 5.")
        return rating
