import os
import uuid
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from werkzeug.utils import secure_filename
from models import (db, Customer, Invoice, InvoiceItem, Payment, Return, ReturnItem,
                    Supplier, Purchase, PurchaseItem, SupplierPayment,
                    InstallmentPlan, Installment, InstallmentPayment,
                    SupplierInstallmentPlan, SupplierInstallment, SupplierInstallmentPayment,
                    ShippingCompany, User, UserPermission, EntityLock)
from datetime import datetime, date, timedelta
from dateutil.relativedelta import relativedelta
from sqlalchemy import desc, func

app = Flask(__name__)
app.config['SECRET_KEY'] = 'eldahab-trading-secret-2026'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///eldahab.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=24)
app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(__file__), 'static', 'uploads')
app.config['RECEIPT_FOLDER'] = os.path.join(app.config['UPLOAD_FOLDER'], 'receipts')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
ALLOWED_RECEIPT_EXTS = {'png', 'jpg', 'jpeg', 'webp', 'gif'}

db.init_app(app)


@app.context_processor
def inject_payment_methods():
    return {'PAYMENT_METHODS': PAYMENT_METHODS}


PAGE_MAP = {
    'dashboard': 'dashboard',
    'customers_list': 'customers',
    'customer_add': 'customer_add',
    'customer_profile': 'customers',
    'customer_edit': 'customers',
    'customer_delete': 'customers',
    'invoices_list': 'invoices',
    'invoice_add': 'invoice_add',
    'invoice_view': 'invoices',
    'invoice_delete': 'invoices',
    'payment_add': 'payments',
    'payments_list': 'payments',
    'installments_list': 'installments_list',
    'installment_view': 'installments_list',
    'installment_pay': 'installments_list',
    'supplier_installments_list': 'supplier_installments_list',
    'supplier_installment_view': 'supplier_installments_list',
    'supplier_installment_pay': 'supplier_installments_list',
    'suppliers_list': 'suppliers',
    'supplier_add': 'supplier_add',
    'supplier_profile': 'suppliers',
    'supplier_edit': 'suppliers',
    'supplier_delete': 'suppliers',
    'supplier_payment_add': 'suppliers',
    'supplier_statement': 'suppliers',
    'suppliers_statement_all': 'suppliers',
    'purchases_list': 'purchases',
    'purchase_add': 'purchase_add',
    'purchase_view': 'purchases',
    'purchase_delete': 'purchases',
    'shipping_list': 'shipping',
    'shipping_add': 'shipping',
    'shipping_profile': 'shipping',
    'shipping_edit': 'shipping',
    'shipping_delete': 'shipping',
    'employees_list': 'employees',
    'employee_add': 'employees',
    'employee_edit': 'employees',
    'employee_delete': 'employees',
    'employee_permissions': 'employees',
}


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        if session.get('expires_at'):
            if datetime.utcnow().timestamp() > session['expires_at']:
                session.clear()
                flash('انتهت الجلسة، يرجى تسجيل الدخول مرة اخرى', 'warning')
                return redirect(url_for('login'))
        user = User.query.get(session['user_id'])
        if not user or not user.is_active:
            session.clear()
            flash('الحساب معطل، تواصل مع المدير', 'danger')
            return redirect(url_for('login'))
        page_key = PAGE_MAP.get(request.endpoint)
        if page_key and not user.has_permission(page_key):
            first_page = get_first_permitted_page(user)
            flash('ليس لديك صلاحية للدخول لهذه الصفحة', 'danger')
            return redirect(url_for(first_page))
        return f(*args, **kwargs)
    return decorated_function


def get_first_permitted_page(user):
    if user.is_admin:
        return 'dashboard'
    order = ['dashboard', 'customers', 'invoices', 'payments', 'installments_list',
             'supplier_installments_list', 'suppliers', 'purchases', 'shipping', 'employees']
    endpoint_map = {
        'dashboard': 'dashboard',
        'customers': 'customers_list',
        'invoices': 'invoices_list',
        'payments': 'payments_list',
        'installments_list': 'installments_list',
        'supplier_installments_list': 'supplier_installments_list',
        'suppliers': 'suppliers_list',
        'purchases': 'purchases_list',
        'shipping': 'shipping_list',
        'employees': 'employees_list',
    }
    for p in order:
        if user.has_permission(p):
            return endpoint_map.get(p, 'logout')
    return 'logout'

@app.before_request
def check_session_expiry():
    if 'user_id' in session and session.get('expires_at'):
        if datetime.utcnow().timestamp() > session['expires_at']:
            session.clear()
            flash('انتهت الجلسة، يرجى تسجيل الدخول مرة اخرى', 'warning')
            return redirect(url_for('login'))

@app.context_processor
def inject_user():
    user = None
    if 'user_id' in session:
        user = User.query.get(session['user_id'])
    return dict(current_user=user)

ACCOUNT_TYPES = {
    'sales': 'حسابات البيع',
    'shipping': 'حسابات الشحن',
    'travel': 'حسابات السفر',
    'bab_al_sharriah': 'حسابات باب الشعريه',
    'supplier': 'حسابات موردين'
}

PAYMENT_TYPES = {
    'cash': 'نقداً',
    'credit': 'بالاجل',
    'installment': 'تقسيط'
}

PAYMENT_METHODS = {
    'cash': 'كاش',
    'ekash': 'اي كاش',
    'bank': 'تحويل بنكي',
    'instapay': 'انستا باي',
    'vodafone': 'فودافون كاش'
}

INSTALLMENT_STATUS = {
    'active': 'نشط',
    'completed': 'مكتمل',
    'overdue': 'متأخر'
}

INSTALLMENT_PAYMENT_STATUS = {
    'pending': 'لم يُدفع',
    'paid': 'مدفوع',
    'partial': ' مدفوع جزئياً'
}

PAGES = {
    'dashboard': {'name': 'لوحة التحكم', 'icon': 'fa-chart-pie', 'group': 'الرئيسية'},
    'customers': {'name': 'قائمة العملاء', 'icon': 'fa-users', 'group': 'العملاء'},
    'customer_add': {'name': 'اضافة عميل', 'icon': 'fa-user-plus', 'group': 'العملاء'},
    'invoices': {'name': 'الفواتير', 'icon': 'fa-file-invoice-dollar', 'group': 'الفواتير'},
    'invoice_add': {'name': 'فاتورة جديدة', 'icon': 'fa-plus-circle', 'group': 'الفواتير'},
    'payments': {'name': 'المدفوعات', 'icon': 'fa-money-bill-wave', 'group': 'المدفوعات'},
    'installments_list': {'name': 'اقساط العملاء', 'icon': 'fa-calendar-check', 'group': 'المدفوعات'},
    'supplier_installments_list': {'name': 'اقساط الموردين', 'icon': 'fa-calendar-alt', 'group': 'المدفوعات'},
    'suppliers': {'name': 'الموردين', 'icon': 'fa-truck', 'group': 'الموردين'},
    'supplier_add': {'name': 'اضافة مورد', 'icon': 'fa-user-plus', 'group': 'الموردين'},
    'purchases': {'name': 'المشتريات', 'icon': 'fa-shopping-cart', 'group': 'المشتريات'},
    'purchase_add': {'name': 'امر شراء جديد', 'icon': 'fa-plus-circle', 'group': 'المشتريات'},
    'shipping': {'name': 'شركات الشحن', 'icon': 'fa-shipping-fast', 'group': 'الشحن'},
    'employees': {'name': 'ادارة الموظفين', 'icon': 'fa-user-tie', 'group': 'الادارة'},
}

PAGE_MAP = {
    'dashboard': 'dashboard',
    'customers_list': 'customers',
    'customer_add': 'customer_add',
    'customer_profile': 'customers',
    'customer_edit': 'customers',
    'customer_delete': 'customers',
    'invoices_list': 'invoices',
    'invoice_add': 'invoice_add',
    'invoice_view': 'invoices',
    'invoice_delete': 'invoices',
    'return_add': 'customers',
    'return_edit': 'customers',
    'customer_statement': 'customers',
    'customers_statement_all': 'customers',
    'payment_add': 'payments',    'payments_list': 'payments',
    'installments_list': 'installments_list',
    'installment_view': 'installments_list',
    'installment_pay': 'installments_list',
    'supplier_installments_list': 'supplier_installments_list',
    'supplier_installment_view': 'supplier_installments_list',
    'supplier_installment_pay': 'supplier_installments_list',
    'suppliers_list': 'suppliers',
    'supplier_add': 'supplier_add',
    'supplier_profile': 'suppliers',
    'supplier_edit': 'suppliers',
    'supplier_delete': 'suppliers',
    'supplier_payment_add': 'suppliers',
    'supplier_statement': 'suppliers',
    'suppliers_statement_all': 'suppliers',
    'purchases_list': 'purchases',
    'purchase_add': 'purchase_add',
    'purchase_view': 'purchases',
    'purchase_delete': 'purchases',
    'shipping_list': 'shipping',
    'shipping_add': 'shipping',
    'shipping_profile': 'shipping',
    'shipping_edit': 'shipping',
    'shipping_delete': 'shipping',
    'employees_list': 'employees',
    'employee_add': 'employees',
    'employee_edit': 'employees',
    'employee_delete': 'employees',
    'employee_permissions': 'employees',
}

