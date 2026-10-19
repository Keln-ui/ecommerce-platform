"""Populate the marketplace with demo sellers, categories, products and orders.

Idempotent: running it twice will not duplicate data. Use --reset to start over.
"""

import random
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from accounts.models import SellerProfile
from catalog.models import Category, Product, Review
from orders.models import Cart, CartItem, Order, OrderItem
from orders.services import place_orders

User = get_user_model()

PASSWORD = "demo12345"

ADMIN_EMAIL = "admin@marketplace.test"

CATEGORIES = [
    ("Electronics", "Devices, audio and accessories", "\U0001f4f1"),
    ("Home & Kitchen", "Everything for your kitchen and home", "\U0001f3e1"),
    ("Fashion", "Clothing, shoes and accessories", "\U0001f455"),
    ("Books", "Fiction, reference and study", "\U0001f4da"),
    ("Sports", "Fitness, outdoor and team sports", "\u26bd"),
    ("Handmade", "Crafted goods from independent makers", "\U0001f528"),
]

# business_name, tagline, description, email, city, [(product, category, price, was, stock, featured)]
SELLERS = [
    (
        "Voltify Electronics",
        "Gadgets that actually last",
        "We repair, refurbish and sell tested electronics with honest warranties. "
        "Every device is bench-checked before it ships.",
        "hello@voltify.test",
        "Manchester",
        [
            ("Wireless Noise-Cancelling Headphones", "Electronics", "249.99", "299.00", 42, True),
            ("USB-C Fast Charger 65W", "Electronics", "34.50", "44.99", 120, False),
            ("Mechanical Keyboard TKL", "Electronics", "89.00", None, 30, False),
            ("4K Action Camera", "Electronics", "219.00", "259.00", 12, True),
        ],
    ),
    (
        "Hearth & Hand",
        "Cast iron, ceramics and slow mornings",
        "A small family workshop making cast iron pans and stoneware mugs. "
        "Everything is finished by hand in our workshop.",
        "orders@hearthandhand.test",
        "Stoke-on-Trent",
        [
            ("Cast Iron Skillet 26cm", "Home & Kitchen", "58.00", "72.00", 25, False),
            ("Stoneware Coffee Mug Set", "Home & Kitchen", "24.00", None, 64, True),
            ("Hand-Thrown Serving Bowl", "Home & Kitchen", "31.50", None, 18, False),
        ],
    ),
    (
        "Northbound Outfitters",
        "Gear for the long way round",
        "Sustainable outdoor clothing and packable gear, built for wet weather and "
        "multi-day hikes.",
        "team@northbound.test",
        "Glasgow",
        [
            ("Waterproof Shell Jacket", "Fashion", "175.00", "210.00", 38, False),
            ("Packable Travel Duffel", "Sports", "68.00", None, 22, True),
            ("Merino Base Layer", "Fashion", "49.00", "59.00", 75, False),
        ],
    ),
    (
        "Inkbound Books",
        "New, used and out-of-print",
        "A secondhand bookshop with a careful eye. We grade every book and list its "
        "true condition.",
        "hello@inkbound.test",
        "Dublin",
        [
            ("The Pragmatic Programmer, 2nd Edition", "Books", "32.00", None, 20, True),
            ("Collected Short Stories", "Books", "14.50", "19.99", 55, False),
            ("Hardcover Design Classics Box", "Books", "46.00", None, 9, False),
        ],
    ),
    (
        "Clay & Kiln Studio",
        "Small-batch ceramics",
        "Two potters, one kiln, a lot of wobble. Every piece is one of a kind.",
        "studio@clayandkiln.test",
        "Bristol",
        [
            ("Handmade Ceramic Planter", "Handmade", "28.00", "35.00", 16, False),
            ("Speckled Espresso Cup", "Handmade", "19.00", None, 40, True),
            ("Glazed Serving Platter", "Handmade", "42.00", None, 11, False),
        ],
    ),
    (
        "Summit Fitness",
        "Gear that earns its shelf space",
        "Strength and conditioning equipment with honest specifications and fast "
        "delivery.",
        "sales@summitfitness.test",
        "Leeds",
        [
            ("Adjustable Kettlebell 20kg", "Sports", "119.00", "139.00", 27, False),
            ("Yoga Mat Pro 6mm", "Sports", "38.00", None, 88, False),
            ("Resistance Band Set", "Sports", "24.00", "29.99", 130, False),
        ],
    ),
]

