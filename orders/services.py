"""Cart and checkout logic.

The important rule here: a buyer's cart may span several stores, but each seller
owns their own fulfilment. `place_orders` therefore creates one Order per seller.
"""

from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.db.models import F

from catalog.models import Product

from .models import Cart, CartItem, Order, OrderItem


def get_or_create_cart(user):
    cart, _ = Cart.objects.get_or_create(user=user)
    return cart


def add_to_cart(user, product, quantity=1):
    """Add a product to the cart, clamped to available stock.

    Returns (cart, added_quantity, error_message).
    """
    if quantity < 1:
        return None, 0, "Quantity must be at least 1."
    if not product.is_purchasable:
        return None, 0, "This product is not available right now."
    if product.stock <= 0:
        return None, 0, "This product is out of stock."

    cart = get_or_create_cart(user)

    # A new line must start at exactly `quantity`. Passing defaults keeps
    # get_or_create from inserting the model's default of 1 and then adding on top.
    item, created = CartItem.objects.get_or_create(
        cart=cart, product=product, defaults={"quantity": quantity}
    )
    if created:
        return cart, quantity, ""

    desired = item.quantity + quantity
    if desired > product.stock:
        item.quantity = product.stock
        item.save(update_fields=["quantity"])
        return cart, 0, f"Only {product.stock} left in stock."

    item.quantity = desired
    item.save(update_fields=["quantity"])
    return cart, quantity, ""


def get_cart_item(user, item_id):
    cart = get_or_create_cart(user)
    return CartItem.objects.filter(cart=cart, pk=item_id).first()


def set_cart_item_quantity(user, item_id, quantity):
    """Set an exact quantity. Zero removes the line. Returns (ok, error_message)."""
    item = get_cart_item(user, item_id)
    if item is None:
        return False, "That item is no longer in your cart."

    if quantity < 1:
        item.delete()
        return True, "Item removed from your cart."

    if quantity > item.product.stock:
        item.quantity = item.product.stock
        item.save(update_fields=["quantity"])
        return False, f"Only {item.product.stock} left in stock."

    item.quantity = quantity
    item.save(update_fields=["quantity"])
    return True, ""


@transaction.atomic
def place_orders(user, shipping_data, payment_method="COD"):
    """Turn the cart into one Order per seller.

    Products are re-read with row locks so concurrent checkouts cannot oversell.
    Raises ValueError with a shopper-friendly reason if stock ran out.
    """
    cart = get_or_create_cart(user)
    groups = cart.group_by_seller()
    if not groups:
        raise ValueError("Your cart is empty.")

    # Shipping is resolved per seller group, since free shipping is item-aware.
    rate = Decimal(str(settings.MARKETPLACE["COMMISSION_RATE"]))
    if rate >= 100:
        rate = Decimal("0")

    orders = []
    for seller, group in groups.items():
        locked_lines = [
            CartItem.objects.select_for_update()
            .select_related("product")
            .get(pk=line.pk)
            for line in group["items"]
        ]

        subtotal = Decimal("0.00")
        snapshot = []
        for line in locked_lines:
            product = Product.objects.select_for_update().get(pk=line.product_id)
            if product.stock < line.quantity:
                raise ValueError(
                    f'"{product.name}" only has {product.stock} left in stock.'
                )
            subtotal += product.price * line.quantity
            snapshot.append((product, line.quantity))

        commission = (subtotal * rate / Decimal("100")).quantize(Decimal("0.01"))

        order = Order.objects.create(
            buyer=user,
            seller=seller,
            status=Order.Status.PAID,
            payment_status=Order.PaymentStatus.PAID,
            payment_method=payment_method,
            subtotal=subtotal,
            shipping_fee=group["shipping"],
            commission=commission,
            total=subtotal + group["shipping"],
            ship_to_name=shipping_data.get("name") or user.display_name,
            ship_to_phone=shipping_data.get("phone") or user.phone,
            ship_to_address=shipping_data.get("address") or user.shipping_address,
            notes=shipping_data.get("notes", ""),
        )

        for product, quantity in snapshot:
            image = product.primary_image
            OrderItem.objects.create(
                order=order,
                product=product,
                product_name=product.name,
                product_sku=product.sku,
                product_image=image.image if image else None,
                unit_price=product.price,
                quantity=quantity,
                line_total=product.price * quantity,
            )
            Product.objects.filter(pk=product.pk).update(
                stock=F("stock") - quantity,
                units_sold=F("units_sold") + quantity,
            )

        orders.append(order)

    cart.items.all().delete()
    return orders


def cancel_order(order, restock=True):
    """Cancel an order, returning stock to the seller when possible."""
    if not order.is_cancellable:
        return False, f"Order {order.order_number} can no longer be cancelled."

    order.status = Order.Status.CANCELLED
    order.save(update_fields=["status", "updated_at"])

    if restock:
        for item in order.items.all():
            if item.product_id:
                Product.objects.filter(pk=item.product_id).update(
                    stock=F("stock") + item.quantity,
                    units_sold=F("units_sold") - item.quantity,
                )

    return True, f"Order {order.order_number} was cancelled."