with app.app_context():
    db.create_all()

    def ensure_columns():
        inspector = db.inspect(db.engine)
        invoice_cols = {c['name'] for c in inspector.get_columns('invoices')}
        if 'payment_type' not in invoice_cols:
            db.session.execute(db.text("ALTER TABLE invoices ADD COLUMN payment_type VARCHAR(20) DEFAULT 'cash'"))
        if 'paid_amount' not in invoice_cols:
            db.session.execute(db.text("ALTER TABLE invoices ADD COLUMN paid_amount FLOAT DEFAULT 0"))
        if 'remaining' not in invoice_cols:
            db.session.execute(db.text("ALTER TABLE invoices ADD COLUMN remaining FLOAT DEFAULT 0"))
        if 'discount' not in invoice_cols:
            db.session.execute(db.text("ALTER TABLE invoices ADD COLUMN discount FLOAT DEFAULT 0"))
        if 'show_balance' not in invoice_cols:
            db.session.execute(db.text("ALTER TABLE invoices ADD COLUMN show_balance BOOLEAN DEFAULT 0"))
        if 'payment_method' not in invoice_cols:
            db.session.execute(db.text("ALTER TABLE invoices ADD COLUMN payment_method VARCHAR(20) DEFAULT 'cash'"))
        if 'receipt_image' not in invoice_cols:
            db.session.execute(db.text("ALTER TABLE invoices ADD COLUMN receipt_image VARCHAR(200)"))

        invoice_item_cols = {c['name'] for c in inspector.get_columns('invoice_items')}
        if 'unit_type' not in invoice_item_cols:
            db.session.execute(db.text("ALTER TABLE invoice_items ADD COLUMN unit_type VARCHAR(10) DEFAULT 'ق'"))

        purchase_cols = {c['name'] for c in inspector.get_columns('purchases')}
        if 'payment_type' not in purchase_cols:
            db.session.execute(db.text("ALTER TABLE purchases ADD COLUMN payment_type VARCHAR(20) DEFAULT 'cash'"))
        if 'paid_amount' not in purchase_cols:
            db.session.execute(db.text("ALTER TABLE purchases ADD COLUMN paid_amount FLOAT DEFAULT 0"))
        if 'remaining' not in purchase_cols:
            db.session.execute(db.text("ALTER TABLE purchases ADD COLUMN remaining FLOAT DEFAULT 0"))
        if 'payment_method' not in purchase_cols:
            db.session.execute(db.text("ALTER TABLE purchases ADD COLUMN payment_method VARCHAR(20) DEFAULT 'cash'"))
        if 'receipt_image' not in purchase_cols:
            db.session.execute(db.text("ALTER TABLE purchases ADD COLUMN receipt_image VARCHAR(200)"))

        purchase_item_cols = {c['name'] for c in inspector.get_columns('purchase_items')}
        if 'unit_type' not in purchase_item_cols:
            db.session.execute(db.text("ALTER TABLE purchase_items ADD COLUMN unit_type VARCHAR(10) DEFAULT 'ق'"))

        return_item_cols = {c['name'] for c in inspector.get_columns('return_items')}
        if 'unit_type' not in return_item_cols:
            db.session.execute(db.text("ALTER TABLE return_items ADD COLUMN unit_type VARCHAR(10) DEFAULT 'ق'"))

        sp_cols = {c['name'] for c in inspector.get_columns('supplier_payments')}
        if 'purchase_id' not in sp_cols:
            db.session.execute(db.text("ALTER TABLE supplier_payments ADD COLUMN purchase_id INTEGER"))
        if 'payment_method' not in sp_cols:
            db.session.execute(db.text("ALTER TABLE supplier_payments ADD COLUMN payment_method VARCHAR(20) DEFAULT 'cash'"))
        if 'receipt_image' not in sp_cols:
            db.session.execute(db.text("ALTER TABLE supplier_payments ADD COLUMN receipt_image VARCHAR(200)"))

        pay_cols = {c['name'] for c in inspector.get_columns('payments')}
        if 'payment_method' not in pay_cols:
            db.session.execute(db.text("ALTER TABLE payments ADD COLUMN payment_method VARCHAR(20) DEFAULT 'cash'"))
        if 'receipt_image' not in pay_cols:
            db.session.execute(db.text("ALTER TABLE payments ADD COLUMN receipt_image VARCHAR(200)"))

        inst_pay_cols = {c['name'] for c in inspector.get_columns('installment_payments')}
        if 'payment_method' not in inst_pay_cols:
            db.session.execute(db.text("ALTER TABLE installment_payments ADD COLUMN payment_method VARCHAR(20) DEFAULT 'cash'"))
        if 'receipt_image' not in inst_pay_cols:
            db.session.execute(db.text("ALTER TABLE installment_payments ADD COLUMN receipt_image VARCHAR(200)"))

        supp_inst_pay_cols = {c['name'] for c in inspector.get_columns('supplier_installment_payments')}
        if 'payment_method' not in supp_inst_pay_cols:
            db.session.execute(db.text("ALTER TABLE supplier_installment_payments ADD COLUMN payment_method VARCHAR(20) DEFAULT 'cash'"))
        if 'receipt_image' not in supp_inst_pay_cols:
            db.session.execute(db.text("ALTER TABLE supplier_installment_payments ADD COLUMN receipt_image VARCHAR(200)"))

        user_cols = {c['name'] for c in inspector.get_columns('users')}
        if 'is_admin' not in user_cols:
            db.session.execute(db.text("ALTER TABLE users ADD COLUMN is_admin BOOLEAN DEFAULT 0"))

        db.session.execute(db.text("UPDATE invoices SET paid_amount=0 WHERE paid_amount IS NULL"))
        db.session.execute(db.text("UPDATE invoices SET remaining=0 WHERE remaining IS NULL"))
        db.session.execute(db.text("UPDATE purchases SET paid_amount=0 WHERE paid_amount IS NULL"))
        db.session.execute(db.text("UPDATE purchases SET remaining=0 WHERE remaining IS NULL"))

        db.create_all()
        db.session.commit()

        if not User.query.filter_by(username='admin').first():
            admin = User(username='admin', full_name='المدير', is_admin=True)
            admin.set_password('admin123')
            db.session.add(admin)
            db.session.commit()
        else:
            admin = User.query.filter_by(username='admin').first()
            if admin and not admin.is_admin:
                admin.is_admin = True
                db.session.commit()

    ensure_columns()


def generate_invoice_number():
    last = Invoice.query.order_by(Invoice.id.desc()).first()
    num = (last.id + 1) if last else 1
    return f"INV-{num:06d}"


def save_receipt_image(file_storage):
    if not file_storage or not file_storage.filename:
        return None
    ext = file_storage.filename.rsplit('.', 1)[-1].lower() if '.' in file_storage.filename else ''
    if ext not in ALLOWED_RECEIPT_EXTS:
        return None
    os.makedirs(app.config['RECEIPT_FOLDER'], exist_ok=True)
    fname = f"receipt_{uuid.uuid4().hex[:12]}.{ext}"
    file_storage.save(os.path.join(app.config['RECEIPT_FOLDER'], fname))
    return fname


def delete_receipt_image(fname):
    if not fname:
        return
    path = os.path.join(app.config['RECEIPT_FOLDER'], fname)
    if os.path.exists(path):
        try:
            os.remove(path)
        except OSError:
            pass


def generate_purchase_number():
    last = Purchase.query.order_by(Purchase.id.desc()).first()
    num = (last.id + 1) if last else 1
    return f"PUR-{num:06d}"


def generate_plan_number(prefix='INST'):
    last = InstallmentPlan.query.order_by(InstallmentPlan.id.desc()).first()
    num = (last.id + 1) if last else 1
    return f"{prefix}-{num:06d}"


def generate_supplier_plan_number():
    last = SupplierInstallmentPlan.query.order_by(SupplierInstallmentPlan.id.desc()).first()
    num = (last.id + 1) if last else 1
    return f"SINST-{num:06d}"