BUYERS = [
    ("Ada", "Lovelace", "ada@marketplace.test"),
    ("Grace", "Hopper", "grace@marketplace.test"),
    ("Linus", "Torvalds", "linus@marketplace.test"),
    ("Mary", "Jackson", "mary@marketplace.test"),
]

REVIEW_TITLES = [
    "Exactly as described",
    "Great quality",
    "Fast delivery",
    "Would buy again",
    "Good value for money",
    "Packaging could be better",
    "Happy with the purchase",
]

REVIEW_BODIES = [
    "Arrived well packed and in good condition.",
    "Quality is better than I expected at this price.",
    "The seller answered my questions quickly, I will order again.",
    "Does the job, no complaints.",
    "Slight delay in shipping but worth it.",
]


class Command(BaseCommand):
    help = "Seed the database with demo sellers, categories, products, reviews and orders."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Delete existing products, orders, carts and seller profiles first.",
        )
        parser.add_argument(
            "--orders",
            action="store_true",
            help="Also place demo orders so the fulfilment flow has data.",
        )
        parser.add_argument("--seed", type=int, default=42, help="RNG seed for reproducibility.")

    @transaction.atomic
    def handle(self, *args, **options):
        rng = random.Random(options["seed"])

        if options["reset"]:
            self._reset()

        self._create_admin()
        categories = self._create_categories()
        sellers = self._create_sellers(categories, rng)
        buyers = self._create_buyers(sellers, rng)
        self._create_reviews(buyers, rng)

        if options["orders"]:
            self._create_orders(buyers, rng)

        self._summary()

    # --------------------------------------------------------------- helpers

    def _reset(self):
        OrderItem.objects.all().delete()
        Order.objects.all().delete()
        CartItem.objects.all().delete()
        Cart.objects.all().delete()
        Review.objects.all().delete()
        Product.objects.all().delete()
        SellerProfile.objects.all().delete()
        User.objects.filter(is_superuser=False).delete()
        self.stdout.write(self.style.WARNING("Existing demo data removed."))

    def _create_admin(self):
        admin, created = User.objects.get_or_create(
            email=ADMIN_EMAIL,
            defaults={
                "first_name": "Marketplace",
                "last_name": "Admin",
                "is_staff": True,
                "is_superuser": True,
                "role": User.Role.STAFF,
            },
        )
        if created:
            admin.set_password(PASSWORD)
            admin.save()
        self.stdout.write(f"Admin  : {ADMIN_EMAIL} / {PASSWORD}")

    def _create_categories(self):
        made = 0
        for order, (name, description, icon) in enumerate(CATEGORIES):
            _obj, was_created = Category.objects.get_or_create(
                name=name,
                defaults={
                    "description": description,
                    "icon": icon,
                    "display_order": order,
                    "slug": slugify(name)[:140],
                },
            )
            made += int(was_created)
        self.stdout.write(f"Categories: {Category.objects.count()} ({made} new)")
        return list(Category.objects.all())

    def _create_sellers(self, categories, rng):
        by_name = {c.name: c for c in categories}

        for business_name, tagline, description, email, city, products in SELLERS:
            user, created = User.objects.get_or_create(
                email=email,
                defaults={
                    "first_name": business_name.split()[0],
                    "last_name": "Seller",
                    "role": User.Role.SELLER,
                    "phone": f"+44 7{rng.randint(100, 999)} {rng.randint(100000, 999999)}",
                    "city": city,
                    "country": "United Kingdom",
                    "address_line1": f"{rng.randint(1, 200)} High Street",
                },
            )
            if created:
                user.set_password(PASSWORD)
                user.save()

            store, _ = SellerProfile.objects.get_or_create(
                user=user,
                defaults={
                    "business_name": business_name,
                    "tagline": tagline,
                    "description": description,
                    "status": SellerProfile.Status.APPROVED,
                    "approved_at": timezone.now(),
                    "contact_email": email,
                    "business_address": f"{user.address_line1}, {city}",
                    "is_active": True,
                },
            )

            prefix = slugify(business_name)[:6].upper()
            for index, (name, cat_name, price, was, stock, featured) in enumerate(products):
                Product.objects.get_or_create(
                    seller=store,
                    sku=f"{prefix}-{index + 100}",
                    defaults={
                        "name": name,
                        "category": by_name[cat_name],
                        "short_description": f"{name}, sold by {business_name}.",
                        "description": (
                            f"{name}\n\n{tagline}. {description}"
                        ),
                        "price": Decimal(price),
                        "compare_at_price": Decimal(was) if was else None,
                        "stock": stock,
                        "low_stock_threshold": 5,
                        "is_active": True,
                        "is_featured": featured,
                        "free_shipping": rng.random() < 0.25,
                    },
                )

        sellers = list(SellerProfile.objects.filter(user__role=User.Role.SELLER))
        self.stdout.write(f"Sellers : {len(sellers)}")
        return sellers

    def _create_buyers(self, sellers, rng):
        for first, last, email in BUYERS:
            user, created = User.objects.get_or_create(
                email=email,
                defaults={
                    "first_name": first,
                    "last_name": last,
                    "role": User.Role.BUYER,
                    "phone": f"+44 7{rng.randint(100, 999)} {rng.randint(100000, 999999)}",
                    "address_line1": f"{rng.randint(1, 180)} Elm Road",
                    "city": "Nottingham",
                    "postal_code": "NG1 2AB",
                    "country": "United Kingdom",
                },
            )
            if created:
                user.set_password(PASSWORD)
                user.save()

        buyers = list(User.objects.filter(role=User.Role.BUYER))
        self.stdout.write(f"Buyers  : {len(buyers)}")
        return buyers

    def _create_reviews(self, buyers, rng):
        products = list(Product.objects.all())
        made = 0

        for product in products:
            reviewers = rng.sample(buyers, k=min(len(buyers), rng.randint(0, 3)))
            for reviewer in reviewers:
                _obj, was_created = Review.objects.get_or_create(
                    product=product,
                    user=reviewer,
                    defaults={
                        "rating": rng.choices([5, 4, 3, 2, 1], weights=[45, 30, 15, 6, 4])[0],
                        "title": rng.choice(REVIEW_TITLES),
                        "comment": rng.choice(REVIEW_BODIES),
                        "is_approved": True,
                    },
                )
                made += int(was_created)

        for seller in SellerProfile.objects.all():
            seller.recalculate_rating()

        self.stdout.write(f"Reviews : {made} new ({Review.objects.count()} total)")

    def _create_orders(self, buyers, rng):
        products = list(Product.objects.live().for_display().filter(stock__gt=5))
        if not products:
            self.stdout.write(self.style.WARNING("No products available to order."))
            return

        placed = 0
        for buyer in buyers:
            # Only seed orders for buyers that have none, so re-runs are safe.
            if Order.objects.filter(buyer=buyer).exists():
                continue

            cart, _ = Cart.objects.get_or_create(user=buyer)
            for product in rng.sample(products, k=min(len(products), rng.randint(2, 4))):
                CartItem.objects.create(
                    cart=cart, product=product, quantity=rng.randint(1, min(3, product.stock))
                )

            if not cart.items.exists():
                continue

            try:
                orders = place_orders(
                    buyer,
                    {
                        "name": buyer.display_name,
                        "phone": buyer.phone,
                        "address": (
                            f"{buyer.address_line1}, {buyer.city}, "
                            f"{buyer.postal_code}, {buyer.country}"
                        ),
                    },
                )
                placed += len(orders)
            except ValueError as exc:
                self.stderr.write(f"Skipped order for {buyer.email}: {exc}")

        self.stdout.write(self.style.SUCCESS(f"Orders  : {placed} created"))

    def _summary(self):
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Demo data ready."))
        self.stdout.write(f"  Products : {Product.objects.count()}")
        self.stdout.write(
            f"  Sellers  : {SellerProfile.objects.filter(status=SellerProfile.Status.APPROVED).count()} approved"
        )
        self.stdout.write(f"  Orders   : {Order.objects.count()}")
        self.stdout.write(f"  Password : {PASSWORD} for every demo user")
