from django.conf import settings
from django.contrib.auth.base_user import BaseUserManager
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.urls import reverse
from django.utils.text import slugify
from django.utils import timezone


class UserManager(BaseUserManager):
    """Creates users keyed by email address."""

    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        if not email:
            raise ValueError("An email address is required.")
        email = self.normalize_email(email).lower()
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")
        return self._create_user(email, password, **extra_fields)


class User(AbstractUser):
    class Role(models.TextChoices):
        BUYER = "BUYER", "Buyer"
        SELLER = "SELLER", "Seller"
        STAFF = "STAFF", "Administrator"

    # There is no username: email is the login identifier.
    username = models.CharField(max_length=150, blank=True, null=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["first_name", "last_name"]

    email = models.EmailField("email address", unique=True)
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.BUYER)
    phone = models.CharField(max_length=32, blank=True)
    address_line1 = models.CharField(max_length=255, blank=True)
    address_line2 = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=100, blank=True)
    postal_code = models.CharField(max_length=20, blank=True)
    country = models.CharField(max_length=100, blank=True)

    objects = UserManager()

    class Meta:
        ordering = ["-date_joined"]

    def __str__(self):
        return self.get_full_name() or self.email

    def get_absolute_url(self):
        if self.can_sell:
            return reverse("sellers:dashboard")
        return reverse("accounts:profile")

    @property
    def is_seller(self):
        return self.role == self.Role.SELLER

    @property
    def seller_profile(self):
        """The related SellerProfile, or None when this user is not a seller."""
        return getattr(self, "seller_store", None)

    @property
    def can_sell(self):
        """Only approved sellers with an active storefront may publish products."""
        store = self.seller_profile
        return bool(
            store and store.is_active and store.status == SellerProfile.Status.APPROVED
        )

    @property
    def display_name(self):
        return self.get_full_name() or self.email

    @property
    def shipping_address(self):
        parts = [
            self.address_line1,
            self.address_line2,
            self.city,
            self.postal_code,
            self.country,
        ]
        return ", ".join(p for p in parts if p)


class SellerProfile(models.Model):
    """A storefront owned by one user."""

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending review"
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"
        SUSPENDED = "SUSPENDED", "Suspended"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="seller_store",
    )
    business_name = models.CharField(max_length=150)
    slug = models.SlugField(max_length=160, unique=True, blank=True)
    tagline = models.CharField(max_length=200, blank=True)
    description = models.TextField(blank=True)
    logo = models.ImageField(upload_to="sellers/logos/", blank=True, null=True)
    banner = models.ImageField(upload_to="sellers/banners/", blank=True, null=True)

    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.PENDING
    )
    is_active = models.BooleanField(
        default=True, help_text="Uncheck to close the storefront without deleting it."
    )
    rejection_reason = models.CharField(max_length=255, blank=True)

    contact_email = models.EmailField(blank=True)
    contact_phone = models.CharField(max_length=32, blank=True)
    business_address = models.CharField(max_length=255, blank=True)
    tax_id = models.CharField(max_length=64, blank=True)

    rating_average = models.DecimalField(max_digits=3, decimal_places=2, default=0)
    rating_count = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    approved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["business_name"]
        indexes = [models.Index(fields=["status", "is_active"])]

    def __str__(self):
        return self.business_name

    def get_absolute_url(self):
        return reverse("catalog:seller_detail", kwargs={"slug": self.slug})

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = self._unique_slug()
        super().save(*args, **kwargs)

    def _unique_slug(self):
        base = slugify(self.business_name)[:140] or "store"
        slug = base
        counter = 2
        while SellerProfile.objects.filter(slug=slug).exclude(pk=self.pk).exists():
            slug = f"{base}-{counter}"
            counter += 1
        return slug

    @property
    def is_approved(self):
        return self.status == self.Status.APPROVED and self.is_active

    @property
    def active_product_count(self):
        return self.products.filter(is_active=True).count()

    def recalculate_rating(self):
        """Average rating across approved reviews of this seller's products."""
        from django.db.models import Avg, Count

        from catalog.models import Review

        stats = Review.objects.filter(
            product__seller=self, is_approved=True
        ).aggregate(average=Avg("rating"), count=Count("id"))
        self.rating_average = stats["average"] or 0
        self.rating_count = stats["count"]
        self.save(update_fields=["rating_average", "rating_count"])


class SubscriptionPlan(models.Model):
    """Admin-configured subscription plans for sellers."""
    
    PLAN_CHOICES = [
        ("MONTHLY", "Monthly"),
        ("YEARLY", "Yearly"),
    ]
    
    name = models.CharField(max_length=100)
    plan_type = models.CharField(max_length=10, choices=PLAN_CHOICES)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ["price"]
        verbose_name = "Subscription Plan"
        verbose_name_plural = "Subscription Plans"
    
    def __str__(self):
        return f"{self.name} ({self.plan_type}) - KSh {self.price}"


class SellerSubscription(models.Model):
    """Track seller subscription payments and status."""
    
    STATUS_CHOICES = [
        ("ACTIVE", "Active"),
        ("EXPIRED", "Expired"),
        ("CANCELLED", "Cancelled"),
        ("PENDING", "Pending Payment"),
    ]
    
    seller = models.OneToOneField(
        SellerProfile,
        on_delete=models.CASCADE,
        related_name="subscription"
    )
    plan = models.ForeignKey(
        SubscriptionPlan,
        on_delete=models.PROTECT,
        related_name="subscriptions"
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="PENDING")
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    auto_renew = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "Seller Subscription"
        verbose_name_plural = "Seller Subscriptions"
    
    def __str__(self):
        return f"{self.seller.business_name} - {self.plan.name}"
    
    @property
    def is_active(self):
        if self.status != "ACTIVE":
            return False
        if self.end_date and self.end_date < timezone.now().date():
            return False
        return True
    
    def activate(self):
        """Activate the subscription for the plan period."""
        from datetime import timedelta
        self.status = "ACTIVE"
        self.start_date = timezone.now().date()
        
        if self.plan.plan_type == "MONTHLY":
            self.end_date = self.start_date + timedelta(days=30)
        else:  # YEARLY
            self.end_date = self.start_date + timedelta(days=365)
        
        self.save()
    
    def check_expiry(self):
        """Check if subscription has expired and update status."""
        if self.end_date and self.end_date < timezone.now().date():
            self.status = "EXPIRED"
            self.save()