@app.route('/')
def splash():
    return render_template('splash.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        user = User.query.filter_by(username=username, is_active=True).first()
        if user and user.check_password(password):
            session.permanent = True
            session['user_id'] = user.id
            session['username'] = user.username
            session['full_name'] = user.full_name or user.username
            session['expires_at'] = (datetime.utcnow() + timedelta(hours=24)).timestamp()
            user.last_login = datetime.utcnow()
            db.session.commit()
            flash(f'مرحباً {user.full_name or user.username}', 'success')
            return redirect(url_for(get_first_permitted_page(user)))
        flash('اسم المستخدم أو كلمة المرور غير صحيحة', 'danger')
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    flash('تم تسجيل الخروج بنجاح', 'info')
    return redirect(url_for('login'))


@app.route('/dashboard')
@login_required
def dashboard():
    total_customers = Customer.query.count()
    total_suppliers = Supplier.query.count()
    total_invoices = Invoice.query.filter_by(is_returned=False).count()
    total_purchases = Purchase.query.count()
    total_revenue = db.session.query(func.sum(Invoice.total)).filter_by(is_returned=False).scalar() or 0
    total_paid = db.session.query(func.sum(Payment.amount)).scalar() or 0
    total_returns_amount = db.session.query(func.sum(Return.total_amount)).scalar() or 0
    total_receivable = total_revenue - total_paid - total_returns_amount
    total_purchase_cost = db.session.query(func.sum(Purchase.total)).scalar() or 0
    total_supplier_paid = db.session.query(func.sum(SupplierPayment.amount)).scalar() or 0
    total_payable = total_purchase_cost - total_supplier_paid

    total_credit_sales = db.session.query(func.sum(Invoice.total)).filter(
        Invoice.payment_type == 'credit', Invoice.is_returned == False
    ).scalar() or 0
    total_installment_sales = db.session.query(func.sum(Invoice.total)).filter(
        Invoice.payment_type == 'installment', Invoice.is_returned == False
    ).scalar() or 0
    total_installment_paid_sales = db.session.query(func.sum(InstallmentPayment.amount)).scalar() or 0

    total_credit_purchases = db.session.query(func.sum(Purchase.total)).filter(
        Purchase.payment_type == 'credit'
    ).scalar() or 0
    total_installment_purchases = db.session.query(func.sum(Purchase.total)).filter(
        Purchase.payment_type == 'installment'
    ).scalar() or 0
    total_installment_paid_purchases = db.session.query(func.sum(SupplierInstallmentPayment.amount)).scalar() or 0

    from datetime import date as dt_date
    today = dt_date.today()
    customer_overdue = 0
    for plan in InstallmentPlan.query.filter_by(status='active').all():
        for inst in plan.installments:
            if inst.status == 'pending' and inst.due_date and inst.due_date < today:
                customer_overdue += inst.amount

    supplier_overdue = 0
    for plan in SupplierInstallmentPlan.query.filter_by(status='active').all():
        for inst in plan.installments:
            if inst.status == 'pending' and inst.due_date and inst.due_date < today:
                supplier_overdue += inst.amount

    recent_invoices = Invoice.query.order_by(Invoice.date.desc()).limit(10).all()
    recent_payments = Payment.query.order_by(Payment.date.desc()).limit(10).all()
    recent_purchases = Purchase.query.order_by(Purchase.date.desc()).limit(10).all()
    top_customers = Customer.query.all()
    top_customers.sort(key=lambda c: c.total_invoiced(), reverse=True)
    top_customers = top_customers[:5]

    monthly_data = []
    all_invoices = Invoice.query.filter_by(is_returned=False).all()
    all_payments = Payment.query.all()
    now = datetime.utcnow()
    for i in range(11, -1, -1):
        month = now.month - i
        year = now.year
        if month <= 0:
            month += 12
            year -= 1
        rev = sum(inv.total for inv in all_invoices if inv.date.year == year and inv.date.month == month)
        paid = sum(p.amount for p in all_payments if p.date.year == year and p.date.month == month)
        monthly_data.append({
            'month': f"{year}-{month:02d}",
            'revenue': rev,
            'paid': paid
        })

    max_revenue = max((m['revenue'] for m in monthly_data), default=1) or 1

    return render_template('dashboard.html',
        total_customers=total_customers,
        total_suppliers=total_suppliers,
        total_invoices=total_invoices,
        total_purchases=total_purchases,
        total_revenue=total_revenue,
        total_paid=total_paid,
        total_receivable=total_receivable,
        total_purchase_cost=total_purchase_cost,
        total_supplier_paid=total_supplier_paid,
        total_payable=total_payable,
        total_returns_amount=total_returns_amount,
        recent_invoices=recent_invoices,
        recent_payments=recent_payments,
        recent_purchases=recent_purchases,
        top_customers=top_customers,
        monthly_data=monthly_data,
        max_revenue=max_revenue,
        total_credit_sales=total_credit_sales,
        total_installment_sales=total_installment_sales,
        total_installment_paid_sales=total_installment_paid_sales,
        total_credit_purchases=total_credit_purchases,
        total_installment_purchases=total_installment_purchases,
        total_installment_paid_purchases=total_installment_paid_purchases,
        customer_overdue=customer_overdue,
        supplier_overdue=supplier_overdue,
        ACCOUNT_TYPES=ACCOUNT_TYPES
    )


@app.route('/employees')
@login_required
def employees_list():
    if not current_user().is_admin:
        flash('ليس لديك صلاحية', 'danger')
        return redirect(url_for('dashboard'))
    users = User.query.order_by(User.id).all()
    return render_template('employees_list.html', users=users, PAGES=PAGES)


@app.route('/employees/add', methods=['GET', 'POST'])
@login_required
def employee_add():
    if not current_user().is_admin:
        flash('ليس لديك صلاحية', 'danger')
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        if User.query.filter_by(username=username).first():
            flash('اسم المستخدم موجود بالفعل', 'danger')
            return render_template('employee_form.html', user=None, PAGES=PAGES)
        u = User(
            username=username,
            full_name=request.form.get('full_name', ''),
            is_admin='is_admin' in request.form,
            is_active='is_active' in request.form
        )
        u.set_password(request.form.get('password', '123456'))
        db.session.add(u)
        db.session.flush()
        for page in request.form.getlist('permissions'):
            if page in PAGES:
                db.session.add(UserPermission(user_id=u.id, page=page))
        db.session.commit()
        flash('تم اضافة الموظف بنجاح', 'success')
        return redirect(url_for('employees_list'))
    return render_template('employee_form.html', user=None, PAGES=PAGES)


@app.route('/employees/<int:user_id>/edit', methods=['GET', 'POST'])
@login_required
def employee_edit(user_id):
    if not current_user().is_admin:
        flash('ليس لديك صلاحية', 'danger')
        return redirect(url_for('dashboard'))
    u = User.query.get_or_404(user_id)
    if request.method == 'POST':
        u.full_name = request.form.get('full_name', '')
        u.is_admin = 'is_admin' in request.form
        u.is_active = 'is_active' in request.form
        new_pass = request.form.get('password', '').strip()
        if new_pass:
            u.set_password(new_pass)
        UserPermission.query.filter_by(user_id=u.id).delete()
        for page in request.form.getlist('permissions'):
            if page in PAGES:
                db.session.add(UserPermission(user_id=u.id, page=page))
        db.session.commit()
        flash('تم تعديل بيانات الموظف بنجاح', 'success')
        return redirect(url_for('employees_list'))
    return render_template('employee_form.html', user=u, PAGES=PAGES)


@app.route('/employees/<int:user_id>/delete', methods=['POST'])
@login_required
def employee_delete(user_id):
    if not current_user().is_admin:
        flash('ليس لديك صلاحية', 'danger')
        return redirect(url_for('dashboard'))
    u = User.query.get_or_404(user_id)
    if u.username == 'admin':
        flash('لا يمكن حذف المدير الرئيسي', 'danger')
        return redirect(url_for('employees_list'))
    db.session.delete(u)
    db.session.commit()
    flash('تم حذف الموظف بنجاح', 'success')
    return redirect(url_for('employees_list'))


@app.route('/employees/<int:user_id>/permissions', methods=['GET', 'POST'])
@login_required
def employee_permissions(user_id):
    if not current_user().is_admin:
        flash('ليس لديك صلاحية', 'danger')
        return redirect(url_for('dashboard'))
    u = User.query.get_or_404(user_id)
    if request.method == 'POST':
        UserPermission.query.filter_by(user_id=u.id).delete()
        for page in request.form.getlist('permissions'):
            if page in PAGES:
                db.session.add(UserPermission(user_id=u.id, page=page))
        db.session.commit()
        flash('تم تحديث الصلاحيات بنجاح', 'success')
        return redirect(url_for('employees_list'))
    return render_template('employee_permissions.html', user=u, PAGES=PAGES)


def current_user():
    if 'user_id' in session:
        return User.query.get(session['user_id'])
    return None


@app.route('/customers')
@login_required
def customers_list():
    account_type = request.args.get('account_type', '')
    search = request.args.get('search', '')
    query = Customer.query
    if account_type:
        query = query.filter_by(account_type=account_type)
    if search:
        query = query.filter(Customer.name.contains(search) | Customer.phone.contains(search))
    customers = query.order_by(Customer.name).all()
    return render_template('customers_list.html', customers=customers,
        ACCOUNT_TYPES=ACCOUNT_TYPES, selected_type=account_type, search=search)


@app.route('/customers/add', methods=['GET', 'POST'])
@login_required
def customer_add():
    if request.method == 'POST':
        c = Customer(
            name=request.form['name'],
            phone=request.form.get('phone', ''),
            address=request.form.get('address', ''),
            account_type=request.form['account_type'],
            notes=request.form.get('notes', '')
        )
        db.session.add(c)
        db.session.commit()
        flash('تم اضافة العميل بنجاح', 'success')
        return redirect(url_for('customer_profile', customer_id=c.id))
    return render_template('customer_form.html', ACCOUNT_TYPES=ACCOUNT_TYPES, customer=None)


@app.route('/customers/<int:customer_id>')
@login_required
def customer_profile(customer_id):
    c = Customer.query.get_or_404(customer_id)
    invoices = Invoice.query.filter_by(customer_id=c.id).order_by(Invoice.date.desc()).all()
    payments = Payment.query.filter_by(customer_id=c.id).order_by(Payment.date.desc()).all()
    returns = Return.query.filter_by(customer_id=c.id).order_by(Return.date.desc()).all()
    installment_plans = InstallmentPlan.query.filter_by(customer_id=c.id).order_by(InstallmentPlan.date.desc()).all()
    return render_template('customer_profile.html', customer=c,
        invoices=invoices, payments=payments, returns=returns,
        installment_plans=installment_plans, ACCOUNT_TYPES=ACCOUNT_TYPES,
        PAYMENT_TYPES=PAYMENT_TYPES)


def _customer_statement_rows(c):
    entries = []

    for inv in c.invoices:
        if inv.is_returned:
            continue
        net = max(0, (inv.total or 0) - (inv.discount or 0))
        entries.append({'date': inv.date, 'label': f'فاتورة بيع رقم {inv.invoice_number}',
                        'debit': net, 'credit': 0})
        linked = db.session.query(db.func.coalesce(db.func.sum(Payment.amount), 0)).filter(
            Payment.invoice_id == inv.id).scalar()
        upfront = max(0, (inv.paid_amount or 0) - linked)
        if upfront > 0:
            if inv.payment_type == 'cash':
                lbl = 'مدفوع نقدي مع الفاتورة'
            elif inv.payment_type == 'installment':
                lbl = 'مقدم تقسيط'
            else:
                lbl = 'مدفوع مع الفاتورة'
            entries.append({'date': inv.date, 'label': f'{lbl} - فاتورة {inv.invoice_number}',
                            'debit': 0, 'credit': upfront})

    for p in c.payments:
        lbl = f"دفعة ({PAYMENT_METHODS.get(p.payment_method, 'كاش')})"
        if p.invoice_id and p.invoice:
            lbl += f' - فاتورة {p.invoice.invoice_number}'
        if p.notes:
            lbl += f' ({p.notes})'
        entries.append({'date': p.date, 'label': lbl, 'debit': 0, 'credit': p.amount or 0})

    for r in c.returns:
        lbl = 'مرتجع بضاعة'
        if r.invoice_id and r.invoice:
            lbl += f' - فاتورة {r.invoice.invoice_number}'
        if r.reason:
            lbl += f' ({r.reason})'
        entries.append({'date': r.date, 'label': lbl, 'debit': 0, 'credit': r.total_amount or 0})

    for plan in c.installment_plans:
        for pay in plan.payments:
            lbl = f"دفعة قسط ({PAYMENT_METHODS.get(pay.payment_method, 'كاش')}) - خطة {plan.plan_number}"
            if pay.notes:
                lbl += f' ({pay.notes})'
            entries.append({'date': pay.date, 'label': lbl, 'debit': 0, 'credit': pay.amount or 0})

    entries.sort(key=lambda e: e['date'])
    return entries


@app.route('/customers/<int:customer_id>/statement')
@login_required
def customer_statement(customer_id):
    c = Customer.query.get_or_404(customer_id)
    entries = _customer_statement_rows(c)

    balance = 0
    for e in entries:
        balance += e['debit'] - e['credit']
        e['balance'] = balance

    return render_template('customer_statement.html', customer=c, entries=entries,
        totals_debit=sum(e['debit'] for e in entries),
        totals_credit=sum(e['credit'] for e in entries),
        final_balance=balance, now=datetime.now(), PAYMENT_TYPES=PAYMENT_TYPES)


@app.route('/reports/customers-statement')
@login_required
def customers_statement_all():
    customers = Customer.query.order_by(Customer.name).all()
    rows = []
    for c in customers:
        entries = _customer_statement_rows(c)
        debit = sum(e['debit'] for e in entries)
        credit = sum(e['credit'] for e in entries)
        rows.append({'customer': c, 'debit': debit, 'credit': credit, 'balance': debit - credit})
    rows.sort(key=lambda r: r['balance'], reverse=True)
    return render_template('customers_statement_all.html', rows=rows,
        totals_debit=sum(r['debit'] for r in rows),
        totals_credit=sum(r['credit'] for r in rows),
        total_balance=sum(r['balance'] for r in rows),
        now=datetime.now())


@app.route('/customers/<int:customer_id>/edit', methods=['GET', 'POST'])
@login_required
def customer_edit(customer_id):
    c = Customer.query.get_or_404(customer_id)
    if request.method == 'POST':
        c.name = request.form['name']
        c.phone = request.form.get('phone', '')
        c.address = request.form.get('address', '')
        c.account_type = request.form['account_type']
        c.notes = request.form.get('notes', '')
        db.session.commit()
        flash('تم تعديل بيانات العميل بنجاح', 'success')
        return redirect(url_for('customer_profile', customer_id=c.id))
    return render_template('customer_form.html', ACCOUNT_TYPES=ACCOUNT_TYPES, customer=c)


@app.route('/customers/<int:customer_id>/delete', methods=['POST'])
@login_required
def customer_delete(customer_id):
    c = Customer.query.get_or_404(customer_id)
    for plan in c.installment_plans:
        InstallmentPayment.query.filter_by(plan_id=plan.id).delete()
        Installment.query.filter_by(plan_id=plan.id).delete()
    InstallmentPlan.query.filter_by(customer_id=c.id).delete()
    InvoiceItem.query.filter(InvoiceItem.invoice_id.in_(
        db.session.query(Invoice.id).filter_by(customer_id=c.id)
    )).delete(synchronize_session='fetch')
    Invoice.query.filter_by(customer_id=c.id).delete()
    Payment.query.filter_by(customer_id=c.id).delete()
    ReturnItem.query.filter(ReturnItem.return_id.in_(
        db.session.query(Return.id).filter_by(customer_id=c.id)
    )).delete(synchronize_session='fetch')
    Return.query.filter_by(customer_id=c.id).delete()
    db.session.delete(c)
    db.session.commit()
    flash('تم حذف العميل بنجاح', 'success')
    return redirect(url_for('customers_list'))


@app.route('/invoices')
@login_required
def invoices_list():
    search = request.args.get('search', '')
    payment_type = request.args.get('payment_type', '')
    query = Invoice.query
    if search:
        query = query.join(Customer).filter(
            Invoice.invoice_number.contains(search) | Customer.name.contains(search)
        )
    if payment_type:
        query = query.filter_by(payment_type=payment_type)
    invoices = query.order_by(Invoice.date.desc()).all()
    return render_template('invoices_list.html', invoices=invoices, search=search,
        payment_type=payment_type, PAYMENT_TYPES=PAYMENT_TYPES)


@app.route('/invoices/add', methods=['GET', 'POST'])
@login_required
def invoice_add():
    customers = Customer.query.order_by(Customer.name).all()
    if request.method == 'POST':
        payment_type = request.form.get('payment_type', 'cash')
        inv = Invoice(
            invoice_number=generate_invoice_number(),
            customer_id=int(request.form['customer_id']),
            shipping_company=request.form.get('shipping_company', ''),
            payment_type=payment_type,
            show_balance=bool(request.form.get('show_balance')),
            payment_method=request.form.get('payment_method', 'cash') if payment_type in ('cash', 'installment') else 'cash',
            receipt_image=save_receipt_image(request.files.get('receipt_image')),
            notes=request.form.get('notes', '')
        )
        db.session.add(inv)
        db.session.flush()
        total = 0
        i = 0
        while True:
            iname = request.form.get(f'item_name_{i}', '')
            if not iname:
                i += 1
                if i > 350:
                    break
                continue
            qty = float(request.form.get(f'item_qty_{i}', 0))
            price = float(request.form.get(f'item_price_{i}', 0))
            unit_type = request.form.get(f'item_unit_{i}', 'ق')
            item_total = qty * price
            item = InvoiceItem(
                invoice_id=inv.id,
                item_name=iname,
                unit_type=unit_type,
                quantity=qty,
                unit_price=price,
                total=item_total
            )
            db.session.add(item)
            total += item_total
            i += 1
            if i > 350:
                break
        inv.total = total
        discount = float(request.form.get('discount', 0) or 0)
        inv.discount = discount
        net = max(0, total - discount)

        if payment_type == 'cash':
            inv.paid_amount = net
            inv.remaining = 0
        elif payment_type == 'credit':
            inv.paid_amount = 0
            inv.remaining = net
        elif payment_type == 'installment':
            down = float(request.form.get('down_payment', 0) or 0)
            inv.paid_amount = down
            inv.remaining = net - down

            count = int(request.form.get('installment_count', 1) or 1)
            start_str = request.form.get('installment_start_date', '')
            if start_str:
                start_date = datetime.strptime(start_str, '%Y-%m-%d').date()
            else:
                start_date = date.today()

            remaining_amount = net - down
            inst_amount = round(remaining_amount / count, 2) if count > 0 else remaining_amount

            plan = InstallmentPlan(
                customer_id=inv.customer_id,
                invoice_id=inv.id,
                plan_number=generate_plan_number(),
                total_amount=net,
                down_payment=down,
                installment_count=count,
                installment_amount=inst_amount,
                remaining=remaining_amount,
                start_date=start_date,
                status='active',
                notes=inv.notes
            )
            db.session.add(plan)
            db.session.flush()

            for j in range(count):
                inst_date = start_date + relativedelta(months=j)
                inst = Installment(
                    plan_id=plan.id,
                    number=j + 1,
                    amount=inst_amount,
                    due_date=inst_date,
                    status='pending'
                )
                db.session.add(inst)

            if down > 0:
                plan.down_payment = down
                plan.remaining = remaining_amount

        db.session.commit()
        customer_id = int(request.form['customer_id'])
        EntityLock.query.filter_by(entity_type='customer', entity_id=customer_id, user_id=session['user_id']).delete()
        db.session.commit()
        flash(f'تم انشاء الفاتورة {inv.invoice_number} بنجاح', 'success')
        return redirect(url_for('invoice_view', invoice_id=inv.id))
    return render_template('invoice_form.html', customers=customers, invoice=None,
        PAYMENT_TYPES=PAYMENT_TYPES)


@app.route('/invoices/<int:invoice_id>/edit', methods=['GET', 'POST'])
@login_required
def invoice_edit(invoice_id):
    inv = Invoice.query.get_or_404(invoice_id)
    customers = Customer.query.order_by(Customer.name).all()

    if request.method == 'POST':
        inv.customer_id = int(request.form['customer_id'])
        inv.shipping_company = request.form.get('shipping_company', '')
        inv.show_balance = bool(request.form.get('show_balance'))
        if inv.payment_type in ('cash', 'installment'):
            inv.payment_method = request.form.get('payment_method', 'cash')
        else:
            inv.payment_method = 'cash'
        new_receipt = save_receipt_image(request.files.get('receipt_image'))
        if new_receipt:
            delete_receipt_image(inv.receipt_image)
            inv.receipt_image = new_receipt
        inv.notes = request.form.get('notes', '')

        InvoiceItem.query.filter_by(invoice_id=inv.id).delete()

        total = 0
        i = 0
        while True:
            iname = request.form.get(f'item_name_{i}', '')
            if not iname:
                i += 1
                if i > 350:
                    break
                continue
            qty = float(request.form.get(f'item_qty_{i}', 0))
            price = float(request.form.get(f'item_price_{i}', 0))
            unit_type = request.form.get(f'item_unit_{i}', 'ق')
            item_total = qty * price
            item = InvoiceItem(
                invoice_id=inv.id,
                item_name=iname,
                unit_type=unit_type,
                quantity=qty,
                unit_price=price,
                total=item_total
            )
            db.session.add(item)
            total += item_total
            i += 1
            if i > 350:
                break
        inv.total = total
        discount = float(request.form.get('discount', 0) or 0)
        inv.discount = discount
        net = max(0, total - discount)

        payments_total = db.session.query(
            db.func.coalesce(db.func.sum(Payment.amount), 0)
        ).filter(Payment.invoice_id == inv.id).scalar()

        inv.paid_amount = payments_total
        inv.remaining = max(0, net - payments_total)

        if inv.payment_type == 'installment':
            plan = InstallmentPlan.query.filter_by(invoice_id=inv.id).first()
            if plan:
                down = float(request.form.get('down_payment', 0) or 0)
                count = int(request.form.get('installment_count', 1) or 1)
                start_str = request.form.get('installment_start_date', '')
                start_date = datetime.strptime(start_str, '%Y-%m-%d').date() if start_str else date.today()

                Installment.query.filter_by(plan_id=plan.id).delete()

                remaining_amount = net - down
                inst_amount = round(remaining_amount / count, 2) if count > 0 else remaining_amount

                plan.total_amount = net
                plan.down_payment = down
                plan.installment_count = count
                plan.installment_amount = inst_amount
                plan.remaining = remaining_amount
                plan.start_date = start_date

                for j in range(count):
                    inst_date = start_date + relativedelta(months=j)
                    inst = Installment(
                        plan_id=plan.id,
                        number=j + 1,
                        amount=inst_amount,
                        due_date=inst_date,
                        status='pending'
                    )
                    db.session.add(inst)

        db.session.commit()
        flash(f'تم تعديل الفاتورة {inv.invoice_number} بنجاح', 'success')
        return redirect(url_for('invoice_view', invoice_id=inv.id))

    return render_template('invoice_form.html', customers=customers, invoice=inv,
        PAYMENT_TYPES=PAYMENT_TYPES,
        installment_plan=InstallmentPlan.query.filter_by(invoice_id=inv.id).first())


@app.route('/invoices/<int:invoice_id>')
@login_required
def invoice_view(invoice_id):
    inv = Invoice.query.get_or_404(invoice_id)
    return_items = []
    for r in inv.returns:
        return_items.extend(r.items)
    return_amount = sum(r.total_amount for r in inv.returns)
    installment_plan = InstallmentPlan.query.filter_by(invoice_id=inv.id).first()
    installments = installment_plan.installments if installment_plan else []
    installment_payments = installment_plan.payments if installment_plan else []
    cust_id = inv.customer_id
    cust_balance_invs = Invoice.query.filter(Invoice.customer_id == cust_id).all()
    cust_balance_total = 0
    cust_balance_list = []
    for bi in cust_balance_invs:
        paid_for_inv = db.session.query(db.func.coalesce(db.func.sum(Payment.amount), 0)).filter(Payment.invoice_id == bi.id).scalar()
        net = max(0, (bi.total or 0) - (bi.discount or 0))
        rem = max(0, net - paid_for_inv)
        if rem > 0:
            cust_balance_total += rem
            cust_balance_list.append({
                'number': bi.invoice_number, 'total': net,
                'paid': paid_for_inv, 'remaining': rem
            })
    return render_template('invoice_view.html', invoice=inv,
        return_items=return_items, return_amount=return_amount,
        installment_plan=installment_plan, installments=installments,
        installment_payments=installment_payments, PAYMENT_TYPES=PAYMENT_TYPES,
        cust_balance_total=cust_balance_total, cust_balance_list=cust_balance_list)


@app.route('/invoices/<int:invoice_id>/delete', methods=['POST'])
@login_required
def invoice_delete(invoice_id):
    inv = Invoice.query.get_or_404(invoice_id)
    plan = InstallmentPlan.query.filter_by(invoice_id=inv.id).first()
    if plan:
        InstallmentPayment.query.filter_by(plan_id=plan.id).delete()
        Installment.query.filter_by(plan_id=plan.id).delete()
        db.session.delete(plan)
    InvoiceItem.query.filter_by(invoice_id=inv.id).delete()
    ReturnItem.query.filter(ReturnItem.return_id.in_(
        db.session.query(Return.id).filter_by(invoice_id=inv.id)
    )).delete(synchronize_session='fetch')
    Return.query.filter_by(invoice_id=inv.id).delete()
    Payment.query.filter_by(invoice_id=inv.id).update({'invoice_id': None})
    db.session.delete(inv)
    db.session.commit()
    flash('تم حذف الفاتورة بنجاح', 'success')
    return redirect(url_for('invoices_list'))


@app.route('/customers/<int:customer_id>/pay', methods=['GET', 'POST'])
@login_required
def payment_add(customer_id):
    c = Customer.query.get_or_404(customer_id)
    unpaid_invoices = Invoice.query.filter(
        Invoice.customer_id == c.id,
        Invoice.is_returned == False,
        Invoice.remaining > 0
    ).all()
    if request.method == 'POST':
        amount = float(request.form['amount'])
        invoice_id = int(request.form.get('invoice_id')) if request.form.get('invoice_id') else None
        p = Payment(
            customer_id=c.id,
            amount=amount,
            invoice_id=invoice_id,
            notes=request.form.get('notes', ''),
            payment_method=request.form.get('payment_method', 'cash'),
            receipt_image=save_receipt_image(request.files.get('receipt_image')),
            next_payment_date=datetime.strptime(request.form['next_payment_date'], '%Y-%m-%d').date() if request.form.get('next_payment_date') else None,
            next_payment_amount=float(request.form['next_payment_amount']) if request.form.get('next_payment_amount') else None
        )
        db.session.add(p)

        if invoice_id:
            inv = Invoice.query.get(invoice_id)
            if inv:
                inv.paid_amount = (inv.paid_amount or 0) + amount
                inv.remaining = max(0, inv.total - inv.paid_amount)

        db.session.commit()
        flash('تم تسجيل الدفعة بنجاح', 'success')
        return redirect(url_for('customer_profile', customer_id=c.id))
    return render_template('payment_form.html', customer=c, unpaid_invoices=unpaid_invoices, payment=None)


@app.route('/payments/<int:payment_id>/edit', methods=['GET', 'POST'])
@login_required
def payment_edit(payment_id):
    p = Payment.query.get_or_404(payment_id)
    c = p.customer

    unpaid_invoices = Invoice.query.filter(
        Invoice.customer_id == c.id,
        Invoice.is_returned == False,
        Invoice.remaining > 0
    ).all()

    if p.invoice_id:
        current_inv = Invoice.query.get(p.invoice_id)
        if current_inv and current_inv.remaining <= 0:
            unpaid_invoices.append(current_inv)
        elif current_inv and current_inv not in unpaid_invoices:
            unpaid_invoices.insert(0, current_inv)

    if request.method == 'POST':
        old_amount = p.amount or 0
        old_invoice_id = p.invoice_id

        new_amount = float(request.form['amount'])
        new_invoice_id = int(request.form['invoice_id']) if request.form.get('invoice_id') else None

        if old_invoice_id:
            old_inv = Invoice.query.get(old_invoice_id)
            if old_inv:
                payments_total = db.session.query(
                    db.func.coalesce(db.func.sum(Payment.amount), 0)
                ).filter(Payment.invoice_id == old_inv.id, Payment.id != p.id).scalar()
                old_inv.paid_amount = payments_total
                old_inv.remaining = max(0, (old_inv.total or 0) - (old_inv.discount or 0) - payments_total)

        p.amount = new_amount
        p.invoice_id = new_invoice_id
        p.notes = request.form.get('notes', '')
        p.payment_method = request.form.get('payment_method', 'cash')
        new_receipt = save_receipt_image(request.files.get('receipt_image'))
        if new_receipt:
            delete_receipt_image(p.receipt_image)
            p.receipt_image = new_receipt
        p.next_payment_date = datetime.strptime(request.form['next_payment_date'], '%Y-%m-%d').date() if request.form.get('next_payment_date') else None
        p.next_payment_amount = float(request.form['next_payment_amount']) if request.form.get('next_payment_amount') else None

        if new_invoice_id:
            new_inv = Invoice.query.get(new_invoice_id)
            if new_inv:
                payments_total = db.session.query(
                    db.func.coalesce(db.func.sum(Payment.amount), 0)
                ).filter(Payment.invoice_id == new_inv.id, Payment.id != p.id).scalar()
                new_inv.paid_amount = payments_total + new_amount
                new_inv.remaining = max(0, (new_inv.total or 0) - (new_inv.discount or 0) - new_inv.paid_amount)

        db.session.commit()
        flash('تم تعديل الدفعة بنجاح', 'success')
        return redirect(url_for('customer_profile', customer_id=c.id))

    return render_template('payment_form.html', customer=c, unpaid_invoices=unpaid_invoices, payment=p)


@app.route('/customers/<int:customer_id>/return', methods=['GET', 'POST'])
@login_required
def return_add(customer_id):
    c = Customer.query.get_or_404(customer_id)
    invoices = Invoice.query.filter_by(customer_id=c.id, is_returned=False).all()
    if request.method == 'POST':
        r = Return(
            customer_id=c.id,
            invoice_id=int(request.form['invoice_id']) if request.form.get('invoice_id') else None,
            reason=request.form.get('reason', '')
        )
        db.session.add(r)
        db.session.flush()
        total = 0
        i = 0
        while True:
            iname = request.form.get(f'item_name_{i}', '')
            if not iname:
                i += 1
                if i > 50:
                    break
                continue
            qty = float(request.form.get(f'item_qty_{i}', 0))
            price = float(request.form.get(f'item_price_{i}', 0))
            unit_type = request.form.get(f'item_unit_{i}', 'ق')
            item_total = qty * price
            ri = ReturnItem(
                return_id=r.id,
                item_name=iname,
                unit_type=unit_type,
                quantity=qty,
                unit_price=price,
                total=item_total
            )
            db.session.add(ri)
            total += item_total
            i += 1
            if i > 50:
                break
        r.total_amount = total
        db.session.commit()
        flash('تم تسجيل المرتجع بنجاح', 'success')
        return redirect(url_for('customer_profile', customer_id=c.id))
    return render_template('return_form.html', customer=c, invoices=invoices)


@app.route('/customers/<int:customer_id>/return/<int:return_id>/edit', methods=['GET', 'POST'])
@login_required
def return_edit(customer_id, return_id):
    c = Customer.query.get_or_404(customer_id)
    r = Return.query.filter_by(id=return_id, customer_id=c.id).first_or_404()
    invoices = Invoice.query.filter_by(customer_id=c.id, is_returned=False).all()
    if request.method == 'POST':
        r.invoice_id = int(request.form['invoice_id']) if request.form.get('invoice_id') else None
        r.reason = request.form.get('reason', '')
        ReturnItem.query.filter_by(return_id=r.id).delete()
        db.session.flush()
        total = 0
        i = 0
        while True:
            iname = request.form.get(f'item_name_{i}', '')
            if not iname:
                i += 1
                if i > 50:
                    break
                continue
            qty = float(request.form.get(f'item_qty_{i}', 0))
            price = float(request.form.get(f'item_price_{i}', 0))
            unit_type = request.form.get(f'item_unit_{i}', 'ق')
            item_total = qty * price
            ri = ReturnItem(
                return_id=r.id,
                item_name=iname,
                unit_type=unit_type,
                quantity=qty,
                unit_price=price,
                total=item_total
            )
            db.session.add(ri)
            total += item_total
            i += 1
            if i > 50:
                break
        r.total_amount = total
        db.session.commit()
        flash('تم تعديل المرتجع بنجاح', 'success')
        return redirect(url_for('customer_profile', customer_id=c.id))
    return render_template('return_form.html', customer=c, invoices=invoices, ret=r)


@app.route('/payments')
@login_required
def payments_list():
    search = request.args.get('search', '')
    query = Payment.query
    if search:
        query = query.join(Customer).filter(Customer.name.contains(search))
    payments = query.order_by(Payment.date.desc()).all()
    return render_template('payments_list.html', payments=payments, search=search)


@app.route('/installments')
@login_required
def installments_list():
    status = request.args.get('status', '')
    query = InstallmentPlan.query
    if status:
        query = query.filter_by(status=status)
    plans = query.order_by(InstallmentPlan.date.desc()).all()
    return render_template('installments_list.html', plans=plans, status=status,
        INSTALLMENT_STATUS=INSTALLMENT_STATUS, PAYMENT_TYPES=PAYMENT_TYPES)


@app.route('/installments/<int:plan_id>')
@login_required
def installment_view(plan_id):
    plan = InstallmentPlan.query.get_or_404(plan_id)
    return render_template('installment_view.html', plan=plan,
        INSTALLMENT_STATUS=INSTALLMENT_STATUS)


@app.route('/installments/<int:plan_id>/pay', methods=['GET', 'POST'])
@login_required
def installment_pay(plan_id):
    plan = InstallmentPlan.query.get_or_404(plan_id)
    from datetime import date as dt_date
    today = dt_date.today()
    pending_installments = [inst for inst in plan.installments if inst.status == 'pending']
    if request.method == 'POST':
        amount = float(request.form['amount'])
        installment_id = int(request.form['installment_id']) if request.form.get('installment_id') else None
        notes = request.form.get('notes', '')

        pmt = InstallmentPayment(
            plan_id=plan.id,
            installment_id=installment_id,
            amount=amount,
            notes=notes,
            payment_method=request.form.get('payment_method', 'cash'),
            receipt_image=save_receipt_image(request.files.get('receipt_image'))
        )
        db.session.add(pmt)

        if installment_id:
            inst = Installment.query.get(installment_id)
            if inst:
                total_paid_for_inst = sum(
                    pay.amount for pay in plan.payments if pay.installment_id == installment_id
                ) + amount
                if total_paid_for_inst >= inst.amount:
                    inst.status = 'paid'
                    inst.paid_date = today

        plan.remaining = max(0, plan.remaining - amount)

        all_paid = all(inst.status == 'paid' for inst in plan.installments)
        if all_paid:
            plan.status = 'completed'
        elif plan.remaining <= 0:
            plan.status = 'completed'

        if plan.invoice_id:
            inv = Invoice.query.get(plan.invoice_id)
            if inv:
                inv.paid_amount = (inv.paid_amount or 0) + amount
                inv.remaining = max(0, inv.total - inv.paid_amount)

        db.session.commit()
        flash('تم تسجيل الدفعة بنجاح', 'success')
        return redirect(url_for('installment_view', plan_id=plan.id))
    return render_template('installment_pay_form.html', plan=plan,
        pending_installments=pending_installments)


@app.route('/supplier-installments')
@login_required
def supplier_installments_list():
    status = request.args.get('status', '')
    query = SupplierInstallmentPlan.query
    if status:
        query = query.filter_by(status=status)
    plans = query.order_by(SupplierInstallmentPlan.date.desc()).all()
    return render_template('supplier_installments_list.html', plans=plans, status=status,
        INSTALLMENT_STATUS=INSTALLMENT_STATUS)


@app.route('/supplier-installments/<int:plan_id>')
@login_required
def supplier_installment_view(plan_id):
    plan = SupplierInstallmentPlan.query.get_or_404(plan_id)
    return render_template('supplier_installment_view.html', plan=plan,
        INSTALLMENT_STATUS=INSTALLMENT_STATUS)


@app.route('/supplier-installments/<int:plan_id>/pay', methods=['GET', 'POST'])
@login_required
def supplier_installment_pay(plan_id):
    plan = SupplierInstallmentPlan.query.get_or_404(plan_id)
    from datetime import date as dt_date
    today = dt_date.today()
    pending_installments = [inst for inst in plan.installments if inst.status == 'pending']
    if request.method == 'POST':
        amount = float(request.form['amount'])
        installment_id = int(request.form['installment_id']) if request.form.get('installment_id') else None
        notes = request.form.get('notes', '')

        pmt = SupplierInstallmentPayment(
            plan_id=plan.id,
            installment_id=installment_id,
            amount=amount,
            notes=notes,
            payment_method=request.form.get('payment_method', 'cash'),
            receipt_image=save_receipt_image(request.files.get('receipt_image'))
        )
        db.session.add(pmt)

        if installment_id:
            inst = SupplierInstallment.query.get(installment_id)
            if inst:
                total_paid_for_inst = sum(
                    pay.amount for pay in plan.payments if pay.installment_id == installment_id
                ) + amount
                if total_paid_for_inst >= inst.amount:
                    inst.status = 'paid'
                    inst.paid_date = today

        plan.remaining = max(0, plan.remaining - amount)

        all_paid = all(inst.status == 'paid' for inst in plan.installments)
        if all_paid:
            plan.status = 'completed'
        elif plan.remaining <= 0:
            plan.status = 'completed'

        if plan.purchase_id:
            pur = Purchase.query.get(plan.purchase_id)
            if pur:
                pur.paid_amount = (pur.paid_amount or 0) + amount
                pur.remaining = max(0, pur.total - pur.paid_amount)

        db.session.commit()
        flash('تم تسجيل الدفعة بنجاح', 'success')
        return redirect(url_for('supplier_installment_view', plan_id=plan.id))
    return render_template('supplier_installment_pay_form.html', plan=plan,
        pending_installments=pending_installments)


@app.route('/suppliers')
@login_required
def suppliers_list():
    search = request.args.get('search', '')
    query = Supplier.query
    if search:
        query = query.filter(Supplier.name.contains(search) | Supplier.phone.contains(search))
    suppliers = query.order_by(Supplier.name).all()
    return render_template('suppliers_list.html', suppliers=suppliers, search=search)


@app.route('/suppliers/add', methods=['GET', 'POST'])
@login_required
def supplier_add():
    if request.method == 'POST':
        s = Supplier(
            name=request.form['name'],
            phone=request.form.get('phone', ''),
            address=request.form.get('address', ''),
            notes=request.form.get('notes', '')
        )
        db.session.add(s)
        db.session.commit()
        flash('تم اضافة المورد بنجاح', 'success')
        return redirect(url_for('supplier_profile', supplier_id=s.id))
    return render_template('supplier_form.html', supplier=None)


@app.route('/suppliers/<int:supplier_id>')
@login_required
def supplier_profile(supplier_id):
    s = Supplier.query.get_or_404(supplier_id)
    purchases = Purchase.query.filter_by(supplier_id=s.id).order_by(Purchase.date.desc()).all()
    payments = SupplierPayment.query.filter_by(supplier_id=s.id).order_by(SupplierPayment.date.desc()).all()
    installment_plans = SupplierInstallmentPlan.query.filter_by(supplier_id=s.id).order_by(SupplierInstallmentPlan.date.desc()).all()
    return render_template('supplier_profile.html', supplier=s,
        purchases=purchases, payments=payments,
        installment_plans=installment_plans, PAYMENT_TYPES=PAYMENT_TYPES)


def _supplier_statement_rows(s):
    entries = []

    for pur in s.purchases:
        entries.append({'date': pur.date, 'label': f'فاتورة مشتريات رقم {pur.purchase_number}',
                        'debit': pur.total or 0, 'credit': 0})
        linked = db.session.query(db.func.coalesce(db.func.sum(SupplierPayment.amount), 0)).filter(
            SupplierPayment.purchase_id == pur.id).scalar()
        upfront = max(0, (pur.paid_amount or 0) - linked)
        if upfront > 0:
            if pur.payment_type == 'cash':
                lbl = 'مدفوع نقدي مع امر الشراء'
            elif pur.payment_type == 'installment':
                lbl = 'مقدم تقسيط'
            else:
                lbl = 'مدفوع مع امر الشراء'
            entries.append({'date': pur.date, 'label': f'{lbl} - {pur.purchase_number}',
                            'debit': 0, 'credit': upfront})

    for p in s.payments:
        lbl = f"دفعة للمورد ({PAYMENT_METHODS.get(p.payment_method, 'كاش')})"
        if p.purchase_id and p.purchase:
            lbl += f' - {p.purchase.purchase_number}'
        if p.notes:
            lbl += f' ({p.notes})'
        entries.append({'date': p.date, 'label': lbl, 'debit': 0, 'credit': p.amount or 0})

    for plan in s.installment_plans:
        for pay in plan.payments:
            lbl = f"دفعة قسط مورد ({PAYMENT_METHODS.get(pay.payment_method, 'كاش')}) - خطة {plan.plan_number}"
            if pay.notes:
                lbl += f' ({pay.notes})'
            entries.append({'date': pay.date, 'label': lbl, 'debit': 0, 'credit': pay.amount or 0})

    entries.sort(key=lambda e: e['date'])
    return entries


@app.route('/suppliers/<int:supplier_id>/statement')
@login_required
def supplier_statement(supplier_id):
    s = Supplier.query.get_or_404(supplier_id)
    entries = _supplier_statement_rows(s)

    balance = 0
    for e in entries:
        balance += e['debit'] - e['credit']
        e['balance'] = balance

    return render_template('supplier_statement.html', supplier=s, entries=entries,
        totals_debit=sum(e['debit'] for e in entries),
        totals_credit=sum(e['credit'] for e in entries),
        final_balance=balance, now=datetime.now(), PAYMENT_TYPES=PAYMENT_TYPES)


@app.route('/reports/suppliers-statement')
@login_required
def suppliers_statement_all():
    suppliers = Supplier.query.order_by(Supplier.name).all()
    rows = []
    for s in suppliers:
        entries = _supplier_statement_rows(s)
        debit = sum(e['debit'] for e in entries)
        credit = sum(e['credit'] for e in entries)
        rows.append({'supplier': s, 'debit': debit, 'credit': credit, 'balance': debit - credit})
    rows.sort(key=lambda r: r['balance'], reverse=True)
    return render_template('suppliers_statement_all.html', rows=rows,
        totals_debit=sum(r['debit'] for r in rows),
        totals_credit=sum(r['credit'] for r in rows),
        total_balance=sum(r['balance'] for r in rows),
        now=datetime.now())


@app.route('/suppliers/<int:supplier_id>/edit', methods=['GET', 'POST'])
@login_required
def supplier_edit(supplier_id):
    s = Supplier.query.get_or_404(supplier_id)
    if request.method == 'POST':
        s.name = request.form['name']
        s.phone = request.form.get('phone', '')
        s.address = request.form.get('address', '')
        s.notes = request.form.get('notes', '')
        db.session.commit()
        flash('تم تعديل بيانات المورد بنجاح', 'success')
        return redirect(url_for('supplier_profile', supplier_id=s.id))
    return render_template('supplier_form.html', supplier=s)


@app.route('/suppliers/<int:supplier_id>/delete', methods=['POST'])
@login_required
def supplier_delete(supplier_id):
    s = Supplier.query.get_or_404(supplier_id)
    for plan in s.installment_plans:
        SupplierInstallmentPayment.query.filter_by(plan_id=plan.id).delete()
        SupplierInstallment.query.filter_by(plan_id=plan.id).delete()
    SupplierInstallmentPlan.query.filter_by(supplier_id=s.id).delete()
    PurchaseItem.query.filter(PurchaseItem.purchase_id.in_(
        db.session.query(Purchase.id).filter_by(supplier_id=s.id)
    )).delete(synchronize_session='fetch')
    Purchase.query.filter_by(supplier_id=s.id).delete()
    SupplierPayment.query.filter_by(supplier_id=s.id).delete()
    db.session.delete(s)
    db.session.commit()
    flash('تم حذف المورد بنجاح', 'success')
    return redirect(url_for('suppliers_list'))


@app.route('/suppliers/<int:supplier_id>/pay', methods=['GET', 'POST'])
@login_required
def supplier_payment_add(supplier_id):
    s = Supplier.query.get_or_404(supplier_id)
    unpaid_purchases = Purchase.query.filter(
        Purchase.supplier_id == s.id,
        Purchase.remaining > 0
    ).all()
    if request.method == 'POST':
        amount = float(request.form['amount'])
        purchase_id = int(request.form.get('purchase_id')) if request.form.get('purchase_id') else None
        p = SupplierPayment(
            supplier_id=s.id,
            amount=amount,
            purchase_id=purchase_id,
            notes=request.form.get('notes', ''),
            payment_method=request.form.get('payment_method', 'cash'),
            receipt_image=save_receipt_image(request.files.get('receipt_image'))
        )
        db.session.add(p)

        if purchase_id:
            pur = Purchase.query.get(purchase_id)
            if pur:
                pur.paid_amount = (pur.paid_amount or 0) + amount
                pur.remaining = max(0, pur.total - pur.paid_amount)

        db.session.commit()
        flash('تم تسجيل الدفعة بنجاح', 'success')
        return redirect(url_for('supplier_profile', supplier_id=s.id))
    return render_template('supplier_payment_form.html', supplier=s, unpaid_purchases=unpaid_purchases)


@app.route('/purchases')
@login_required
def purchases_list():
    search = request.args.get('search', '')
    payment_type = request.args.get('payment_type', '')
    query = Purchase.query
    if search:
        query = query.join(Supplier).filter(
            Purchase.purchase_number.contains(search) | Supplier.name.contains(search)
        )
    if payment_type:
        query = query.filter_by(payment_type=payment_type)
    purchases = query.order_by(Purchase.date.desc()).all()
    return render_template('purchases_list.html', purchases=purchases, search=search,
        payment_type=payment_type, PAYMENT_TYPES=PAYMENT_TYPES)


@app.route('/purchases/add', methods=['GET', 'POST'])
@login_required
def purchase_add():
    suppliers = Supplier.query.order_by(Supplier.name).all()
    if request.method == 'POST':
        payment_type = request.form.get('payment_type', 'cash')
        p = Purchase(
            purchase_number=generate_purchase_number(),
            supplier_id=int(request.form['supplier_id']),
            payment_type=payment_type,
            payment_method=request.form.get('payment_method', 'cash') if payment_type in ('cash', 'installment') else 'cash',
            receipt_image=save_receipt_image(request.files.get('receipt_image')),
            notes=request.form.get('notes', '')
        )
        db.session.add(p)
        db.session.flush()
        total = 0
        i = 0
        while True:
            iname = request.form.get(f'item_name_{i}', '')
            if not iname:
                i += 1
                if i > 350:
                    break
                continue
            qty = float(request.form.get(f'item_qty_{i}', 0))
            price = float(request.form.get(f'item_price_{i}', 0))
            sell_price = float(request.form.get(f'item_sell_price_{i}', 0))
            unit_type = request.form.get(f'item_unit_{i}', 'ق')
            item_total = qty * price
            item = PurchaseItem(
                purchase_id=p.id,
                item_name=iname,
                unit_type=unit_type,
                quantity=qty,
                unit_price=price,
                selling_price=sell_price,
                total=item_total
            )
            db.session.add(item)
            total += item_total
            i += 1
            if i > 350:
                break
        p.total = total

        if payment_type == 'cash':
            p.paid_amount = total
            p.remaining = 0
        elif payment_type == 'credit':
            p.paid_amount = 0
            p.remaining = total
        elif payment_type == 'installment':
            down = float(request.form.get('down_payment', 0) or 0)
            p.paid_amount = down
            p.remaining = total - down

            count = int(request.form.get('installment_count', 1) or 1)
            start_str = request.form.get('installment_start_date', '')
            if start_str:
                start_date = datetime.strptime(start_str, '%Y-%m-%d').date()
            else:
                start_date = date.today()

            remaining_amount = total - down
            inst_amount = round(remaining_amount / count, 2) if count > 0 else remaining_amount

            plan = SupplierInstallmentPlan(
                supplier_id=p.supplier_id,
                purchase_id=p.id,
                plan_number=generate_supplier_plan_number(),
                total_amount=total,
                down_payment=down,
                installment_count=count,
                installment_amount=inst_amount,
                remaining=remaining_amount,
                start_date=start_date,
                status='active',
                notes=p.notes
            )
            db.session.add(plan)
            db.session.flush()

            for j in range(count):
                inst_date = start_date + relativedelta(months=j)
                inst = SupplierInstallment(
                    plan_id=plan.id,
                    number=j + 1,
                    amount=inst_amount,
                    due_date=inst_date,
                    status='pending'
                )
                db.session.add(inst)

            if down > 0:
                plan.down_payment = down
                plan.remaining = remaining_amount

        db.session.commit()
        supplier_id = int(request.form['supplier_id'])
        EntityLock.query.filter_by(entity_type='supplier', entity_id=supplier_id, user_id=session['user_id']).delete()
        db.session.commit()
        flash(f'تم انشاء امر الشراء {p.purchase_number} بنجاح', 'success')
        return redirect(url_for('purchase_view', purchase_id=p.id))
    return render_template('purchase_form.html', suppliers=suppliers,
        PAYMENT_TYPES=PAYMENT_TYPES)


@app.route('/purchases/<int:purchase_id>')
@login_required
def purchase_view(purchase_id):
    p = Purchase.query.get_or_404(purchase_id)
    installment_plan = SupplierInstallmentPlan.query.filter_by(purchase_id=p.id).first()
    installments = installment_plan.installments if installment_plan else []
    installment_payments = installment_plan.payments if installment_plan else []
    return render_template('purchase_view.html', purchase=p,
        supplier_installment_plan=installment_plan, installments=installments,
        installment_payments=installment_payments, PAYMENT_TYPES=PAYMENT_TYPES)


@app.route('/purchases/<int:purchase_id>/delete', methods=['POST'])
@login_required
def purchase_delete(purchase_id):
    p = Purchase.query.get_or_404(purchase_id)
    plan = SupplierInstallmentPlan.query.filter_by(purchase_id=p.id).first()
    if plan:
        SupplierInstallmentPayment.query.filter_by(plan_id=plan.id).delete()
        SupplierInstallment.query.filter_by(plan_id=plan.id).delete()
        db.session.delete(plan)
    PurchaseItem.query.filter_by(purchase_id=p.id).delete()
    db.session.delete(p)
    db.session.commit()
    flash('تم حذف امر الشراء بنجاح', 'success')
    return redirect(url_for('purchases_list'))


@app.route('/shipping')
@login_required
def shipping_list():
    companies = ShippingCompany.query.order_by(ShippingCompany.name).all()
    return render_template('shipping_list.html', companies=companies)


@app.route('/shipping/add', methods=['GET', 'POST'])
@login_required
def shipping_add():
    if request.method == 'POST':
        c = ShippingCompany(
            name=request.form['name'].strip(),
            phone=request.form.get('phone', '').strip(),
            contact_person=request.form.get('contact_person', '').strip(),
            address=request.form.get('address', '').strip(),
            notes=request.form.get('notes', '').strip()
        )
        db.session.add(c)
        db.session.commit()
        flash('تم اضافة شركة الشحن بنجاح', 'success')
        return redirect(url_for('shipping_list'))
    return render_template('shipping_form.html', company=None)


@app.route('/shipping/<int:company_id>')
@login_required
def shipping_profile(company_id):
    c = ShippingCompany.query.get_or_404(company_id)
    invoices = Invoice.query.filter_by(shipping_company=c.name).order_by(Invoice.date.desc()).all()
    return render_template('shipping_profile.html', company=c, invoices=invoices)


@app.route('/shipping/<int:company_id>/edit', methods=['GET', 'POST'])
@login_required
def shipping_edit(company_id):
    c = ShippingCompany.query.get_or_404(company_id)
    old_name = c.name
    if request.method == 'POST':
        new_name = request.form['name'].strip()
        if new_name != old_name:
            Invoice.query.filter_by(shipping_company=old_name).update({'shipping_company': new_name})
        c.name = new_name
        c.phone = request.form.get('phone', '').strip()
        c.contact_person = request.form.get('contact_person', '').strip()
        c.address = request.form.get('address', '').strip()
        c.notes = request.form.get('notes', '').strip()
        db.session.commit()
        flash('تم تعديل شركة الشحن بنجاح', 'success')
        return redirect(url_for('shipping_profile', company_id=c.id))
    return render_template('shipping_form.html', company=c)


@app.route('/shipping/<int:company_id>/delete', methods=['POST'])
@login_required
def shipping_delete(company_id):
    c = ShippingCompany.query.get_or_404(company_id)
    db.session.delete(c)
    db.session.commit()
    flash('تم حذف شركة الشحن بنجاح', 'success')
    return redirect(url_for('shipping_list'))


@app.route('/api/search-shipping')
@login_required
def api_search_shipping():
    q = request.args.get('q', '').strip()
    if not q:
        return jsonify([])
    companies = ShippingCompany.query.filter(
        ShippingCompany.name.like(f'%{q}%')
    ).limit(15).all()
    return jsonify([{'id': c.id, 'name': c.name, 'phone': c.phone or ''} for c in companies])


@app.route('/api/customer-balance')
@login_required
def api_customer_balance():
    customer_id = request.args.get('customer_id', type=int)
    if not customer_id:
        return jsonify({'total_remaining': 0, 'invoices': []})
    invs = Invoice.query.filter(Invoice.customer_id == customer_id).all()
    result = []
    total = 0
    for inv in invs:
        paid_for_inv = db.session.query(db.func.coalesce(db.func.sum(Payment.amount), 0)).filter(Payment.invoice_id == inv.id).scalar()
        net = max(0, (inv.total or 0) - (inv.discount or 0))
        rem = max(0, net - paid_for_inv)
        if rem > 0:
            total += rem
            result.append({
                'invoice_number': inv.invoice_number,
                'total': net,
                'paid': paid_for_inv,
                'remaining': rem
            })
    return jsonify({'total_remaining': total, 'invoices': result})


@app.route('/api/dashboard-data')
@login_required
def api_dashboard_data():
    monthly_data = []
    all_invoices = Invoice.query.filter_by(is_returned=False).all()
    all_payments = Payment.query.all()
    now = datetime.utcnow()
    for i in range(11, -1, -1):
        month = now.month - i
        year = now.year
        if month <= 0:
            month += 12
            year -= 1
        rev = sum(inv.total for inv in all_invoices if inv.date.year == year and inv.date.month == month)
        paid = sum(p.amount for p in all_payments if p.date.year == year and p.date.month == month)
        monthly_data.append({'month': f"{year}-{month:02d}", 'revenue': rev, 'paid': paid})
    return jsonify(monthly_data)


@app.route('/api/search-items')
@login_required
def api_search_items():
    q = request.args.get('q', '').strip()
    if len(q) < 1:
        return jsonify([])
    items = db.session.query(InvoiceItem.item_name).distinct().filter(
        InvoiceItem.item_name.like(f'%{q}%')
    ).limit(15).all()
    purchase_items = db.session.query(PurchaseItem.item_name).distinct().filter(
        PurchaseItem.item_name.like(f'%{q}%')
    ).limit(15).all()
    all_names = set()
    for row in items:
        all_names.add(row[0])
    for row in purchase_items:
        all_names.add(row[0])
    return jsonify(sorted(all_names))


@app.route('/api/search-customers')
@login_required
def api_search_customers():
    q = request.args.get('q', '').strip()
    if not q:
        return jsonify([])
    customers = Customer.query.filter(
        Customer.name.like(f'%{q}%')
    ).limit(15).all()
    return jsonify([{'id': c.id, 'name': c.name, 'phone': c.phone or ''} for c in customers])


@app.route('/api/search-suppliers')
@login_required
def api_search_suppliers():
    q = request.args.get('q', '').strip()
    if not q:
        return jsonify([])
    suppliers = Supplier.query.filter(
        Supplier.name.like(f'%{q}%')
    ).limit(15).all()
    return jsonify([{'id': s.id, 'name': s.name, 'phone': s.phone or ''} for s in suppliers])


@app.route('/api/item-price')
@login_required
def api_item_price():
    name = request.args.get('name', '').strip()
    if not name:
        return jsonify({'found': False})
    item = PurchaseItem.query.filter(
        PurchaseItem.item_name == name
    ).order_by(PurchaseItem.id.desc()).first()
    if item and item.selling_price > 0:
        return jsonify({
            'found': True,
            'selling_price': item.selling_price,
            'unit_price': item.unit_price
        })
    inv_item = InvoiceItem.query.filter(
        InvoiceItem.item_name == name
    ).order_by(InvoiceItem.id.desc()).first()
    if inv_item:
        return jsonify({
            'found': True,
            'selling_price': inv_item.unit_price,
            'unit_price': item.unit_price if item else 0
        })
    return jsonify({'found': False})


LOCK_TIMEOUT = 120


def clean_stale_locks():
    stale = datetime.utcnow() - timedelta(seconds=LOCK_TIMEOUT)
    EntityLock.query.filter(EntityLock.heartbeat < stale).delete()
    db.session.commit()


@app.route('/api/lock-entity', methods=['POST'])
@login_required
def api_lock_entity():
    clean_stale_locks()
    data = request.get_json()
    entity_type = data.get('type', 'customer')
    entity_id = data.get('id')
    user_id = session['user_id']
    if not entity_id:
        return jsonify({'locked': False, 'error': 'missing id'}), 400
    existing = EntityLock.query.filter_by(
        entity_type=entity_type, entity_id=entity_id
    ).first()
    if existing:
        if existing.user_id == user_id:
            existing.heartbeat = datetime.utcnow()
            db.session.commit()
            return jsonify({'locked': True, 'owner': 'self'})
        lock_user = User.query.get(existing.user_id)
        return jsonify({
            'locked': False,
            'held_by': lock_user.full_name or lock_user.username,
            'held_at': existing.locked_at.strftime('%H:%M')
        })
    lock = EntityLock(
        entity_type=entity_type,
        entity_id=entity_id,
        user_id=user_id
    )
    db.session.add(lock)
    db.session.commit()
    return jsonify({'locked': True, 'owner': 'self'})


@app.route('/api/unlock-entity', methods=['POST'])
@login_required
def api_unlock_entity():
    data = request.get_json()
    entity_type = data.get('type', 'customer')
    entity_id = data.get('id')
    user_id = session['user_id']
    EntityLock.query.filter_by(
        entity_type=entity_type, entity_id=entity_id, user_id=user_id
    ).delete()
    db.session.commit()
    return jsonify({'ok': True})


@app.route('/api/heartbeat-entity', methods=['POST'])
@login_required
def api_heartbeat_entity():
    data = request.get_json()
    entity_type = data.get('type', 'customer')
    entity_id = data.get('id')
    user_id = session['user_id']
    lock = EntityLock.query.filter_by(
        entity_type=entity_type, entity_id=entity_id, user_id=user_id
    ).first()
    if lock:
        lock.heartbeat = datetime.utcnow()
        db.session.commit()
    return jsonify({'ok': True})


@app.route('/api/check-lock', methods=['GET'])
@login_required
def api_check_lock():
    clean_stale_locks()
    entity_type = request.args.get('type', 'customer')
    entity_id = request.args.get('id')
    if not entity_id:
        return jsonify({'locked': False})
    lock = EntityLock.query.filter_by(
        entity_type=entity_type, entity_id=int(entity_id)
    ).first()
    if not lock:
        return jsonify({'locked': False})
    if lock.user_id == session['user_id']:
        return jsonify({'locked': True, 'owner': 'self'})
    lock_user = User.query.get(lock.user_id)
    return jsonify({
        'locked': True,
        'held_by': lock_user.full_name or lock_user.username,
        'held_at': lock.locked_at.strftime('%H:%M')
    })


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
