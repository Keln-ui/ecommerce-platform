# MultiVendor Market

A multi-vendor e-commerce marketplace built with Django. Independent sellers
onboard themselves, get their own storefront, list products and fulfil orders.
Buyers shop across every store and check out once.

## Setup

```bash
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_demo --orders     # optional demo data
python manage.py runserver
```

- Storefront: http://127.0.0.1:8000/
- Admin: http://127.0.0.1:8000/admin/

### Demo accounts

All demo users share the password `demo12345`.

| Role | Email | Notes |
| --- | --- | --- |
| Admin | `admin@marketplace.test` | Full admin access |
| Buyer | `ada@marketplace.test`, `grace@…`, `linus@…`, `mary@…` | Shopping and order history |
| Seller | `hello@voltify.test`, `orders@hearthandhand.test`, … | Storefront and fulfilment |

**Accounts are identified by email address — there is no username.** Sign-up,
log-in and the admin all use the email field.

### Opening your own store

1. Sign up at `/register/`
2. Choose **Sell with us** (or visit `/sell/`) and submit your business details
3. With `AUTO_APPROVE_SELLERS = True` the store goes live immediately. Set it
   to `False` to require an administrator to approve each seller first.
4. Add products from the seller dashboard at `/seller/`

## Features

**Buyers**
- Home page with featured products, new arrivals and highlighted stores
- Browse by category, search across products *and* store names
- Filter by price range, minimum rating, in-stock and on-sale; sort six ways
- Product pages with image gallery, stock warnings, discount badges, reviews
- Leave one review per product
- Cart grouped by seller, with per-store subtotal and shipping
- Checkout that splits into one order per seller
- Order history with status timeline and self-service cancellation

**Sellers**
- Self-service onboarding: business profile, logo, auto-generated storefront slug
- Approval states: `PENDING`, `APPROVED`, `REJECTED`, `SUSPENDED`
- Product CRUD with images, SKU, stock thresholds, compare-at pricing,
  free-shipping flag, featured flag
- Inventory table with live / hidden / out-of-stock states and stock alerts
- Order queue with guarded fulfilment: `PAID` → `PROCESSING` → `SHIPPED` →
  `DELIVERED`, plus cancellation that restores stock
- Dashboard: revenue, commission, payout, best sellers, orders awaiting action
- Editable store settings and a public storefront page

**Administrators**
- Django admin for users, sellers, categories, products, reviews, orders, carts
- Bulk approve / suspend / reject sellers and approve reviews

## The core design decision: one order per seller

A buyer's cart can span many stores, but each seller owns their own fulfilment.
A single checkout therefore creates **one `Order` per seller**:

```
Cart (7 lines, 6 sellers)
   |
   +-- Clay & Kiln Studio  -> Order 1  sub 122.00  comm 9.76  ship 4.99  total 126.99
   +-- Hearth & Hand       -> Order 2  sub  63.00  comm 5.04  ship 0.00  total  63.00
   +-- Inkbound Books      -> Order 3  sub  92.00  comm 7.36  ship 4.99  total  96.99
   ...
```

Money is computed per order in `orders/services.py`:

```
commission = round(subtotal * COMMISSION_RATE / 100)
total      = subtotal + shipping_fee
payout     = subtotal - commission        # what the seller earns
```

Shipping is charged once per seller order, and waived when every item in that
order is flagged free shipping.

**Order items are snapshots.** Each `OrderItem` copies the product name, SKU,
image and unit price, and the product FK is `ON DELETE SET NULL`. If a seller
later renames, repriced or deleted a product, historical orders still render
correctly.

## Correctness properties

- **No overselling.** `place_orders` runs in a transaction and re-reads each
  product with `select_for_update()` before pricing and decrementing stock. If
  stock ran out it raises and the whole checkout rolls back.
- **Seller isolation.** Every seller query is scoped to
  `request.user.seller_store`, so one seller gets a 404 for another's products
  and orders rather than seeing them.
- **Guarded fulfilment.** `Order.ALLOWED_TRANSITIONS` defines the legal status
  moves. A seller cannot skip `PAID` straight to `DELIVERED`, and shipping
  requires a tracking number.
- **Cancellation restores stock** and decrements `units_sold`.
- **Unapproved sellers are invisible.** `Product.objects.live()` filters on both
  `is_active` and the seller's approval status, so products, storefronts and
  direct links are all hidden until approved.

## Configuration

Everything marketplace-specific is one dict in `marketplace/settings.py`:

```python
MARKETPLACE = {
    "AUTO_APPROVE_SELLERS": True,   # False = require admin approval
    "COMMISSION_RATE": 8,           # percent retained by the platform
    "SHIPPING_FEE": 4.99,           # flat fee per seller order
    "TAX_RATE": 0,
    "PRODUCTS_PER_PAGE": 12,
}
```

## Layout

```
marketplace/   settings, root URLconf
accounts/      User (email login), SellerProfile, onboarding, auth views
catalog/       Category, Product, ProductImage, Review, storefront + seller views
orders/        Cart, Order, OrderItem, checkout/fulfilment services
templates/     base layout, storefront, accounts, cart/checkout, seller area
static/css/    single stylesheet
```

Seller views live in `catalog` and `orders` because they operate on those
models, but they are exposed under a clean `/seller/` namespace by
`marketplace/urls.py`.

## Seed command

```bash
python manage.py seed_demo                   # idempotent, keeps existing data
python manage.py seed_demo --reset           # wipe and rebuild demo data
python manage.py seed_demo --reset --orders  # also place demo orders
python manage.py seed_demo --seed 7          # reproducible randomness
```

Running it twice will not duplicate data.

## Before deploying

This runs on SQLite with `DEBUG = True` for local development. For production:

- Set `DEBUG = False` and a real `SECRET_KEY`
- Move uploaded media to object storage (S3 or similar)
- Switch to PostgreSQL
- Serve static files via `collectstatic` and a CDN
- Replace the demo payment step with a real gateway
- Set `AUTO_APPROVE_SELLERS = False` if you want to vet sellers manually
