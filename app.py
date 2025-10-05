from flask import Flask, request, render_template, redirect, url_for, session, flash
from flask_cors import CORS
from config import Config
from models import db, Product, User, Sale, AuditLog, Setting, Category, Supplier, SupplierOrder, ProductHistory
from sqlalchemy import func, desc
import os
from werkzeug.utils import secure_filename
import csv
import io
import json
from flask import send_file, make_response
from io import BytesIO
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from flask import send_file

app = Flask(__name__)
app.config.from_object(Config)
app.secret_key = 'replace-this-with-a-secure-key'
db.init_app(app)
CORS(app)

with app.app_context():
    db.create_all()

UPLOAD_FOLDER = 'static/uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def login_required(role=None):
    def decorator(f):
        from functools import wraps
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'user_id' not in session:
                return redirect(url_for('login'))
            if role and session.get('role') != role:
                flash('You do not have permission to access this page.', 'danger')
                return redirect(url_for('home'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator

@app.route('/')
def home():
    return render_template('landing.html')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        role = request.form.get('role', 'staff')
        if User.query.filter_by(username=username).first():
            flash('Username already exists.', 'danger')
            return redirect(url_for('signup'))
        user = User(username=username, role=role)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        flash('Account created! Please log in.', 'success')
        return redirect(url_for('login'))
    return render_template('signup.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            session['user_id'] = user.id
            session['username'] = user.username
            session['role'] = user.role
            flash('Logged in successfully!', 'success')
            return redirect(url_for('products_page'))
        flash('Invalid username or password.', 'danger')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('Logged out.', 'info')
    return redirect(url_for('home'))

@app.route('/products', methods=['GET', 'POST'])
@login_required()
def products_page():
    can_edit = session.get('role') == 'admin'
    search = request.args.get('search', '')
    category_id = request.args.get('category', type=int)
    supplier_id = request.args.get('supplier', type=int)
    stock_status = request.args.get('stock_status', '')
    sort = request.args.get('sort', '')
    page = request.args.get('page', 1, type=int)
    per_page = 10

    query = Product.query
    if search:
        query = query.filter(
            (Product.name.ilike(f'%{search}%')) |
            (Product.barcode.ilike(f'%{search}%')) |
            (Product.description.ilike(f'%{search}%'))
        )
    if category_id:
        query = query.filter(Product.category_id == category_id)
    if supplier_id:
        query = query.filter(Product.supplier_id == supplier_id)
    if stock_status == 'low':
        query = query.filter(Product.stock < 5)
    elif stock_status == 'out':
        query = query.filter(Product.stock == 0)
    if sort == 'name':
        query = query.order_by(Product.name)
    elif sort == 'price':
        query = query.order_by(Product.selling_price)
    elif sort == 'stock':
        query = query.order_by(Product.stock)

    products = query.paginate(page=page, per_page=per_page)
    categories = Category.query.all()
    suppliers = Supplier.query.all()
    units = ['KGs', 'Grams', 'Liters', 'Milliliters', 'Pieces', 'Bales', 'Packs', 'Boxes', 'Cartons', 'Dozens', 'Meters', 'Rolls', 'Bottles', 'Bags', 'Trays']

    return render_template('products.html',
        products=products,
        categories=categories,
        suppliers=suppliers,
        units=units,
        can_edit=can_edit,
        search=search,
        category_id=category_id,
        supplier_id=supplier_id,
        stock_status=stock_status,
        sort=sort,
        threshold=5  # For low stock badge
    )

@app.route('/products/edit/<int:product_id>', methods=['GET', 'POST'])
@login_required(role='admin')
def edit_product_page(product_id):
    units = ['KGs', 'Grams', 'Liters', 'Milliliters', 'Pieces', 'Bales', 'Packs', 'Boxes', 'Cartons', 'Dozens', 'Meters', 'Rolls', 'Bottles', 'Bags', 'Trays']
    product = Product.query.get_or_404(product_id)
    if request.method == 'POST':
        product.name = request.form['name']
        product.selling_price = float(request.form['selling_price'])
        product.stock = int(request.form['stock'])
        product.unit = request.form['unit']
        db.session.commit()
        return redirect(url_for('products_page'))
    return render_template('edit_product.html', product=product, units=units)

@app.route('/products/delete/<int:product_id>')
@login_required(role='admin')
def delete_product_page(product_id):
    product = Product.query.get_or_404(product_id)
    db.session.delete(product)
    db.session.commit()
    return redirect(url_for('products_page'))
@app.route('/products/import', methods=['POST'])
@login_required(role='admin')
def import_products():
    file = request.files['csv']
    if file:
        stream = io.StringIO(file.stream.read().decode("UTF8"), newline=None)
        reader = csv.DictReader(stream)
        for row in reader:
            product = Product(
                name=row['name'],
                price=float(row['price']),
                stock=int(row['stock']),
                unit=row['unit'],
                category_id=int(row['category_id']),
                supplier_id=int(row['supplier_id']),
                barcode=row.get('barcode'),
                image=row.get('image')
            )
            db.session.add(product)
        db.session.commit()
        flash('Products imported.', 'success')
    return redirect(url_for('products_page'))

@app.route('/products/export')
@login_required(role='admin')
def export_products():
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['id', 'name', 'price', 'stock', 'unit', 'category_id', 'supplier_id', 'barcode', 'image'])
    for p in Product.query.all():
        writer.writerow([p.id, p.name, p.price, p.stock, p.unit, p.category_id, p.supplier_id, p.barcode, p.image])
    output.seek(0)
    return send_file(
        io.BytesIO(output.getvalue().encode()),
        mimetype='text/csv',
        as_attachment=True,
        download_name='products.csv'
    )

@app.route('/products/<int:product_id>/history')
@login_required()
def product_history(product_id):
    product = Product.query.get_or_404(product_id)
    history = ProductHistory.query.filter_by(product_id=product.id).order_by(ProductHistory.timestamp.desc()).all()
    return render_template('product_history.html', product=product, history=history)

@app.route('/sales', methods=['GET', 'POST'])
@login_required()
def make_sale():
    products = Product.query.all()
    payment_methods = ['Cash', 'Mpesa', 'Other']
    if request.method == 'POST':
        product_id = request.form['product_id']
        quantity = int(request.form['quantity'])
        payment_method = request.form['payment_method']
        customer_name = request.form.get('customer_name', '')
        customer_contact = request.form.get('customer_contact', '')
        product = Product.query.get(product_id)
        if product and product.stock >= quantity:
            product.stock -= quantity
            total_price = product.selling_price * quantity
            profit = (product.selling_price - product.buying_price) * quantity
            sale = Sale(product_id=product_id, quantity=quantity, payment_method=payment_method, total_price=total_price, customer_name=customer_name, customer_contact=customer_contact, profit=profit)
            db.session.add(sale)
            db.session.commit()
            # Generate receipt data for preview (could be extended for PDF/print)
            receipt = {
                'product': product.name,
                'quantity': quantity,
                'total': total_price,
                'customer': customer_name,
                'contact': customer_contact,
                'payment_method': payment_method,
                'sale_id': sale.id
            }
            flash('Sale completed successfully!', 'success')
            return render_template('make_sale.html', products=products, payment_methods=payment_methods, receipt=receipt)
        else:
            flash('Insufficient stock!', 'danger')
            return render_template('make_sale.html', products=products, payment_methods=payment_methods)
    return render_template('make_sale.html', products=products, payment_methods=payment_methods)

@app.route('/sales/list')
@login_required(role='admin')
def sales_list():
    # Get all sales with product info
    sales = (
        db.session.query(Sale, Product)
        .join(Product, Sale.product_id == Product.id)
        .order_by(Sale.timestamp.desc())
        .all()
    )

    # Aggregate best performing products
    best_products = (
        db.session.query(
            Product.name,
            func.sum(Sale.quantity).label('total_sold'),
            func.sum(Sale.total_price).label('total_revenue')
        )
        .join(Sale, Sale.product_id == Product.id)
        .group_by(Product.id)
        .order_by(desc('total_sold'))
        .limit(5)
        .all()
    )

    # Total sales amount
    total_sales = db.session.query(func.sum(Sale.total_price)).scalar() or 0

    return render_template(
        'sales_list.html',
        sales=sales,
        best_products=best_products,
        total_sales=total_sales
    )

@app.route('/admin/users')
@login_required(role='admin')
def user_list():
    users = User.query.all()
    return render_template('user_list.html', users=users)

@app.route('/admin/users/edit/<int:user_id>', methods=['GET', 'POST'])
@login_required(role='admin')
def edit_user(user_id):
    user = User.query.get_or_404(user_id)
    if request.method == 'POST':
        if user.id == session['user_id']:
            flash("You can't change your own role.", 'danger')
            return redirect(url_for('user_list'))
        user.role = request.form['role']
        db.session.commit()
        flash('User role updated.', 'success')
        return redirect(url_for('user_list'))
    return render_template('edit_user.html', user=user)

@app.route('/admin/users/delete/<int:user_id>')
@login_required(role='admin')
def delete_user(user_id):
    user = User.query.get_or_404(user_id)
    if user.id == session['user_id']:
        flash("You can't delete your own account.", 'danger')
        return redirect(url_for('user_list'))
    db.session.delete(user)
    db.session.commit()
    flash('User deleted.', 'success')
    return redirect(url_for('user_list'))

@app.route('/admin/audit-logs')
@login_required(role='admin')
def audit_logs():
    logs = AuditLog.query.order_by(AuditLog.timestamp.desc()).all()
    return render_template('audit_logs.html', logs=logs)

@app.route('/admin/dashboard')
@login_required(role='admin')
def admin_dashboard():
    # Basic stats
    total_products = Product.query.count()
    total_users = User.query.count()
    total_sales = db.session.query(func.sum(Sale.total_price)).scalar() or 0

    # Expenses (sum of supplier orders marked as Delivered)
    total_expenses = db.session.query(func.sum(SupplierOrder.cost)).filter(SupplierOrder.status == 'Delivered').scalar() or 0

    # Sales trends (monthly for last 6 months)
    sales_trends = db.session.query(
        func.strftime('%Y-%m', Sale.timestamp).label('month'),
        func.sum(Sale.total_price)
    ).group_by('month').order_by('month').all()
    sales_trends_labels = [row[0] for row in sales_trends]
    sales_trends_data = [row[1] for row in sales_trends]

    # Inventory value over time (simulate with current value)
    inventory_value_labels = sales_trends_labels
    inventory_value_data = []
    for label in inventory_value_labels:
            value = db.session.query(func.sum(Product.selling_price * Product.stock)).scalar() or 0
            inventory_value_data.append(value)

    # Top products by sales
    top_products = db.session.query(
        Product.name,
        func.sum(Sale.quantity).label('units_sold')
    ).join(Sale, Sale.product_id == Product.id).group_by(Product.id).order_by(desc('units_sold')).limit(5).all()
    top_products_labels = [row[0] for row in top_products]
    top_products_data = [row[1] for row in top_products]

    # Payment method breakdown
    payment_methods = db.session.query(
        Sale.payment_method,
        func.sum(Sale.total_price)
    ).group_by(Sale.payment_method).all()
    payment_method_labels = [row[0] for row in payment_methods]
    payment_method_data = [row[1] for row in payment_methods]

    # Recent supplier orders
    recent_supplier_orders = SupplierOrder.query.order_by(SupplierOrder.order_date.desc()).limit(5).all()

    # Outstanding payments to suppliers (sum of costs for pending/delivered but not paid)
    outstanding_payments = []
    suppliers = Supplier.query.all()
    for supplier in suppliers:
        amount = db.session.query(func.sum(SupplierOrder.cost)).filter(
            SupplierOrder.supplier_id == supplier.id,
            SupplierOrder.status != 'Delivered'
        ).scalar() or 0
        if amount > 0:
            outstanding_payments.append((supplier, amount))

    # Supplier performance
    supplier_performance = []
    for supplier in suppliers:
        orders = SupplierOrder.query.filter_by(supplier_id=supplier.id).all()
        total_supplied = sum(order.quantity for order in orders)
        delivered_orders = [o for o in orders if o.status == 'Delivered']
        on_time = sum(1 for o in delivered_orders if o.delivery_date and o.delivery_date <= o.order_date)
        on_time_percent = int((on_time / len(delivered_orders) * 100) if delivered_orders else 0)
        supplier_performance.append({
            'name': supplier.name,
            'total_supplied': total_supplied,
            'on_time_percent': on_time_percent
        })

    # Cash flow summary (monthly revenue/expenses/profit)
    cash_flow = []
    months = sales_trends_labels
    for month in months:
        revenue = next((row[1] for row in sales_trends if row[0] == month), 0)
        expenses = db.session.query(func.sum(SupplierOrder.cost)).filter(
            func.strftime('%Y-%m', SupplierOrder.order_date) == month,
            SupplierOrder.status == 'Delivered'
        ).scalar() or 0
        profit = revenue - expenses
        cash_flow.append({'month': month, 'revenue': revenue, 'expenses': expenses, 'profit': profit})

    # Recent logs and low stock
    low_stock_products = Product.query.filter(Product.stock < 5).all()
    recent_logs = AuditLog.query.order_by(AuditLog.timestamp.desc()).limit(10).all()
    best_products = (
        db.session.query(
            Product.name,
            func.sum(Sale.quantity).label('total_sold')
        )
        .join(Sale, Sale.product_id == Product.id)
        .group_by(Product.id)
        .order_by(desc('total_sold'))
        .limit(5)
        .all()
    )

    return render_template(
        'admin_dashboard.html',
        total_products=total_products,
        total_users=total_users,
        total_sales=total_sales,
        total_expenses=total_expenses,
        sales_trends_labels=sales_trends_labels,
        sales_trends_data=sales_trends_data,
        inventory_value_labels=inventory_value_labels,
        inventory_value_data=inventory_value_data,
        top_products_labels=top_products_labels,
        top_products_data=top_products_data,
        payment_method_labels=payment_method_labels,
        payment_method_data=payment_method_data,
        recent_supplier_orders=recent_supplier_orders,
        outstanding_payments=outstanding_payments,
        supplier_performance=supplier_performance,
        cash_flow=cash_flow,
        low_stock_products=low_stock_products,
        recent_logs=recent_logs,
        best_products=best_products
    )

@app.route('/admin/settings', methods=['GET', 'POST'])
@login_required(role='admin')
def system_settings():
    # Business details keys
    business_keys = [
        'business_name', 'business_address', 'business_email', 'business_phone',
        'bank_name', 'bank_account_name', 'bank_account_number', 'tax_id', 'currency_symbol',
        'receipt_footer', 'date_format', 'session_timeout', 'password_policy', 'signup_enabled'
    ]
    # Get or create settings
    settings = {key: (Setting.query.filter_by(key=key).first() or Setting(key=key, value='')) for key in business_keys}
    for s in settings.values():
        if not s.id:
            db.session.add(s)
    db.session.commit()

    # Inventory and sales settings
    threshold_setting = Setting.query.filter_by(key='low_stock_threshold').first()
    if not threshold_setting:
        threshold_setting = Setting(key='low_stock_threshold', value='5')
        db.session.add(threshold_setting)
        db.session.commit()
    payment_methods_setting = Setting.query.filter_by(key='payment_methods').first()
    if not payment_methods_setting:
        payment_methods_setting = Setting(key='payment_methods', value='Cash,Mpesa,Other')
        db.session.add(payment_methods_setting)
        db.session.commit()

    # Logo setting
    logo_setting = Setting.query.filter_by(key='business_logo').first()
    if not logo_setting:
        logo_setting = Setting(key='business_logo', value='')
        db.session.add(logo_setting)
        db.session.commit()

    if request.method == 'POST':
        # Business details
        for key in business_keys:
            if key in request.form:
                settings[key].value = request.form[key]
        # Inventory
        if 'threshold' in request.form:
            threshold_setting.value = request.form['threshold']
        # Payment methods
        if 'payment_methods' in request.form:
            payment_methods_setting.value = request.form['payment_methods']
        # Logo upload
        if 'business_logo' in request.files:
            file = request.files['business_logo']
            if file and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
                file.save(filepath)
                logo_setting.value = filepath
        db.session.commit()
        flash('Settings updated.', 'success')
        return redirect(url_for('system_settings'))

    categories = Category.query.all()
    return render_template(
        'system_settings.html',
        settings=settings,
        threshold=threshold_setting.value,
        payment_methods=payment_methods_setting.value,
        categories=categories,
        logo=logo_setting.value
    )

@app.route('/admin/settings/overview')
@login_required(role='admin')
def system_settings_overview():
    return render_template('system_settings_overview.html')

@app.route('/admin/settings/business', methods=['GET', 'POST'])
@login_required(role='admin')
def edit_business_details():
    # Business details keys
    business_keys = [
        'business_name', 'business_address', 'business_email', 'business_phone',
        'bank_name', 'bank_account_name', 'bank_account_number', 'tax_id', 'currency_symbol',
        'receipt_footer', 'date_format', 'session_timeout', 'password_policy', 'signup_enabled'
    ]
    # Get or create settings
    settings = {key: (Setting.query.filter_by(key=key).first() or Setting(key=key, value='')) for key in business_keys}
    for s in settings.values():
        if not s.id:
            db.session.add(s)
    db.session.commit()

    # Logo setting
    logo_setting = Setting.query.filter_by(key='business_logo').first()
    if not logo_setting:
        logo_setting = Setting(key='business_logo', value='')
        db.session.add(logo_setting)
        db.session.commit()

    if request.method == 'POST':
        # Business details
        for key in business_keys:
            if key in request.form:
                settings[key].value = request.form[key]
        # Logo upload
        if 'business_logo' in request.files:
            file = request.files['business_logo']
            if file and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
                file.save(filepath)
                logo_setting.value = filepath
        db.session.commit()
        flash('Business details updated.', 'success')
        return redirect(url_for('edit_business_details'))

    return render_template('edit_business_details.html', settings=settings, logo=logo_setting.value)

@app.route('/admin/settings/inventory', methods=['GET', 'POST'])
@login_required(role='admin')
def edit_inventory_settings():
    threshold_setting = Setting.query.filter_by(key='low_stock_threshold').first()
    currency_setting = Setting.query.filter_by(key='currency_symbol').first()
    categories = Category.query.all()
    if not threshold_setting:
        threshold_setting = Setting(key='low_stock_threshold', value='5')
        db.session.add(threshold_setting)
    if not currency_setting:
        currency_setting = Setting(key='currency_symbol', value='KES')
        db.session.add(currency_setting)
    db.session.commit()

    if request.method == 'POST':
        if 'threshold' in request.form:
            threshold_setting.value = request.form['threshold']
        if 'currency_symbol' in request.form:
            currency_setting.value = request.form['currency_symbol']
        if 'add_category' in request.form and request.form['add_category'].strip():
            cat = request.form['add_category'].strip()
            if not Category.query.filter_by(name=cat).first():
                db.session.add(Category(name=cat))
        if 'delete_category' in request.form:
            cat_id = int(request.form['delete_category'])
            cat = Category.query.get(cat_id)
            if cat:
                db.session.delete(cat)
        db.session.commit()
        flash('Inventory settings updated.', 'success')
        return redirect(url_for('edit_inventory_settings'))

    settings = {
        'currency_symbol': currency_setting,
    }
    return render_template(
        'edit_inventory_settings.html',
        threshold=threshold_setting.value,
        settings=settings,
        categories=Category.query.all()
    )

@app.route('/admin/settings/sales', methods=['GET', 'POST'])
@login_required(role='admin')
def edit_sales_settings():
    payment_methods_setting = Setting.query.filter_by(key='payment_methods').first()
    receipt_footer_setting = Setting.query.filter_by(key='receipt_footer').first()
    if not payment_methods_setting:
        payment_methods_setting = Setting(key='payment_methods', value='Cash,Mpesa,Other')
        db.session.add(payment_methods_setting)
    if not receipt_footer_setting:
        receipt_footer_setting = Setting(key='receipt_footer', value='')
        db.session.add(receipt_footer_setting)
    db.session.commit()

    if request.method == 'POST':
        if 'payment_methods' in request.form:
            payment_methods_setting.value = request.form['payment_methods']
        if 'receipt_footer' in request.form:
            receipt_footer_setting.value = request.form['receipt_footer']
        db.session.commit()
        flash('Sales settings updated.', 'success')
        return redirect(url_for('edit_sales_settings'))

    settings = {
        'receipt_footer': receipt_footer_setting,
    }
    return render_template(
        'edit_sales_settings.html',
        payment_methods=payment_methods_setting.value,
        settings=settings
    )

@app.route('/admin/settings/user-security', methods=['GET', 'POST'])
@login_required(role='admin')
def edit_user_security_settings():
    password_policy_setting = Setting.query.filter_by(key='password_policy').first()
    signup_enabled_setting = Setting.query.filter_by(key='signup_enabled').first()
    session_timeout_setting = Setting.query.filter_by(key='session_timeout').first()
    if not password_policy_setting:
        password_policy_setting = Setting(key='password_policy', value='8')
        db.session.add(password_policy_setting)
    if not signup_enabled_setting:
        signup_enabled_setting = Setting(key='signup_enabled', value='yes')
        db.session.add(signup_enabled_setting)
    if not session_timeout_setting:
        session_timeout_setting = Setting(key='session_timeout', value='30')
        db.session.add(session_timeout_setting)
    db.session.commit()

    if request.method == 'POST':
        if 'password_policy' in request.form:
            password_policy_setting.value = request.form['password_policy']
        if 'signup_enabled' in request.form:
            signup_enabled_setting.value = request.form['signup_enabled']
        if 'session_timeout' in request.form:
            session_timeout_setting.value = request.form['session_timeout']
        db.session.commit()
        flash('User & security settings updated.', 'success')
        return redirect(url_for('edit_user_security_settings'))

    settings = {
        'password_policy': password_policy_setting,
        'signup_enabled': signup_enabled_setting,
        'session_timeout': session_timeout_setting,
    }
    return render_template(
        'edit_user_security_settings.html',
        settings=settings
    )

@app.route('/admin/settings/other', methods=['GET', 'POST'])
@login_required(role='admin')
def edit_other_settings():
    date_format_setting = Setting.query.filter_by(key='date_format').first()
    if not date_format_setting:
        date_format_setting = Setting(key='date_format', value='%Y-%m-%d %H:%M:%S')
        db.session.add(date_format_setting)
    db.session.commit()

    if request.method == 'POST':
        if 'date_format' in request.form:
            date_format_setting.value = request.form['date_format']
        db.session.commit()
        flash('Other settings updated.', 'success')
        return redirect(url_for('edit_other_settings'))

    settings = {
        'date_format': date_format_setting,
    }
    return render_template(
        'edit_other_settings.html',
        settings=settings
    )

@app.route('/admin/export')
@login_required(role='admin')
def export_data():
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['ID', 'Name', 'Price', 'Stock', 'Unit'])
    for product in Product.query.all():
        writer.writerow([product.id, product.name, product.selling_price, product.stock, product.unit])
    output.seek(0)
    return send_file(
        io.BytesIO(output.getvalue().encode()),
        mimetype='text/csv',
        as_attachment=True,
        download_name='products_export.csv'
    )

@app.route('/admin/backup')
@login_required(role='admin')
def backup_data():
    data = {
        'products': [dict(id=p.id, name=p.name, price=p.price, stock=p.stock, unit=p.unit) for p in Product.query.all()],
        'users': [dict(id=u.id, username=u.username, role=u.role) for u in User.query.all()],
        'sales': [dict(id=s.id, product_id=s.product_id, quantity=s.quantity, total_price=s.total_price, payment_method=s.payment_method, timestamp=str(s.timestamp)) for s in Sale.query.all()],
        'categories': [dict(id=c.id, name=c.name) for c in Category.query.all()],
        'settings': [dict(key=s.key, value=s.value) for s in Setting.query.all()]
    }
    output = io.BytesIO(json.dumps(data, indent=2).encode())
    return send_file(
        output,
        mimetype='application/json',
        as_attachment=True,
        download_name='duka_backup.json'
    )

@app.route('/suppliers')
@login_required(role='admin')
def suppliers_list():
    suppliers = Supplier.query.all()
    return render_template('suppliers_list.html', suppliers=suppliers)

@app.route('/suppliers/add', methods=['GET', 'POST'])
@login_required(role='admin')
def add_supplier():
    if request.method == 'POST':
        supplier = Supplier(
            name=request.form['name'],
            company=request.form.get('company'),
            contact_email=request.form.get('contact_email'),
            contact_phone=request.form.get('contact_phone'),
            address=request.form.get('address'),
            bank_name=request.form.get('bank_name'),
            bank_account=request.form.get('bank_account'),
            notes=request.form.get('notes')
        )
        db.session.add(supplier)
        db.session.commit()
        flash('Supplier added.', 'success')
        return redirect(url_for('suppliers_list'))
    return render_template('add_supplier.html')

@app.route('/suppliers/edit/<int:supplier_id>', methods=['GET', 'POST'])
@login_required(role='admin')
def edit_supplier(supplier_id):
    supplier = Supplier.query.get_or_404(supplier_id)
    if request.method == 'POST':
        supplier.name = request.form['name']
        supplier.company = request.form.get('company')
        supplier.contact_email = request.form.get('contact_email')
        supplier.contact_phone = request.form.get('contact_phone')
        supplier.address = request.form.get('address')
        supplier.bank_name = request.form.get('bank_name')
        supplier.bank_account = request.form.get('bank_account')
        supplier.notes = request.form.get('notes')
        db.session.commit()
        flash('Supplier updated.', 'success')
        return redirect(url_for('suppliers_list'))
    return render_template('edit_supplier.html', supplier=supplier)

@app.route('/suppliers/delete/<int:supplier_id>')
@login_required(role='admin')
def delete_supplier(supplier_id):
    supplier = Supplier.query.get_or_404(supplier_id)
    db.session.delete(supplier)
    db.session.commit()
    flash('Supplier deleted.', 'success')
    return redirect(url_for('suppliers_list'))

@app.route('/suppliers/<int:supplier_id>/products', methods=['GET', 'POST'])
@login_required(role='admin')
def supplier_products(supplier_id):
    supplier = Supplier.query.get_or_404(supplier_id)
    products = Product.query.all()
    if request.method == 'POST':
        product_id = int(request.form['product_id'])
        product = Product.query.get(product_id)
        if product:
            product.supplier_id = supplier.id
            db.session.commit()
            flash('Product linked to supplier.', 'success')
        return redirect(url_for('supplier_products', supplier_id=supplier.id))
    return render_template('supplier_products.html', supplier=supplier, products=products)

@app.route('/suppliers/<int:supplier_id>/orders', methods=['GET', 'POST'])
@login_required(role='admin')
def supplier_orders(supplier_id):
    supplier = Supplier.query.get_or_404(supplier_id)
    products = Product.query.filter_by(supplier_id=supplier.id).all()
    if request.method == 'POST':
        product_id = int(request.form['product_id'])
        quantity = int(request.form['quantity'])
        cost = float(request.form['cost'])
        order = SupplierOrder(
            supplier_id=supplier.id,
            product_id=product_id,
            quantity=quantity,
            cost=cost,
            status=request.form.get('status', 'Pending')
        )
        db.session.add(order)
        db.session.commit()
        flash('Order recorded.', 'success')
        return redirect(url_for('supplier_orders', supplier_id=supplier.id))
    orders = SupplierOrder.query.filter_by(supplier_id=supplier.id).all()
    return render_template('supplier_orders.html', supplier=supplier, products=products, orders=orders)

@app.route('/suppliers/<int:supplier_id>/report')
@login_required(role='admin')
def supplier_report(supplier_id):
    supplier = Supplier.query.get_or_404(supplier_id)
    orders = SupplierOrder.query.filter_by(supplier_id=supplier.id).all()
    total_purchases = sum(order.cost for order in orders)
    outstanding_orders = [order for order in orders if order.status != 'Delivered']
    return render_template('supplier_report.html', supplier=supplier, orders=orders, total_purchases=total_purchases, outstanding_orders=outstanding_orders)

@app.route('/suppliers/<int:supplier_id>/details')
@login_required(role='admin')
def supplier_details(supplier_id):
    supplier = Supplier.query.get_or_404(supplier_id)
    products = Product.query.filter_by(supplier_id=supplier.id).all()
    orders = SupplierOrder.query.filter_by(supplier_id=supplier.id).all()
    total_purchases = sum(order.cost for order in orders)
    outstanding_orders = [order for order in orders if order.status != 'Delivered']
    return render_template('supplier_report.html', supplier=supplier, products=products, orders=orders, total_purchases=total_purchases, outstanding_orders=outstanding_orders)

@app.route('/products/add', methods=['GET', 'POST'])
@login_required(role='admin')
def add_product():
    categories = Category.query.all()
    suppliers = Supplier.query.all()
    units = ['KGs', 'Grams', 'Liters', 'Milliliters', 'Pieces', 'Bales', 'Packs', 'Boxes', 'Cartons', 'Dozens', 'Meters', 'Rolls', 'Bottles', 'Bags', 'Trays']
    if request.method == 'POST':
        name = request.form['name']
        buying_price = float(request.form['buying_price'])
        selling_price = float(request.form['selling_price'])
        stock = int(request.form['stock'])
        unit = request.form['unit']
        category_id = int(request.form['category'])
        supplier_id = int(request.form['supplier'])
        description = request.form.get('description')
        image = None
        if 'image' in request.files:
            file = request.files['image']
            if file and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(filepath)
                image = filepath
        barcode = request.form.get('barcode')
        product = Product(
            name=name,
            buying_price=buying_price,
            selling_price=selling_price,
            stock=stock,
            unit=unit,
            category_id=category_id,
            supplier_id=supplier_id,
            image=image,
            barcode=barcode,
            description=description
        )
        db.session.add(product)
        db.session.commit()
        flash('Product added.', 'success')
        return redirect(url_for('products_page'))
    return render_template('add_product.html', categories=categories, suppliers=suppliers, units=units)

@app.route('/products/bulk', methods=['POST'])
@login_required(role='admin')
def bulk_products():
    action = request.form['action']
    product_ids = request.form.getlist('product_ids')
    if action == 'delete':
        for pid in product_ids:
            product = Product.query.get(pid)
            db.session.delete(product)
    elif action == 'update_stock':
        new_stock = int(request.form['new_stock'])
        for pid in product_ids:
            product = Product.query.get(pid)
            product.stock = new_stock
    elif action == 'update_price':
        new_price = float(request.form['new_price'])
        for pid in product_ids:
            product = Product.query.get(pid)
            product.selling_price = new_price
    db.session.commit()
    flash('Bulk action completed.', 'success')
    return redirect(url_for('products_page'))

    # PDF receipt route
@app.route('/download_receipt/<int:sale_id>')
def download_receipt(sale_id):
    sale = Sale.query.get_or_404(sale_id)
    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)
    p.setFont("Helvetica-Bold", 16)
    p.drawString(50, 750, "Sale Receipt")
    p.setFont("Helvetica", 12)
    p.drawString(50, 720, f"Product: {sale.product.name}")
    p.drawString(50, 700, f"Quantity: {sale.quantity}")
    p.drawString(50, 680, f"Total: {sale.total_price}")
    p.drawString(50, 660, f"Customer: {sale.customer_name or '-'}")
    p.drawString(50, 640, f"Contact: {sale.customer_contact or '-'}")
    p.drawString(50, 620, f"Payment: {sale.payment_method}")
    p.drawString(50, 600, f"Date: {sale.timestamp.strftime('%Y-%m-%d %H:%M')}")
    p.showPage()
    p.save()
    buffer.seek(0)
    return send_file(buffer, as_attachment=True, download_name=f"receipt_{sale.id}.pdf", mimetype='application/pdf')
if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)