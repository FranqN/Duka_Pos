# Product data model and storage
# For simplicity, we'll use an in-memory list. Later, you can switch to a database.

class Product:
    def __init__(self, id, name, price, stock):
        self.id = id
        self.name = name
        self.price = price
        self.stock = stock

products = []

# Helper functions

def add_product(name, price, stock):
    new_id = len(products) + 1
    product = Product(new_id, name, price, stock)
    products.append(product)
    return product

def get_product(product_id):
    for product in products:
        if product.id == product_id:
            return product
    return None

def update_product(product_id, name=None, price=None, stock=None):
    product = get_product(product_id)
    if product:
        if name is not None:
            product.name = name
        if price is not None:
            product.price = price
        if stock is not None:
            product.stock = stock
        return product
    return None

def delete_product(product_id):
    global products
    products = [p for p in products if p.id != product_id]

