import os
import uuid
import json
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session, g
from werkzeug.utils import secure_filename
from models import (db, Customer, Invoice, InvoiceItem, Payment, Return, ReturnItem,
                    Supplier, Purchase, PurchaseItem, SupplierPayment,
                    SupplierReturn, SupplierReturnItem,
                    InstallmentPlan, Installment, InstallmentPayment,
                    SupplierInstallmentPlan, SupplierInstallment, SupplierInstallmentPayment,
                    ShippingCompany, User, UserPermission, EntityLock)
from datetime import datetime, date, timedelta
from dateutil.relativedelta import relativedelta
from sqlalchemy import desc, func
from sqlalchemy.orm import joinedload

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
    return {'PAYMENT_METHODS': PAYMENT_METHODS, 'parse_images': parse_images}


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
        user = db.session.get(User, session['user_id'])
        g.current_user = user
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
    # يعاد استخدام المستخدم المخزن في g لتجنب استعلام مكرر في نفس الطلب
    if not hasattr(g, 'current_user'):
        g.current_user = db.session.get(User, session['user_id']) if 'user_id' in session else None
    return dict(current_user=g.current_user)

ACCOUNT_TYPES = {
    'sales': 'حسابات البيع',
    'shipping': 'حسابات الشحن',
    'travel': 'حسابات السفر',
    'bab_al_sharriah': 'حسابات باب الشعريه'
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

PAGES = {
    'dashboard': {'name': 'لوحة التحكم', 'icon': 'fa-chart-pie', 'group': 'الرئيسية'},
    'analytics': {'name': 'تحليل البيانات', 'icon': 'fa-chart-line', 'group': 'الرئيسية'},
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
    'items_list': {'name': 'الاصناف المتوفرة', 'icon': 'fa-boxes', 'group': 'المشتريات'},
    'shipping': {'name': 'شركات الشحن', 'icon': 'fa-shipping-fast', 'group': 'الشحن'},
    'employees': {'name': 'ادارة الموظفين', 'icon': 'fa-user-tie', 'group': 'الادارة'},
}

PAGE_MAP = {
    'dashboard': 'dashboard',
    'analytics': 'analytics',
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
    'customer_return_view': 'customers',
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
    'supplier_payment_edit': 'suppliers',
    'supplier_payment_delete': 'suppliers',
    'supplier_return_add': 'suppliers',
    'supplier_return_edit': 'suppliers',
    'supplier_return_delete': 'suppliers',
    'supplier_return_view': 'suppliers',
    'supplier_statement': 'suppliers',
    'suppliers_statement_all': 'suppliers',
    'purchases_list': 'purchases',
    'purchase_add': 'purchase_add',
    'purchase_view': 'purchases',
    'purchase_edit': 'purchases',
    'purchase_delete': 'purchases',
    'purchase_image_delete': 'purchases',
    'items_list': 'items_list',
    'items_edit': 'items_list',
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
        if 'created_by' not in invoice_cols:
            db.session.execute(db.text("ALTER TABLE invoices ADD COLUMN created_by INTEGER"))
        if 'modified_by' not in invoice_cols:
            db.session.execute(db.text("ALTER TABLE invoices ADD COLUMN modified_by INTEGER"))
        if 'previous_due' not in invoice_cols:
            db.session.execute(db.text("ALTER TABLE invoices ADD COLUMN previous_due FLOAT DEFAULT 0"))
        if 'balance_after' not in invoice_cols:
            db.session.execute(db.text("ALTER TABLE invoices ADD COLUMN balance_after FLOAT DEFAULT 0"))

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
        if 'created_by' not in purchase_cols:
            db.session.execute(db.text("ALTER TABLE purchases ADD COLUMN created_by INTEGER"))
        if 'previous_due' not in purchase_cols:
            db.session.execute(db.text("ALTER TABLE purchases ADD COLUMN previous_due FLOAT DEFAULT 0"))
        if 'balance_after' not in purchase_cols:
            db.session.execute(db.text("ALTER TABLE purchases ADD COLUMN balance_after FLOAT DEFAULT 0"))

        purchase_item_cols = {c['name'] for c in inspector.get_columns('purchase_items')}
        if 'unit_type' not in purchase_item_cols:
            db.session.execute(db.text("ALTER TABLE purchase_items ADD COLUMN unit_type VARCHAR(10) DEFAULT 'ق'"))

        if 'discount' not in purchase_cols:
            db.session.execute(db.text("ALTER TABLE purchases ADD COLUMN discount FLOAT DEFAULT 0"))
        if 'show_balance' not in purchase_cols:
            db.session.execute(db.text("ALTER TABLE purchases ADD COLUMN show_balance BOOLEAN DEFAULT 0"))
        if 'modified_by' not in purchase_cols:
            db.session.execute(db.text("ALTER TABLE purchases ADD COLUMN modified_by INTEGER"))

        return_item_cols = {c['name'] for c in inspector.get_columns('return_items')}
        if 'unit_type' not in return_item_cols:
            db.session.execute(db.text("ALTER TABLE return_items ADD COLUMN unit_type VARCHAR(10) DEFAULT 'ق'"))

        ret_cols = {c['name'] for c in inspector.get_columns('returns')}
        if 'balance_before' not in ret_cols:
            db.session.execute(db.text("ALTER TABLE returns ADD COLUMN balance_before FLOAT DEFAULT 0"))
        if 'balance_after' not in ret_cols:
            db.session.execute(db.text("ALTER TABLE returns ADD COLUMN balance_after FLOAT DEFAULT 0"))
        if 'created_by' not in ret_cols:
            db.session.execute(db.text("ALTER TABLE returns ADD COLUMN created_by INTEGER"))
        if 'modified_by' not in ret_cols:
            db.session.execute(db.text("ALTER TABLE returns ADD COLUMN modified_by INTEGER"))

        db.session.execute(db.text(
            "CREATE TABLE IF NOT EXISTS supplier_returns ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " supplier_id INTEGER NOT NULL,"
            " purchase_id INTEGER,"
            " total_amount FLOAT DEFAULT 0,"
            " balance_before FLOAT DEFAULT 0,"
            " balance_after FLOAT DEFAULT 0,"
            " date DATETIME,"
            " reason TEXT)"
        ))
        db.session.execute(db.text(
            "CREATE TABLE IF NOT EXISTS supplier_return_items ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " return_id INTEGER NOT NULL,"
            " item_name VARCHAR(300) NOT NULL,"
            " unit_type VARCHAR(10) DEFAULT 'ق',"
            " quantity FLOAT NOT NULL DEFAULT 0,"
            " unit_price FLOAT NOT NULL DEFAULT 0,"
            " total FLOAT NOT NULL DEFAULT 0)"
        ))

        sp_cols = {c['name'] for c in inspector.get_columns('supplier_payments')}
        if 'purchase_id' not in sp_cols:
            db.session.execute(db.text("ALTER TABLE supplier_payments ADD COLUMN purchase_id INTEGER"))
        if 'payment_method' not in sp_cols:
            db.session.execute(db.text("ALTER TABLE supplier_payments ADD COLUMN payment_method VARCHAR(20) DEFAULT 'cash'"))
        if 'receipt_image' not in sp_cols:
            db.session.execute(db.text("ALTER TABLE supplier_payments ADD COLUMN receipt_image VARCHAR(200)"))
        if 'created_by' not in sp_cols:
            db.session.execute(db.text("ALTER TABLE supplier_payments ADD COLUMN created_by INTEGER"))

        pay_cols = {c['name'] for c in inspector.get_columns('payments')}
        if 'payment_method' not in pay_cols:
            db.session.execute(db.text("ALTER TABLE payments ADD COLUMN payment_method VARCHAR(20) DEFAULT 'cash'"))
        if 'receipt_image' not in pay_cols:
            db.session.execute(db.text("ALTER TABLE payments ADD COLUMN receipt_image VARCHAR(200)"))
        if 'created_by' not in pay_cols:
            db.session.execute(db.text("ALTER TABLE payments ADD COLUMN created_by INTEGER"))

        inst_pay_cols = {c['name'] for c in inspector.get_columns('installment_payments')}
        if 'payment_method' not in inst_pay_cols:
            db.session.execute(db.text("ALTER TABLE installment_payments ADD COLUMN payment_method VARCHAR(20) DEFAULT 'cash'"))
        if 'receipt_image' not in inst_pay_cols:
            db.session.execute(db.text("ALTER TABLE installment_payments ADD COLUMN receipt_image VARCHAR(200)"))
        if 'created_by' not in inst_pay_cols:
            db.session.execute(db.text("ALTER TABLE installment_payments ADD COLUMN created_by INTEGER"))

        supp_inst_pay_cols = {c['name'] for c in inspector.get_columns('supplier_installment_payments')}
        if 'payment_method' not in supp_inst_pay_cols:
            db.session.execute(db.text("ALTER TABLE supplier_installment_payments ADD COLUMN payment_method VARCHAR(20) DEFAULT 'cash'"))
        if 'receipt_image' not in supp_inst_pay_cols:
            db.session.execute(db.text("ALTER TABLE supplier_installment_payments ADD COLUMN receipt_image VARCHAR(200)"))
        if 'created_by' not in supp_inst_pay_cols:
            db.session.execute(db.text("ALTER TABLE supplier_installment_payments ADD COLUMN created_by INTEGER"))

        user_cols = {c['name'] for c in inspector.get_columns('users')}
        if 'is_admin' not in user_cols:
            db.session.execute(db.text("ALTER TABLE users ADD COLUMN is_admin BOOLEAN DEFAULT 0"))

        db.session.execute(db.text("UPDATE invoices SET paid_amount=0 WHERE paid_amount IS NULL"))
        db.session.execute(db.text("UPDATE invoices SET remaining=0 WHERE remaining IS NULL"))
        db.session.execute(db.text("UPDATE purchases SET paid_amount=0 WHERE paid_amount IS NULL"))
        db.session.execute(db.text("UPDATE purchases SET remaining=0 WHERE remaining IS NULL"))

        # فهارس لتسريع البحث والتجميع على الاعمدة الاكثر استخداما
        INDEXES = [
            "CREATE INDEX IF NOT EXISTS ix_purchase_items_name ON purchase_items (item_name)",
            "CREATE INDEX IF NOT EXISTS ix_invoice_items_name ON invoice_items (item_name)",
            "CREATE INDEX IF NOT EXISTS ix_return_items_name ON return_items (item_name)",
            "CREATE INDEX IF NOT EXISTS ix_invoices_customer ON invoices (customer_id)",
            "CREATE INDEX IF NOT EXISTS ix_invoices_date ON invoices (date)",
            "CREATE INDEX IF NOT EXISTS ix_payments_customer ON payments (customer_id)",
            "CREATE INDEX IF NOT EXISTS ix_returns_customer ON returns (customer_id)",
            "CREATE INDEX IF NOT EXISTS ix_purchases_supplier ON purchases (supplier_id)",
            "CREATE INDEX IF NOT EXISTS ix_purchases_date ON purchases (date)",
            "CREATE INDEX IF NOT EXISTS ix_supplier_payments_supplier ON supplier_payments (supplier_id)",
            "CREATE INDEX IF NOT EXISTS ix_supplier_returns_supplier ON supplier_returns (supplier_id)",
            "CREATE INDEX IF NOT EXISTS ix_installment_plans_customer ON installment_plans (customer_id)",
            "CREATE INDEX IF NOT EXISTS ix_supp_installment_plans_supplier ON supplier_installment_plans (supplier_id)",
        ]
        for stmt in INDEXES:
            db.session.execute(db.text(stmt))

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


def parse_images(value):
    """تفسير قيمة صور الايصال: JSON array (جديدة) او اسم ملف واحد (قديمة)."""
    if not value:
        return []
    s = str(value).strip()
    if s.startswith('['):
        try:
            parsed = json.loads(s)
            return [x for x in parsed if x] if isinstance(parsed, list) else []
        except Exception:
            return []
    return [s]


def save_receipt_images(files_list):
    """حفظ عدة صور وارجاع JSON array من اسماء الملفات المحفوظة."""
    names = []
    if files_list:
        for f in files_list:
            if f and f.filename:
                n = save_receipt_image(f)
                if n:
                    names.append(n)
    return json.dumps(names)


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


def _customer_balance_before(customer_id, before_date, exclude_id=None):
    """المستحق الفعلي على العميل قبل تاريخ معين (قبل اضافة فاتورة جديدة).

    يعيد نفس منهج حساب رصيد العميل في البروفايل (total_invoiced - total_paid
    - total_returns) مع قصر الحساب على الحركات التي حدثت قبل before_date فقط،
    حتى تكون قيمة 'آخر المستحقات' المسجلة في الفاتورة مساوية لرصيد البروفايل
    قبل اضافة اجمالي الفاتورة الحالية.
    """
    invs = Invoice.query.filter(
        Invoice.customer_id == customer_id,
        Invoice.id != exclude_id,
        Invoice.date < before_date
    ).all()
    total_invoiced = sum(
        (i.total or 0) - (i.discount or 0)
        for i in invs if not i.is_returned
    )
    paid_invoice_ids = {p.invoice_id for p in Payment.query.filter(
        Payment.customer_id == customer_id,
        Payment.invoice_id.isnot(None)
    ).all()}
    sum_inv_paid = sum(
        (i.paid_amount or 0)
        for i in invs
        if not i.is_returned and i.id not in paid_invoice_ids
    )
    sum_payments = sum(
        p.amount or 0
        for p in Payment.query.filter(
            Payment.customer_id == customer_id,
            Payment.date < before_date
        ).all()
    )
    plan_ids = [pl.id for pl in InstallmentPlan.query.filter(
        InstallmentPlan.customer_id == customer_id,
        InstallmentPlan.date < before_date
    ).all()]
    sum_inst = 0
    if plan_ids:
        sum_inst = sum(
            ip.amount or 0
            for ip in InstallmentPayment.query.filter(
                InstallmentPayment.plan_id.in_(plan_ids),
                InstallmentPayment.date < before_date
            ).all()
        )
    sum_returns = sum(
        r.total_amount or 0
        for r in Return.query.filter(
            Return.customer_id == customer_id,
            Return.date < before_date
        ).all()
    )
    balance = total_invoiced - sum_payments - sum_inst - sum_inv_paid - sum_returns
    return max(0, round(balance, 2))


def _supplier_balance_before(supplier_id, before_date, exclude_id=None):
    """المستحق الفعلي للمورد قبل تاريخ معين (قبل اضافة امر شراء جديد).

    يعيد نفس منهج حساب رصيد المورد في البروفايل (total_purchased - total_paid
    - total_returns) مع قصر الحساب على الحركات قبل before_date فقط.
    """
    purs = Purchase.query.filter(
        Purchase.supplier_id == supplier_id,
        Purchase.id != exclude_id,
        Purchase.date < before_date
    ).all()
    total_purchased = sum(
        p.total or 0
        for p in purs
    )
    paid_purchase_ids = {pp.purchase_id for pp in SupplierPayment.query.filter(
        SupplierPayment.supplier_id == supplier_id,
        SupplierPayment.purchase_id.isnot(None)
    ).all()}
    sum_pur_paid = sum(
        (p.paid_amount or 0)
        for p in purs
        if p.id not in paid_purchase_ids
    )
    sum_payments = sum(
        p.amount or 0
        for p in SupplierPayment.query.filter(
            SupplierPayment.supplier_id == supplier_id,
            SupplierPayment.date < before_date
        ).all()
    )
    plan_ids = [pl.id for pl in SupplierInstallmentPlan.query.filter(
        SupplierInstallmentPlan.supplier_id == supplier_id,
        SupplierInstallmentPlan.date < before_date
    ).all()]
    sum_inst = 0
    if plan_ids:
        sum_inst = sum(
            ip.amount or 0
            for ip in SupplierInstallmentPayment.query.filter(
                SupplierInstallmentPayment.plan_id.in_(plan_ids),
                SupplierInstallmentPayment.date < before_date
            ).all()
        )
    sum_returns = sum(
        r.total_amount or 0
        for r in SupplierReturn.query.filter(
            SupplierReturn.supplier_id == supplier_id,
            SupplierReturn.date < before_date
        ).all()
    )
    balance = total_purchased - sum_payments - sum_inst - sum_pur_paid - sum_returns
    return max(0, round(balance, 2))


def _next_invoice_date(customer_id, inv_date):
    """تاريخ انشاء الفاتورة التالية لنفس العميل (لا شيء اذا لم توجد)."""
    nxt = Invoice.query.filter(
        Invoice.customer_id == customer_id,
        Invoice.date > inv_date
    ).order_by(Invoice.date.asc(), Invoice.id.asc()).first()
    return nxt.date if nxt else None


def _invoice_window_payments(inv):
    """الدفعات التي تظهر داخل الفاتورة: كل دفعة تُعرض في آخر فاتورة
    تم انشاؤها قبل تسجيل الدفعة. أي من تاريخ انشاء الفاتورة الحالية حتى
    انشاء الفاتورة التالية لنفس العميل (بدونها).
    """
    end = _next_invoice_date(inv.customer_id, inv.date)
    q = Payment.query.filter(
        Payment.customer_id == inv.customer_id,
        Payment.date >= inv.date
    )
    if end is not None:
        q = q.filter(Payment.date < end)
    return q.order_by(Payment.date.asc(), Payment.id.asc()).all()


def _next_purchase_date(supplier_id, pur_date):
    """تاريخ انشاء امر الشراء التالي لنفس المورد (لا شيء اذا لم توجد)."""
    nxt = Purchase.query.filter(
        Purchase.supplier_id == supplier_id,
        Purchase.date > pur_date
    ).order_by(Purchase.date.asc(), Purchase.id.asc()).first()
    return nxt.date if nxt else None


def _purchase_window_payments(pur):
    """الدفعات التي تظهر داخل امر الشراء: كل دفعة تُعرض في آخر امر شراء
    تم انشاؤه قبل تسجيل الدفعة. أي من تاريخ انشاء الامر الحالي حتى انشاء
    امر الشراء التالي لنفس المورد (بدونها).
    """
    end = _next_purchase_date(pur.supplier_id, pur.date)
    q = SupplierPayment.query.filter(
        SupplierPayment.supplier_id == pur.supplier_id,
        SupplierPayment.date >= pur.date
    )
    if end is not None:
        q = q.filter(SupplierPayment.date < end)
    return q.order_by(SupplierPayment.date.asc(), SupplierPayment.id.asc()).all()


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


@app.route('/analytics')
@login_required
def analytics():
    period = request.args.get('period', 'week')

    # اختيار قالب التجميع الزمني + عدد الفترات المعروضة
    if period == 'day':
        fmt = '%Y-%m-%d'
        label_fmt = '%d/%m'
        buckets = 30
        period_label = 'آخر 30 يوم'
    elif period == 'week':
        fmt = '%Y-%W'
        label_fmt = None
        buckets = 16
        period_label = 'آخر 16 أسبوع'
    else:  # month
        fmt = '%Y-%m'
        label_fmt = '%m/%Y'
        buckets = 12
        period_label = 'آخر 12 شهر'

    # --- سلاسل زمنية (إيرادات / مشتريات / مدفوعات محصلة / مدفوعات موردين) ---
    rev_rows = db.session.query(
        func.strftime(fmt, Invoice.date).label('b'),
        func.coalesce(func.sum(Invoice.total), 0).label('v')
    ).filter(Invoice.is_returned == False).group_by('b').all()
    ret_rows = db.session.query(
        func.strftime(fmt, Return.date).label('b'),
        func.coalesce(func.sum(Return.total_amount), 0).label('v')
    ).group_by('b').all()
    pur_rows = db.session.query(
        func.strftime(fmt, Purchase.date).label('b'),
        func.coalesce(func.sum(Purchase.total), 0).label('v')
    ).group_by('b').all()
    pay_c_rows = db.session.query(
        func.strftime(fmt, Payment.date).label('b'),
        func.coalesce(func.sum(Payment.amount), 0).label('v')
    ).group_by('b').all()
    pay_s_rows = db.session.query(
        func.strftime(fmt, SupplierPayment.date).label('b'),
        func.coalesce(func.sum(SupplierPayment.amount), 0).label('v')
    ).group_by('b').all()

    def series_map(rows):
        return {r.b: (r.v or 0) for r in rows}

    rev_map = series_map(rev_rows)
    ret_map = series_map(ret_rows)
    pur_map = series_map(pur_rows)
    payc_map = series_map(pay_c_rows)
    pays_map = series_map(pay_s_rows)

    # بناء الفترات الزمنية المتتالية (لآخر N فترة متاحة من البيانات)
    from datetime import timedelta as _td
    now = datetime.utcnow()
    buckets_keys = []
    week_label_map = {}
    if period == 'day':
        for i in range(buckets - 1, -1, -1):
            d = (now - _td(days=i)).date()
            buckets_keys.append(d.strftime('%Y-%m-%d'))
    elif period == 'month':
        for i in range(buckets - 1, -1, -1):
            y = now.year
            m = now.month - i
            while m <= 0:
                m += 12
                y -= 1
            buckets_keys.append(f"{y}-{m:02d}")
    else:  # week (ISO year-week)
        seen = set()
        cur = now.date()
        for i in range(buckets - 1, -1, -1):
            d = cur - _td(weeks=i)
            kw = '%d-%02d' % (d.isocalendar()[0], d.isocalendar()[1])
            if kw in seen:
                continue
            seen.add(kw)
            wk_start = d - _td(days=d.weekday())
            wk_end = wk_start + _td(days=6)
            buckets_keys.append(kw)
            week_label_map[kw] = f"{wk_start.strftime('%d/%m')} - {wk_end.strftime('%d/%m')}"

    chart_rev = []
    chart_pur = []
    chart_net = []
    chart_labels = []
    for bk in buckets_keys:
        if period == 'week':
            chart_labels.append(week_label_map.get(bk, bk))
        else:
            chart_labels.append(bk)
        rev = rev_map.get(bk, 0)
        pur = pur_map.get(bk, 0)
        chart_rev.append(round(rev, 2))
        chart_pur.append(round(pur, 2))
        chart_net.append(round(rev - pur, 2))

    # --- إجماليات الفترة المحددة (آخر يوم / أسبوع / شهر مكتمل) ---
    # أجمالي الأرقام الكلية للمدة المختارة من البيانات كلها
    period_sum = lambda m: round(sum(m.get(bk, 0) for bk in buckets_keys), 2)
    totals = {
        'revenue': period_sum(rev_map),
        'purchases': period_sum(pur_map),
        'net': period_sum({k: (rev_map.get(k, 0) - pur_map.get(k, 0)) for k in buckets_keys}),
        'returns': period_sum(ret_map),
        'collected': period_sum(payc_map),
        'paid_suppliers': period_sum(pays_map),
    }
    totals['invoice_count'] = Invoice.query.filter_by(is_returned=False).count()
    totals['all_collected'] = round((db.session.query(func.coalesce(func.sum(Payment.amount), 0)).scalar() or 0), 2)
    totals['all_revenue'] = round((db.session.query(func.coalesce(func.sum(Invoice.total), 0)).filter_by(is_returned=False).scalar() or 0), 2)

    # --- أهم الأصناف مبيعاً (من فواتير الفترة الأخيرة) ---
    from sqlalchemy import func as _f
    # نأخذ كل الأصناف المبيعة مرتبة بالكمية
    top_items = db.session.query(
        InvoiceItem.item_name.label('name'),
        _f.coalesce(_f.sum(InvoiceItem.quantity), 0).label('qty'),
        _f.coalesce(_f.sum(InvoiceItem.total), 0).label('val')
    ).join(Invoice, Invoice.id == InvoiceItem.invoice_id)\
     .filter(Invoice.is_returned == False)\
     .group_by(InvoiceItem.item_name)\
     .order_by(_f.sum(InvoiceItem.total).desc())\
     .limit(10).all()

    # --- طرق الدفع المستخدمة (حسب الفترة) ---
    pm_rows = db.session.query(
        Invoice.payment_method,
        _f.count(Invoice.id),
        _f.coalesce(_f.sum(Invoice.total), 0)
    ).filter(Invoice.is_returned == False).group_by(Invoice.payment_method).all()
    payment_methods = []
    for row in pm_rows:
        payment_methods.append({
            'method': PAYMENT_METHODS.get(row[0], row[0] or 'كاش'),
            'count': row[1],
            'total': round(row[2] or 0, 2)
        })

    # --- العملاء الأكثر شراءً ---
    top_customers = db.session.query(
        Customer.name.label('name'),
        _f.coalesce(_f.sum(Invoice.total), 0).label('val'),
        _f.count(Invoice.id).label('cnt')
    ).join(Invoice, Invoice.customer_id == Customer.id)\
     .filter(Invoice.is_returned == False)\
     .group_by(Customer.id)\
     .order_by(_f.sum(Invoice.total).desc())\
     .limit(8).all()

    # --- أنماط الدفع (نقداً/آجل/تقسيط) ---
    type_rows = db.session.query(
        Invoice.payment_type,
        _f.coalesce(_f.sum(Invoice.total), 0)
    ).filter(Invoice.is_returned == False).group_by(Invoice.payment_type).all()
    payment_types = [{'type': PAYMENT_TYPES.get(r[0], r[0]), 'total': round(r[1] or 0, 2)} for r in type_rows]

    # --- عملاء جدد ---
    new_customers_count = Customer.query.count()

    # --- متوسط قيمة الفاتورة ---
    avg_invoice = round(totals['all_revenue'] / totals['invoice_count'], 2) if totals['invoice_count'] else 0

    return render_template('analytics.html',
        period=period, period_label=period_label,
        chart_labels=chart_labels, chart_rev=chart_rev, chart_pur=chart_pur, chart_net=chart_net,
        totals=totals, top_items=top_items, payment_methods=payment_methods,
        top_customers=top_customers, payment_types=payment_types,
        new_customers_count=new_customers_count, avg_invoice=avg_invoice,
        PAYMENT_TYPES=PAYMENT_TYPES, APP_NAME='El Dahab')


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
    balance_filter = request.args.get('balance', '')
    sort = request.args.get('sort', 'name')
    query = Customer.query
    if account_type:
        query = query.filter_by(account_type=account_type)
    else:
        # استبعاد حسابات الموردين من قائمة العملاء (التوريد له صفحات منفصلة)
        query = query.filter(Customer.account_type != 'supplier')
    if search:
        query = query.filter(Customer.name.contains(search) | Customer.phone.contains(search))
    customers = query.all()
    # فلاتر الرصيد الفعلية: البيانات محسوبة ديناميكياً من DB وليست مجرد واجهة
    if balance_filter == 'has':
        customers = [c for c in customers if c.balance() > 0]
    elif balance_filter == 'none':
        customers = [c for c in customers if c.balance() <= 0]
    if sort == 'balance_desc':
        customers.sort(key=lambda x: x.balance(), reverse=True)
    elif sort == 'balance_asc':
        customers.sort(key=lambda x: x.balance())
    elif sort == 'type':
        customers.sort(key=lambda x: (x.account_type or '', x.name or ''))
    else:
        customers.sort(key=lambda x: x.name or '')
    return render_template('customers_list.html', customers=customers,
        ACCOUNT_TYPES=ACCOUNT_TYPES, selected_type=account_type, search=search,
        balance_filter=balance_filter, sort=sort)


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
        # الدفع الفوري يُحتسب فقط إذا لم تُسجل له دفعات منفصلة (تجنب الازدواج)
        upfront = max(0, (inv.paid_amount or 0))
        if upfront > 0 and not inv.payments:
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

        # التحقق: لا يُسمح بصنف له كمية بدون سعر
        no_price_items = []
        indices_ = sorted({int(k.rsplit('_', 1)[1]) for k in request.form if k.startswith('item_name_')})
        for i in indices_:
            iname = request.form.get(f'item_name_{i}', '').strip()
            if not iname:
                continue
            qty = float(request.form.get(f'item_qty_{i}', 0) or 0)
            price = float(request.form.get(f'item_price_{i}', 0) or 0)
            if qty > 0 and price <= 0:
                no_price_items.append(iname)
        if no_price_items:
            flash('لا يمكن حفظ الفاتورة: يوجد منتج بدون سعر (' + '، '.join(no_price_items) + ')', 'danger')
            return render_template('invoice_form.html',
                customers=customers, invoice=None, no_price=no_price_items,
                PAYMENT_TYPES=PAYMENT_TYPES)

        inv = Invoice(
            invoice_number=generate_invoice_number(),
            customer_id=int(request.form['customer_id']),
            shipping_company=request.form.get('shipping_company', ''),
            payment_type=payment_type,
            show_balance=bool(request.form.get('show_balance')),
            payment_method=request.form.get('payment_method', 'cash') if payment_type in ('cash', 'installment') else 'cash',
            receipt_image=save_receipt_images(request.files.getlist('receipt_images')),
            created_by=session.get('user_id'),
            notes=request.form.get('notes', '')
        )
        db.session.add(inv)
        db.session.flush()
        total = 0
        indices = sorted({int(k.rsplit('_', 1)[1]) for k in request.form if k.startswith('item_name_')})
        for i in indices:
            iname = request.form.get(f'item_name_{i}', '').strip()
            if not iname:
                continue
            try:
                qty = float(request.form.get(f'item_qty_{i}', 0) or 0)
            except (TypeError, ValueError):
                qty = 0
            try:
                price = float(request.form.get(f'item_price_{i}', 0) or 0)
            except (TypeError, ValueError):
                price = 0
            if qty <= 0:
                continue
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
        inv.total = total
        try:
            discount = float(request.form.get('discount', 0) or 0)
        except (TypeError, ValueError):
            discount = 0
        inv.discount = discount
        net = max(0, total - discount)

        # حساب اللقطة التراكمية الثابتة:
        # previous_due = المستحق الفعلي على العميل قبل اضافة اجمالي الفاتورة الحالية
        # balance_after = previous_due + قيمة الفاتورة - دفعات فورية (كاش/مقدم)
        prev_due = _customer_balance_before(inv.customer_id, inv.date, exclude_id=inv.id)
        inv.previous_due = prev_due

        if payment_type == 'cash':
            inv.paid_amount = net
            inv.remaining = 0
            inv.balance_after = max(0, prev_due + net - net)
        elif payment_type == 'credit':
            # الآجل: يمكن للعميل دفع مقدم نقدي (down_payment) والباقي آجل
            down = min(float(request.form.get('down_payment', 0) or 0), net)
            inv.paid_amount = down
            inv.remaining = max(0, net - down)
            inv.balance_after = max(0, prev_due + net - down)
        elif payment_type == 'installment':
            down = min(float(request.form.get('down_payment', 0) or 0), net)
            inv.paid_amount = down
            inv.remaining = max(0, net - down)
            inv.balance_after = max(0, prev_due + net - down)

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
        inv.modified_by = session.get('user_id')
        inv.customer_id = int(request.form['customer_id'])
        inv.shipping_company = request.form.get('shipping_company', '')
        inv.show_balance = bool(request.form.get('show_balance'))

        # التحقق: لا يُسمح بصنف له كمية بدون سعر
        no_price_items = []
        indices_ = sorted({int(k.rsplit('_', 1)[1]) for k in request.form if k.startswith('item_name_')})
        for i in indices_:
            iname = request.form.get(f'item_name_{i}', '').strip()
            if not iname:
                continue
            try:
                qty = float(request.form.get(f'item_qty_{i}', 0) or 0)
            except (TypeError, ValueError):
                qty = 0
            try:
                price = float(request.form.get(f'item_price_{i}', 0) or 0)
            except (TypeError, ValueError):
                price = 0
            if qty > 0 and price <= 0:
                no_price_items.append(iname)
        if no_price_items:
            flash('لا يمكن حفظ الفاتورة: يوجد منتج بدون سعر (' + '، '.join(no_price_items) + ')', 'danger')
            return render_template('invoice_form.html',
                customers=customers, invoice=inv, no_price=no_price_items,
                PAYMENT_TYPES=PAYMENT_TYPES)

        old_ptype = inv.payment_type
        inv.payment_type = request.form.get('payment_type', old_ptype or 'cash')
        new_ptype = inv.payment_type
        if new_ptype in ('cash', 'installment'):
            inv.payment_method = request.form.get('payment_method', 'cash')
        else:
            inv.payment_method = 'cash'

        new_images = save_receipt_images(request.files.getlist('receipt_images'))
        if new_images != '[]':
            existing = parse_images(inv.receipt_image)
            inv.receipt_image = json.dumps(existing + parse_images(new_images))
        inv.notes = request.form.get('notes', '')

        InvoiceItem.query.filter_by(invoice_id=inv.id).delete()

        total = 0
        indices = sorted({int(k.rsplit('_', 1)[1]) for k in request.form if k.startswith('item_name_')})
        for i in indices:
            iname = request.form.get(f'item_name_{i}', '').strip()
            if not iname:
                continue
            try:
                qty = float(request.form.get(f'item_qty_{i}', 0) or 0)
            except (TypeError, ValueError):
                qty = 0
            try:
                price = float(request.form.get(f'item_price_{i}', 0) or 0)
            except (TypeError, ValueError):
                price = 0
            if qty <= 0:
                continue
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
        inv.total = total
        try:
            discount = float(request.form.get('discount', 0) or 0)
        except (TypeError, ValueError):
            discount = 0
        inv.discount = discount
        net = max(0, total - discount)

        down_val = 0
        if new_ptype in ('credit', 'installment'):
            try:
                down_val = float(request.form.get('down_payment', 0) or 0)
            except (TypeError, ValueError):
                down_val = 0

        if new_ptype == 'cash':
            inv.paid_amount = net
            inv.remaining = 0
        elif new_ptype == 'credit':
            want_down = min(down_val, net)
            inv.paid_amount = want_down
            inv.remaining = max(0, net - want_down)
        elif new_ptype == 'installment':
            want_down = min(down_val, net)
            inv.paid_amount = want_down
            inv.remaining = max(0, net - want_down)

        # اعادة حساب اللقطة التراكمية الثابتة عند التعديل
        # حفظ previous_due الحالي (الثابت) وبناء balance_after عليه
        cur_prev = inv.previous_due if inv.previous_due is not None else 0
        if cur_prev == 0:
            prev_inv_edit = Invoice.query.filter(
                Invoice.customer_id == inv.customer_id,
                Invoice.id != inv.id
            ).order_by(Invoice.id.desc()).first()
            cur_prev = (prev_inv_edit.balance_after if prev_inv_edit and prev_inv_edit.balance_after else 0) or 0
        inv.previous_due = max(0, cur_prev)
        # مستحقات الفاتورة قيمة ثابتة = المستحق السابق + قيمة الفاتورة - مقدم الدفع
        inv.balance_after = max(0, round((inv.previous_due or 0) + net - (inv.paid_amount or 0), 2))

        if new_ptype == 'installment':
            plan = InstallmentPlan.query.filter_by(invoice_id=inv.id).first()
            if plan:
                down = min(float(request.form.get('down_payment', 0) or 0), net)
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
            else:
                down = min(float(request.form.get('down_payment', 0) or 0), net)
                count = int(request.form.get('installment_count', 1) or 1)
                start_str = request.form.get('installment_start_date', '')
                start_date = datetime.strptime(start_str, '%Y-%m-%d').date() if start_str else date.today()
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
        else:
            # التحويل من تقسيط إلى نقدي/آجل: حذف خطة التقسيط ان وجدت
            # (حتى لا تبقى خطة مكررة تضاعف الحساب او تُنشئ حركة خاطئة)
            plan = InstallmentPlan.query.filter_by(invoice_id=inv.id).first()
            if plan:
                InstallmentPayment.query.filter_by(plan_id=plan.id).delete()
                Installment.query.filter_by(plan_id=plan.id).delete()
                db.session.delete(plan)

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
    installment_plan = InstallmentPlan.query.filter_by(invoice_id=inv.id).first()
    installments = installment_plan.installments if installment_plan else []
    installment_payments = installment_plan.payments if installment_plan else []
    cust = inv.customer
    # الدفعات التي تظهر داخل هذه الفاتورة فقط: كل دفعة تظهر في آخر فاتورة
    # تم انشاؤها قبل تسجيلها (من تاريخ هذه الفاتورة حتى انشاء الفاتورة التالية)
    customer_payments = _invoice_window_payments(inv)
    cust_total_paid = sum(p.amount or 0 for p in customer_payments)
    cust_balance = cust.balance()
    # للمستحقات المعروضة في الفاتورة نستخدم اللقطة الثابتة المحفوظة وقت الانشاء
    # وليس الحساب العام الحالي — حتى لا تتغير الفواتير القديمة
    prev_saved = inv.previous_due if inv.previous_due is not None else 0
    after_saved = inv.balance_after if inv.balance_after is not None else 0
    return render_template('invoice_view.html', invoice=inv,
        installment_plan=installment_plan, installments=installments,
        installment_payments=installment_payments, PAYMENT_TYPES=PAYMENT_TYPES,
        previous_dues=max(0, prev_saved), balance_after=max(0, after_saved),
        customer_payments=customer_payments,
        cust_total_paid=round(cust_total_paid, 2),
        cust_balance=round(cust_balance, 2))


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


@app.route('/invoices/<int:invoice_id>/image/<int:idx>/delete', methods=['POST'])
@login_required
def invoice_image_delete(invoice_id, idx):
    inv = Invoice.query.get_or_404(invoice_id)
    images = parse_images(inv.receipt_image)
    if 0 <= idx < len(images):
        delete_receipt_image(images[idx])
        images.pop(idx)
    inv.receipt_image = json.dumps(images) if images else ''
    db.session.commit()
    flash('تم حذف الصورة بنجاح', 'success')
    # الرجوع لنفس الصفحة المصدر (عرض الفاتورة او نموذج التعديل)
    dest = request.args.get('dest', 'view')
    if dest == 'edit':
        return redirect(url_for('invoice_edit', invoice_id=invoice_id))
    return redirect(url_for('invoice_view', invoice_id=invoice_id))


@app.route('/customers/<int:customer_id>/pay', methods=['GET', 'POST'])
@login_required
def payment_add(customer_id):
    c = Customer.query.get_or_404(customer_id)
    if request.method == 'POST':
        amount_str = request.form.get('amount', '')
        try:
            amount = float(amount_str)
            assert amount > 0
        except (ValueError, AssertionError):
            flash('يجب ادخال مبلغ صحيح', 'danger')
            return redirect(url_for('payment_add', customer_id=c.id))
        # الدفعة حركة مالية على حساب العميل التراكمي بالكامل.
        # لا تُربط بفاتورة محددة ولا تُعدّل مستحقات أي فاتورة تاريخية.
        p = Payment(
            customer_id=c.id,
            amount=amount,
            invoice_id=None,
            notes=request.form.get('notes', ''),
            payment_method=request.form.get('payment_method', 'cash'),
            receipt_image=save_receipt_images(request.files.getlist('receipt_images')),
            created_by=session.get('user_id'),
            next_payment_date=datetime.strptime(request.form['next_payment_date'], '%Y-%m-%d').date() if request.form.get('next_payment_date') else None,
            next_payment_amount=float(request.form['next_payment_amount']) if request.form.get('next_payment_amount') else None
        )
        db.session.add(p)
        db.session.commit()
        flash('تم تسجيل الدفعة بنجاح', 'success')
        return redirect(url_for('customer_profile', customer_id=c.id))
    return render_template('payment_form.html', customer=c, payment=None)


@app.route('/payments/<int:payment_id>/edit', methods=['GET', 'POST'])
@login_required
def payment_edit(payment_id):
    p = Payment.query.get_or_404(payment_id)
    c = p.customer

    if request.method == 'POST':
        try:
            new_amount = float(request.form.get('amount', ''))
            assert new_amount > 0
        except (ValueError, AssertionError):
            flash('يجب ادخال مبلغ صحيح', 'danger')
            return redirect(url_for('payment_edit', payment_id=p.id))

        # الدفعة حركة على حساب العميل التراكمي؛ تعديل المبلغ لا يمس أي فاتورة تاريخية.
        # لا نغير ربط invoice_id للدفعات القديمة (حارس من الازدواج في total_paid)؛
        # الدفعات الجديدة تُنشأ دائماً بدون ربط invoice_id.
        p.amount = new_amount
        p.notes = request.form.get('notes', '')
        p.payment_method = request.form.get('payment_method', 'cash')
        new_receipt = save_receipt_image(request.files.get('receipt_image'))
        if new_receipt:
            delete_receipt_image(p.receipt_image)
            p.receipt_image = new_receipt
        p.next_payment_date = datetime.strptime(request.form['next_payment_date'], '%Y-%m-%d').date() if request.form.get('next_payment_date') else None
        p.next_payment_amount = float(request.form['next_payment_amount']) if request.form.get('next_payment_amount') else None

        db.session.commit()
        flash('تم تعديل الدفعة بنجاح', 'success')
        return redirect(url_for('customer_profile', customer_id=c.id))

    return render_template('payment_form.html', customer=c, payment=p)


@app.route('/payments/<int:payment_id>/delete', methods=['POST'])
@login_required
def payment_delete(payment_id):
    p = Payment.query.get_or_404(payment_id)
    cid = p.customer_id

    # حذف صور الإيصالات المرتبطة بالدفعة
    for fname in parse_images(p.receipt_image):
        delete_receipt_image(fname)

    db.session.delete(p)
    db.session.commit()
    flash('تم حذف الدفعة بنجاح', 'success')
    # اذا تم الحذف من صفحة الفاتورة ارجع اليها، والا ارجع لصفحة العميل
    next_inv = request.args.get('next_invoice')
    if next_inv and next_inv.isdigit():
        return redirect(url_for('invoice_view', invoice_id=int(next_inv)))
    return redirect(url_for('customer_profile', customer_id=cid))


@app.route('/customers/<int:customer_id>/return', methods=['GET', 'POST'])
@login_required
def return_add(customer_id):
    c = Customer.query.get_or_404(customer_id)
    invoices = Invoice.query.filter_by(customer_id=c.id, is_returned=False).all()
    if request.method == 'POST':
        r = Return(
            customer_id=c.id,
            invoice_id=int(request.form['invoice_id']) if request.form.get('invoice_id') else None,
            reason=request.form.get('reason', ''),
            created_by=session.get('user_id')
        )
        db.session.add(r)
        db.session.flush()
        total = 0
        indices = sorted({int(k.rsplit('_', 1)[1]) for k in request.form if k.startswith('item_name_')})
        for i in indices:
            iname = request.form.get(f'item_name_{i}', '').strip()
            if not iname:
                continue
            try:
                qty = float(request.form.get(f'item_qty_{i}', 0) or 0)
            except (TypeError, ValueError):
                qty = 0
            try:
                price = float(request.form.get(f'item_price_{i}', 0) or 0)
            except (TypeError, ValueError):
                price = 0
            if qty <= 0:
                continue
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
        r.total_amount = total
        # لقطة الرصيد قبل/بعد المرتجع: الرصيد قبل = الرصيد الحالي + قيمة المرتجع
        bal_now = c.balance()
        r.balance_before = bal_now + total
        r.balance_after = bal_now
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
        r.modified_by = session.get('user_id')
        ReturnItem.query.filter_by(return_id=r.id).delete()
        db.session.flush()
        total = 0
        indices = sorted({int(k.rsplit('_', 1)[1]) for k in request.form if k.startswith('item_name_')})
        for i in indices:
            iname = request.form.get(f'item_name_{i}', '').strip()
            if not iname:
                continue
            try:
                qty = float(request.form.get(f'item_qty_{i}', 0) or 0)
            except (TypeError, ValueError):
                qty = 0
            try:
                price = float(request.form.get(f'item_price_{i}', 0) or 0)
            except (TypeError, ValueError):
                price = 0
            if qty <= 0:
                continue
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
        r.total_amount = total
        # لقطة الرصيد قبل/بعد المرتجع
        r.balance_before = c.balance() + total
        r.balance_after = c.balance()
        db.session.commit()
        flash('تم تعديل المرتجع بنجاح', 'success')
        return redirect(url_for('customer_profile', customer_id=c.id))
    return render_template('return_form.html', customer=c, invoices=invoices, ret=r)


@app.route('/customers/<int:customer_id>/return/<int:return_id>/view')
@login_required
def customer_return_view(customer_id, return_id):
    c = Customer.query.get_or_404(customer_id)
    r = Return.query.filter_by(id=return_id, customer_id=c.id).first_or_404()
    before = r.balance_before
    after = r.balance_after
    # fallback للفواتير القديمة التي لا تحمل لقطة رصيد
    if not before and not after:
        cust_balance = c.balance()
        before = cust_balance + (r.total_amount or 0)
        after = cust_balance
    # نفس منطق عرض دفعات فاتورة البيع: كل دفعة تُعرض في آخر مستند
    # تم انشاؤه قبل تسجيلها — من تاريخ هذا المرتجع حتى انشاء الفاتورة
    # التالية لنفس العميل (عرض تنظيمي فقط، ولا يُغيّر أي رصيد).
    customer_payments = _invoice_window_payments(r)
    cust_total_paid = sum(p.amount or 0 for p in customer_payments)
    cust_balance = c.balance()
    return render_template('return_view.html', customer=c, ret=r,
                           balance_before=max(0, before or 0),
                           balance_after=max(0, after or 0),
                           customer_payments=customer_payments,
                           cust_total_paid=round(cust_total_paid, 2),
                           cust_balance=round(cust_balance, 2),
                           ACCOUNT_TYPES=ACCOUNT_TYPES)


@app.route('/suppliers/<int:supplier_id>/return', methods=['GET', 'POST'])
@login_required
def supplier_return_add(supplier_id):
    s = Supplier.query.get_or_404(supplier_id)
    purchases = Purchase.query.filter_by(supplier_id=s.id).all()
    if request.method == 'POST':
        r = SupplierReturn(
            supplier_id=s.id,
            purchase_id=int(request.form['purchase_id']) if request.form.get('purchase_id') else None,
            reason=request.form.get('reason', '')
        )
        db.session.add(r)
        db.session.flush()
        total = 0
        indices = sorted({int(k.rsplit('_', 1)[1]) for k in request.form if k.startswith('item_name_')})
        for i in indices:
            iname = request.form.get(f'item_name_{i}', '').strip()
            if not iname:
                continue
            try:
                qty = float(request.form.get(f'item_qty_{i}', 0) or 0)
            except (TypeError, ValueError):
                qty = 0
            try:
                price = float(request.form.get(f'item_price_{i}', 0) or 0)
            except (TypeError, ValueError):
                price = 0
            if qty <= 0:
                continue
            unit_type = request.form.get(f'item_unit_{i}', 'ق')
            item_total = qty * price
            ri = SupplierReturnItem(
                return_id=r.id,
                item_name=iname,
                unit_type=unit_type,
                quantity=qty,
                unit_price=price,
                total=item_total
            )
            db.session.add(ri)
            total += item_total
        r.total_amount = total
        bal_now = s.balance()
        r.balance_before = bal_now + total
        r.balance_after = bal_now
        db.session.commit()
        flash('تم تسجيل مرتجع المورد بنجاح', 'success')
        return redirect(url_for('supplier_profile', supplier_id=s.id))
    return render_template('supplier_return_form.html', supplier=s, purchases=purchases)


@app.route('/suppliers/<int:supplier_id>/return/<int:return_id>/edit', methods=['GET', 'POST'])
@login_required
def supplier_return_edit(supplier_id, return_id):
    s = Supplier.query.get_or_404(supplier_id)
    r = SupplierReturn.query.filter_by(id=return_id, supplier_id=s.id).first_or_404()
    purchases = Purchase.query.filter_by(supplier_id=s.id).all()
    if request.method == 'POST':
        r.purchase_id = int(request.form['purchase_id']) if request.form.get('purchase_id') else None
        r.reason = request.form.get('reason', '')
        SupplierReturnItem.query.filter_by(return_id=r.id).delete()
        db.session.flush()
        total = 0
        indices = sorted({int(k.rsplit('_', 1)[1]) for k in request.form if k.startswith('item_name_')})
        for i in indices:
            iname = request.form.get(f'item_name_{i}', '').strip()
            if not iname:
                continue
            try:
                qty = float(request.form.get(f'item_qty_{i}', 0) or 0)
            except (TypeError, ValueError):
                qty = 0
            try:
                price = float(request.form.get(f'item_price_{i}', 0) or 0)
            except (TypeError, ValueError):
                price = 0
            if qty <= 0:
                continue
            unit_type = request.form.get(f'item_unit_{i}', 'ق')
            item_total = qty * price
            ri = SupplierReturnItem(
                return_id=r.id,
                item_name=iname,
                unit_type=unit_type,
                quantity=qty,
                unit_price=price,
                total=item_total
            )
            db.session.add(ri)
            total += item_total
        r.total_amount = total
        r.balance_before = s.balance() + total
        r.balance_after = s.balance()
        db.session.commit()
        flash('تم تعديل مرتجع المورد بنجاح', 'success')
        return redirect(url_for('supplier_profile', supplier_id=s.id))
    return render_template('supplier_return_form.html', supplier=s, purchases=purchases, ret=r)


@app.route('/suppliers/<int:supplier_id>/return/<int:return_id>/delete', methods=['POST'])
@login_required
def supplier_return_delete(supplier_id, return_id):
    s = Supplier.query.get_or_404(supplier_id)
    r = SupplierReturn.query.filter_by(id=return_id, supplier_id=s.id).first_or_404()
    db.session.delete(r)
    db.session.commit()
    flash('تم حذف مرتجع المورد بنجاح', 'success')
    return redirect(url_for('supplier_profile', supplier_id=s.id))


@app.route('/suppliers/<int:supplier_id>/return/<int:return_id>/view')
@login_required
def supplier_return_view(supplier_id, return_id):
    s = Supplier.query.get_or_404(supplier_id)
    r = SupplierReturn.query.filter_by(id=return_id, supplier_id=s.id).first_or_404()
    before = r.balance_before
    after = r.balance_after
    if not before and not after:
        sup_balance = s.balance()
        before = sup_balance + (r.total_amount or 0)
        after = sup_balance
    return render_template('supplier_return_view.html', supplier=s, ret=r,
                           balance_before=max(0, before or 0),
                           balance_after=max(0, after or 0))


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
        try:
            amount = float(request.form.get('amount', ''))
            assert amount > 0
        except (ValueError, AssertionError):
            flash('يجب ادخال مبلغ صحيح', 'danger')
            return redirect(url_for('installment_pay', plan_id=plan.id))
        installment_id = int(request.form['installment_id']) if request.form.get('installment_id') else None
        notes = request.form.get('notes', '')

        pmt = InstallmentPayment(
            plan_id=plan.id,
            installment_id=installment_id,
            amount=amount,
            notes=notes,
            payment_method=request.form.get('payment_method', 'cash'),
            receipt_image=save_receipt_image(request.files.get('receipt_image')),
            created_by=session.get('user_id')
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
        try:
            amount = float(request.form.get('amount', ''))
            assert amount > 0
        except (ValueError, AssertionError):
            flash('يجب ادخال مبلغ صحيح', 'danger')
            return redirect(url_for('supplier_installment_pay', plan_id=plan.id))
        installment_id = int(request.form['installment_id']) if request.form.get('installment_id') else None
        notes = request.form.get('notes', '')

        pmt = SupplierInstallmentPayment(
            plan_id=plan.id,
            installment_id=installment_id,
            amount=amount,
            notes=notes,
            payment_method=request.form.get('payment_method', 'cash'),
            receipt_image=save_receipt_image(request.files.get('receipt_image')),
            created_by=session.get('user_id')
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
                # لا نضيف لـ paid_amount (الدفعة الفورية)؛ أقساط المورد مسجلة في SupplierInstallmentPayment
                total_paid_pur = (pur.paid_amount or 0) + db.session.query(
                    db.func.coalesce(db.func.sum(SupplierInstallmentPayment.amount), 0)
                ).filter(SupplierInstallmentPayment.plan_id == plan.id).scalar()
                pur.remaining = max(0, (pur.total or 0) - total_paid_pur)

        db.session.commit()
        flash('تم تسجيل الدفعة بنجاح', 'success')
        return redirect(url_for('supplier_installment_view', plan_id=plan.id))
    return render_template('supplier_installment_pay_form.html', plan=plan,
        pending_installments=pending_installments)


@app.route('/suppliers')
@login_required
def suppliers_list():
    search = request.args.get('search', '')
    balance_filter = request.args.get('balance', '')
    sort = request.args.get('sort', 'name')
    query = Supplier.query
    if search:
        query = query.filter(Supplier.name.contains(search) | Supplier.phone.contains(search))
    suppliers = query.all()
    # فلاتر الرصيد الفعلية: محسوبة ديناميكياً وليس تجميلياً
    if balance_filter == 'has':
        suppliers = [s for s in suppliers if s.balance() > 0]
    elif balance_filter == 'none':
        suppliers = [s for s in suppliers if s.balance() <= 0]
    if sort == 'balance_desc':
        suppliers.sort(key=lambda x: x.balance(), reverse=True)
    elif sort == 'balance_asc':
        suppliers.sort(key=lambda x: x.balance())
    else:
        suppliers.sort(key=lambda x: x.name or '')
    return render_template('suppliers_list.html', suppliers=suppliers, search=search,
                           balance_filter=balance_filter, sort=sort)


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
    returns = SupplierReturn.query.filter_by(supplier_id=s.id).order_by(SupplierReturn.date.desc()).all()
    return render_template('supplier_profile.html', supplier=s,
        purchases=purchases, payments=payments, returns=returns,
        installment_plans=installment_plans, PAYMENT_TYPES=PAYMENT_TYPES)


def _supplier_statement_rows(s):
    entries = []

    for pur in s.purchases:
        entries.append({'date': pur.date, 'label': f'فاتورة مشتريات رقم {pur.purchase_number}',
                        'debit': pur.total or 0, 'credit': 0})
        upfront = max(0, (pur.paid_amount or 0))
        if upfront > 0 and not pur.payments:
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

    for r in s.returns:
        lbl = 'مرتجع مورد'
        if r.purchase_id and r.purchase:
            lbl += f' - {r.purchase.purchase_number}'
        if r.reason:
            lbl += f' ({r.reason})'
        entries.append({'date': r.date, 'label': lbl, 'debit': 0, 'credit': r.total_amount or 0})

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
    SupplierReturnItem.query.filter(SupplierReturnItem.return_id.in_(
        db.session.query(SupplierReturn.id).filter_by(supplier_id=s.id)
    )).delete(synchronize_session='fetch')
    SupplierReturn.query.filter_by(supplier_id=s.id).delete()
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
        try:
            amount = float(request.form.get('amount', ''))
            assert amount > 0
        except (ValueError, AssertionError):
            flash('يجب ادخال مبلغ صحيح', 'danger')
            return redirect(url_for('supplier_payment_add', supplier_id=s.id))
        purchase_id = None
        p = SupplierPayment(
            supplier_id=s.id,
            amount=amount,
            purchase_id=None,
            notes=request.form.get('notes', ''),
            payment_method=request.form.get('payment_method', 'cash'),
            receipt_image=save_receipt_image(request.files.get('receipt_image')),
            created_by=session.get('user_id')
        )
        db.session.add(p)
        db.session.commit()
        flash('تم تسجيل الدفعة بنجاح', 'success')
        return redirect(url_for('supplier_profile', supplier_id=s.id))
    return render_template('supplier_payment_form.html', supplier=s, unpaid_purchases=unpaid_purchases)


@app.route('/supplier-payments/<int:payment_id>/edit', methods=['GET', 'POST'])
@login_required
def supplier_payment_edit(payment_id):
    p = SupplierPayment.query.get_or_404(payment_id)
    s = p.supplier
    if request.method == 'POST':
        try:
            new_amount = float(request.form.get('amount', ''))
            assert new_amount > 0
        except (ValueError, AssertionError):
            flash('يجب ادخال مبلغ صحيح', 'danger')
            return redirect(url_for('supplier_payment_edit', payment_id=p.id))
        # الدفعة حركة على حساب المورد التراكمي؛ تعديل المبلغ لا يمس أي أمر شراء تاريخي.
        p.amount = new_amount
        p.notes = request.form.get('notes', '')
        p.payment_method = request.form.get('payment_method', 'cash')
        new_receipt = save_receipt_image(request.files.get('receipt_image'))
        if new_receipt:
            delete_receipt_image(p.receipt_image)
            p.receipt_image = new_receipt
        db.session.commit()
        flash('تم تعديل الدفعة بنجاح', 'success')
        return redirect(url_for('supplier_profile', supplier_id=s.id))
    return render_template('supplier_payment_form.html', supplier=s, payment=p,
                           unpaid_purchases=[])


@app.route('/supplier-payments/<int:payment_id>/delete', methods=['POST'])
@login_required
def supplier_payment_delete(payment_id):
    p = SupplierPayment.query.get_or_404(payment_id)
    s_id = p.supplier_id
    if p.receipt_image:
        delete_receipt_image(p.receipt_image)
    db.session.delete(p)
    db.session.commit()
    flash('تم حذف الدفعة بنجاح', 'success')
    return redirect(url_for('supplier_profile', supplier_id=s_id))


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
        # التحقق: لا يُسمح بصنف له كمية بدون سعر
        no_price_items = []
        indices_ = sorted({int(k.rsplit('_', 1)[1]) for k in request.form if k.startswith('item_name_')})
        for i in indices_:
            iname = request.form.get(f'item_name_{i}', '').strip()
            if not iname:
                continue
            try:
                qty = float(request.form.get(f'item_qty_{i}', 0) or 0)
            except (TypeError, ValueError):
                qty = 0
            try:
                price = float(request.form.get(f'item_price_{i}', 0) or 0)
            except (TypeError, ValueError):
                price = 0
            if qty > 0 and price <= 0:
                no_price_items.append(iname)
        if no_price_items:
            flash('لا يمكن حفظ امر الشراء: يوجد منتج بدون سعر (' + '، '.join(no_price_items) + ')', 'danger')
            return render_template('purchase_form.html', suppliers=suppliers,
                no_price=no_price_items, PAYMENT_TYPES=PAYMENT_TYPES)
        p = Purchase(
            purchase_number=generate_purchase_number(),
            supplier_id=int(request.form['supplier_id']),
            payment_type=payment_type,
            show_balance=bool(request.form.get('show_balance')),
            payment_method=request.form.get('payment_method', 'cash') if payment_type in ('cash', 'installment') else 'cash',
            receipt_image=save_receipt_images(request.files.getlist('receipt_images')),
            created_by=session.get('user_id'),
            notes=request.form.get('notes', '')
        )
        db.session.add(p)
        db.session.flush()
        total = 0
        indices = sorted({int(k.rsplit('_', 1)[1]) for k in request.form if k.startswith('item_name_')})
        for i in indices:
            iname = request.form.get(f'item_name_{i}', '').strip()
            if not iname:
                continue
            try:
                qty = float(request.form.get(f'item_qty_{i}', 0) or 0)
            except (TypeError, ValueError):
                qty = 0
            try:
                price = float(request.form.get(f'item_price_{i}', 0) or 0)
            except (TypeError, ValueError):
                price = 0
            try:
                sell_price = float(request.form.get(f'item_sell_price_{i}', 0) or 0)
            except (TypeError, ValueError):
                sell_price = 0
            if qty <= 0:
                continue
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
        p.total = total
        try:
            discount = float(request.form.get('discount', 0) or 0)
        except (TypeError, ValueError):
            discount = 0
        p.discount = discount
        net = max(0, total - discount)

        # حساب اللقطة التراكمية الثابتة (مثل فاتورة المبيعات):
        # previous_due = المستحق الفعلي للمورد قبل اضافة اجمالي امر الشراء الحالي
        # balance_after = previous_due + قيمة الفاتورة - دفعات فورية (كاش/مقدم)
        prev_due = _supplier_balance_before(p.supplier_id, p.date, exclude_id=p.id)
        p.previous_due = prev_due

        if payment_type == 'cash':
            p.paid_amount = net
            p.remaining = 0
            p.balance_after = max(0, prev_due + net - net)
        elif payment_type == 'credit':
            # الآجل: يمكن دفع مقدم نقدي عن المورد
            down = min(float(request.form.get('down_payment', 0) or 0), net)
            p.paid_amount = down
            p.remaining = max(0, net - down)
            p.balance_after = max(0, prev_due + net - down)
        elif payment_type == 'installment':
            down = min(float(request.form.get('down_payment', 0) or 0), net)
            p.paid_amount = down
            p.remaining = max(0, net - down)
            p.balance_after = max(0, prev_due + net - down)

            count = int(request.form.get('installment_count', 1) or 1)
            start_str = request.form.get('installment_start_date', '')
            if start_str:
                start_date = datetime.strptime(start_str, '%Y-%m-%d').date()
            else:
                start_date = date.today()

            remaining_amount = max(0, net - down)
            inst_amount = round(remaining_amount / count, 2) if count > 0 else remaining_amount

            plan = SupplierInstallmentPlan(
                supplier_id=p.supplier_id,
                purchase_id=p.id,
                plan_number=generate_supplier_plan_number(),
                total_amount=net,
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
    return_items = []
    for r in p.returns:
        return_items.extend(r.items)
    return_amount = sum(r.total_amount for r in p.returns)
    installment_plan = SupplierInstallmentPlan.query.filter_by(purchase_id=p.id).first()
    installments = installment_plan.installments if installment_plan else []
    installment_payments = installment_plan.payments if installment_plan else []
    sup = p.supplier
    # الدفعات التي تظهر داخل هذا الامر فقط: كل دفعة تظهر في آخر امر شراء
    # تم انشاؤه قبل تسجيلها (من تاريخ هذا الامر حتى انشاء امر الشراء التالي)
    supplier_payments = _purchase_window_payments(p)
    supp_total_paid = sum(pay.amount or 0 for pay in supplier_payments)
    supp_balance = sup.balance()

    # اللقطة التراكمية الثابتة (مثل فاتورة المبيعات)
    prev_saved = p.previous_due if p.previous_due is not None else 0
    after_saved = p.balance_after if p.balance_after is not None else 0
    if prev_saved == 0 and after_saved == 0:
        # fallback للفواتير القديمة المحسوبة يدوياً كمجموع تراكمي للمستحق
        sup_total = 0
        rem_this = 0
        prev_pur_old = Purchase.query.filter(
            Purchase.supplier_id == p.supplier_id,
            Purchase.id < p.id
        ).all()
        for pp in prev_pur_old:
            net = max(0, (pp.total or 0) - (pp.paid_amount or 0))
            sup_total += net
        this_net = max(0, (p.total or 0) - (p.paid_amount or 0))
        rem_this = this_net
        if sup_total > 0 or rem_this > 0:
            prev_saved = max(0, round(sup_total, 2))
            after_saved = max(0, round(sup_total + this_net, 2))

    return render_template('purchase_view.html', purchase=p,
        return_items=return_items, return_amount=return_amount,
        supplier_installment_plan=installment_plan, installments=installments,
        installment_payments=installment_payments, PAYMENT_TYPES=PAYMENT_TYPES,
        previous_dues=max(0, prev_saved), balance_after=max(0, after_saved),
        purchase_payments=p.payments,
        supplier_payments=supplier_payments,
        supp_total_paid=round(supp_total_paid, 2),
        supp_balance=round(supp_balance, 2))


@app.route('/purchases/<int:purchase_id>/edit', methods=['GET', 'POST'])
@login_required
def purchase_edit(purchase_id):
    p = Purchase.query.get_or_404(purchase_id)
    suppliers = Supplier.query.order_by(Supplier.name).all()

    if request.method == 'POST':
        p.modified_by = session.get('user_id')
        p.supplier_id = int(request.form['supplier_id'])
        payment_type = request.form.get('payment_type', 'cash')
        p.payment_type = payment_type
        p.show_balance = bool(request.form.get('show_balance'))
        if payment_type in ('cash', 'installment'):
            p.payment_method = request.form.get('payment_method', 'cash')
        else:
            p.payment_method = 'cash'
        new_images = save_receipt_images(request.files.getlist('receipt_images'))
        if new_images != '[]':
            existing = parse_images(p.receipt_image)
            p.receipt_image = json.dumps(existing + parse_images(new_images))
        p.notes = request.form.get('notes', '')

        # التحقق: لا يُسمح بصنف له كمية بدون سعر
        no_price_items = []
        indices_ = sorted({int(k.rsplit('_', 1)[1]) for k in request.form if k.startswith('item_name_')})
        for i in indices_:
            iname = request.form.get(f'item_name_{i}', '').strip()
            if not iname:
                continue
            try:
                qty = float(request.form.get(f'item_qty_{i}', 0) or 0)
            except (TypeError, ValueError):
                qty = 0
            try:
                price = float(request.form.get(f'item_price_{i}', 0) or 0)
            except (TypeError, ValueError):
                price = 0
            if qty > 0 and price <= 0:
                no_price_items.append(iname)
        if no_price_items:
            flash('لا يمكن حفظ امر الشراء: يوجد منتج بدون سعر (' + '، '.join(no_price_items) + ')', 'danger')
            return render_template('purchase_form.html', suppliers=suppliers, purchase=p,
                no_price=no_price_items, PAYMENT_TYPES=PAYMENT_TYPES,
                installment_plan=SupplierInstallmentPlan.query.filter_by(purchase_id=p.id).first())

        PurchaseItem.query.filter_by(purchase_id=p.id).delete()

        total = 0
        indices = sorted({int(k.rsplit('_', 1)[1]) for k in request.form if k.startswith('item_name_')})
        for i in indices:
            iname = request.form.get(f'item_name_{i}', '').strip()
            if not iname:
                continue
            try:
                qty = float(request.form.get(f'item_qty_{i}', 0) or 0)
            except (TypeError, ValueError):
                qty = 0
            try:
                price = float(request.form.get(f'item_price_{i}', 0) or 0)
            except (TypeError, ValueError):
                price = 0
            try:
                sell_price = float(request.form.get(f'item_sell_price_{i}', 0) or 0)
            except (TypeError, ValueError):
                sell_price = 0
            if qty <= 0:
                continue
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
        p.total = total
        try:
            discount = float(request.form.get('discount', 0) or 0)
        except (TypeError, ValueError):
            discount = 0
        p.discount = discount
        net = max(0, total - discount)

        plan_existing = SupplierInstallmentPlan.query.filter_by(purchase_id=p.id).first()

        if payment_type == 'cash':
            p.paid_amount = net
            p.remaining = 0
        elif payment_type == 'credit':
            # الآجل: السماح بتعديل المقدم النقدي للمورد
            want_down = min(float(request.form.get('down_payment', 0) or 0), net)
            p.paid_amount = want_down
            p.remaining = max(0, net - want_down)
        elif payment_type == 'installment':
            down = min(float(request.form.get('down_payment', 0) or 0), net)
            p.paid_amount = down
            p.remaining = max(0, net - down)

            count = int(request.form.get('installment_count', 1) or 1)
            start_str = request.form.get('installment_start_date', '')
            start_date = datetime.strptime(start_str, '%Y-%m-%d').date() if start_str else date.today()

            remaining_amount = max(0, net - down)
            inst_amount = round(remaining_amount / count, 2) if count > 0 else remaining_amount

            if not plan_existing:
                plan_existing = SupplierInstallmentPlan(
                    supplier_id=p.supplier_id,
                    purchase_id=p.id,
                    plan_number=generate_supplier_plan_number(),
                    total_amount=net,
                    down_payment=down,
                    installment_count=count,
                    installment_amount=inst_amount,
                    remaining=remaining_amount,
                    start_date=start_date,
                    status='active',
                    notes=p.notes
                )
                db.session.add(plan_existing)
                db.session.flush()

            SupplierInstallment.query.filter_by(plan_id=plan_existing.id).delete()

            plan_existing.total_amount = net
            plan_existing.down_payment = down
            plan_existing.installment_count = count
            plan_existing.installment_amount = inst_amount
            plan_existing.remaining = remaining_amount
            plan_existing.start_date = start_date

            for j in range(count):
                inst_date = start_date + relativedelta(months=j)
                inst = SupplierInstallment(
                    plan_id=plan_existing.id,
                    number=j + 1,
                    amount=inst_amount,
                    due_date=inst_date,
                    status='pending'
                )
                db.session.add(inst)

        # اعادة حساب اللقطة التراكمية الثابتة (مثل فاتورة المبيعات)
        cur_prev = p.previous_due if p.previous_due is not None else 0
        if cur_prev == 0:
            prev_pur_edit = Purchase.query.filter(
                Purchase.supplier_id == p.supplier_id,
                Purchase.id != p.id
            ).order_by(Purchase.id.desc()).first()
            cur_prev = (prev_pur_edit.balance_after if prev_pur_edit and prev_pur_edit.balance_after else 0) or 0
        p.previous_due = max(0, cur_prev)
        p.balance_after = max(0, round((p.previous_due or 0) + net - (p.paid_amount or 0), 2))

        # التحويل من تقسيط الي نقدي/آجل: حذف خطة التقسيط ان وجدت
        if payment_type != 'installment':
            plan_del = SupplierInstallmentPlan.query.filter_by(purchase_id=p.id).first()
            if plan_del:
                SupplierInstallmentPayment.query.filter_by(plan_id=plan_del.id).delete()
                SupplierInstallment.query.filter_by(plan_id=plan_del.id).delete()
                db.session.delete(plan_del)

        db.session.commit()
        EntityLock.query.filter_by(entity_type='supplier', entity_id=p.supplier_id, user_id=session['user_id']).delete()
        db.session.commit()
        flash(f'تم تعديل امر الشراء {p.purchase_number} بنجاح', 'success')
        return redirect(url_for('purchase_view', purchase_id=p.id))

    return render_template('purchase_form.html', suppliers=suppliers, purchase=p,
        PAYMENT_TYPES=PAYMENT_TYPES,
        installment_plan=SupplierInstallmentPlan.query.filter_by(purchase_id=p.id).first())


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
    SupplierReturnItem.query.filter(SupplierReturnItem.return_id.in_(
        db.session.query(SupplierReturn.id).filter_by(purchase_id=p.id)
    )).delete(synchronize_session='fetch')
    SupplierReturn.query.filter_by(purchase_id=p.id).delete()
    SupplierPayment.query.filter_by(purchase_id=p.id).update({'purchase_id': None})
    db.session.delete(p)
    db.session.commit()
    flash('تم حذف امر الشراء بنجاح', 'success')
    return redirect(url_for('purchases_list'))


@app.route('/purchases/<int:purchase_id>/image/<int:idx>/delete', methods=['POST'])
@login_required
def purchase_image_delete(purchase_id, idx):
    p = Purchase.query.get_or_404(purchase_id)
    images = parse_images(p.receipt_image)
    if 0 <= idx < len(images):
        delete_receipt_image(images[idx])
        images.pop(idx)
    p.receipt_image = json.dumps(images) if images else ''
    db.session.commit()
    flash('تم حذف الصورة بنجاح', 'success')
    # الرجوع لنفس الصفحة المصدر (عرض امر الشراء او نموذج التعديل)
    dest = request.args.get('dest', 'view')
    if dest == 'edit':
        return redirect(url_for('purchase_edit', purchase_id=purchase_id))
    return redirect(url_for('purchase_view', purchase_id=purchase_id))


@app.route('/payments/<int:payment_id>/receipt')
@login_required
def payment_receipt(payment_id):
    p = Payment.query.get_or_404(payment_id)
    c = p.customer
    bal_now = c.balance()
    dues_info = {'before': bal_now + p.amount, 'after': bal_now}
    return render_template('payment_receipt.html',
        doc_title='ايصال استلام دفعة',
        doc_number='RCV-%06d' % p.id,
        amount_label='المبلغ المستلم',
        party_label='العميل',
        party_name=c.name, party_phone=c.phone,
        amount=p.amount, pay_date=p.date,
        method_label=PAYMENT_METHODS.get(p.payment_method, 'كاش'),
        linked_label=None,
        linked_value=None,
        remaining_label='الرصيد المتبقي على العميل',
        remaining_value=c.balance(),
        notes=p.notes,
        receipt_image=p.receipt_image,
        creator=p.creator,
        dues_info=dues_info)


@app.route('/installment-payments/<int:payment_id>/receipt')
@login_required
def installment_payment_receipt(payment_id):
    p = InstallmentPayment.query.get_or_404(payment_id)
    plan = p.plan
    c = plan.customer
    bal_now = c.balance()
    dues_info = {'before': bal_now + p.amount, 'after': bal_now}
    return render_template('payment_receipt.html',
        doc_title='ايصال استلام قسط',
        doc_number='INS-%06d' % p.id,
        amount_label='المبلغ المستلم',
        party_label='العميل',
        party_name=c.name, party_phone=c.phone,
        amount=p.amount, pay_date=p.date,
        method_label=PAYMENT_METHODS.get(p.payment_method, 'كاش'),
        linked_label='خطة التقسيط',
        linked_value=plan.plan_number,
        remaining_label='المتبقي على الخطة',
        remaining_value=plan.remaining,
        notes=p.notes,
        receipt_image=p.receipt_image,
        creator=p.creator,
        dues_info=dues_info)


@app.route('/supplier-payments/<int:payment_id>/receipt')
@login_required
def supplier_payment_receipt(payment_id):
    p = SupplierPayment.query.get_or_404(payment_id)
    s = p.supplier
    return render_template('payment_receipt.html',
        doc_title='سند صرف دفعة',
        doc_number='PAY-%06d' % p.id,
        amount_label='المبلغ المدفوع',
        party_label='المورد',
        party_name=s.name, party_phone=s.phone,
        amount=p.amount, pay_date=p.date,
        method_label=PAYMENT_METHODS.get(p.payment_method, 'كاش'),
        linked_label='امر الشراء',
        linked_value=p.purchase.purchase_number if p.purchase else None,
        remaining_label='الرصيد المتبقي للمورد',
        remaining_value=max(0, s.balance()),
        notes=p.notes,
        receipt_image=p.receipt_image,
        creator=p.creator)


@app.route('/supplier-installment-payments/<int:payment_id>/receipt')
@login_required
def supplier_installment_payment_receipt(payment_id):
    p = SupplierInstallmentPayment.query.get_or_404(payment_id)
    plan = p.plan
    s = plan.supplier
    return render_template('payment_receipt.html',
        doc_title='سند صرف قسط',
        doc_number='SIP-%06d' % p.id,
        amount_label='المبلغ المدفوع',
        party_label='المورد',
        party_name=s.name, party_phone=s.phone,
        amount=p.amount, pay_date=p.date,
        method_label=PAYMENT_METHODS.get(p.payment_method, 'كاش'),
        linked_label='خطة التقسيط',
        linked_value=plan.plan_number,
        remaining_label='المتبقي على الخطة',
        remaining_value=plan.remaining,
        notes=p.notes,
        receipt_image=p.receipt_image,
        creator=p.creator)


@app.route('/items')
@login_required
def items_list():
    search = request.args.get('search', '').strip()

    purchased = dict(db.session.query(
        PurchaseItem.item_name,
        db.func.coalesce(db.func.sum(PurchaseItem.quantity), 0)
    ).group_by(PurchaseItem.item_name).all())

    sold = dict(db.session.query(
        InvoiceItem.item_name,
        db.func.coalesce(db.func.sum(InvoiceItem.quantity), 0)
    ).group_by(InvoiceItem.item_name).all())

    returned = dict(db.session.query(
        ReturnItem.item_name,
        db.func.coalesce(db.func.sum(ReturnItem.quantity), 0)
    ).group_by(ReturnItem.item_name).all())

    # استعلام واحد لجلب احدث سجل شراء لكل صنف (بدل استعلام لكل صنف)
    latest_ids = db.session.query(func.max(PurchaseItem.id)).group_by(PurchaseItem.item_name)
    latest_rows = (PurchaseItem.query.filter(PurchaseItem.id.in_(latest_ids))
                   .options(joinedload(PurchaseItem.purchase).joinedload(Purchase.supplier))
                   .all())
    latest_by_name = {pi.item_name: pi for pi in latest_rows}

    items = []
    for name in sorted(purchased.keys()):
        if search and search not in (name or ''):
            continue
        qty = (purchased.get(name, 0) or 0) - (sold.get(name, 0) or 0) + (returned.get(name, 0) or 0)
        if qty <= 0:
            continue
        pi = latest_by_name.get(name)
        items.append({
            'name': name,
            'qty': qty,
            'unit_type': (pi.unit_type if pi else None) or 'ق',
            'unit_price': (pi.unit_price if pi else None) or 0,
            'selling_price': (pi.selling_price if pi else None) or 0,
            'supplier': pi.purchase.supplier.name if pi and pi.purchase and pi.purchase.supplier else '—',
        })

    return render_template('items_list.html', items=items, search=search)


@app.route('/items/edit', methods=['GET', 'POST'])
@login_required
def items_edit():
    name = request.values.get('name', '').strip()
    if not name:
        return redirect(url_for('items_list'))

    latest_pi = PurchaseItem.query.filter(PurchaseItem.item_name == name).order_by(PurchaseItem.id.desc()).first()
    if not latest_pi:
        flash('الصنف غير موجود', 'danger')
        return redirect(url_for('items_list'))

    if request.method == 'POST':
        new_name = request.form.get('item_name', '').strip()
        unit_type = request.form.get('unit_type', latest_pi.unit_type or 'ق')
        unit_price = float(request.form.get('unit_price', 0) or 0)
        selling_price = float(request.form.get('selling_price', 0) or 0)

        if not new_name:
            flash('اسم الصنف مطلوب', 'danger')
            return redirect(url_for('items_edit', name=name))

        if new_name != name and PurchaseItem.query.filter(PurchaseItem.item_name == new_name).first():
            flash('يوجد صنف آخر بنفس الاسم، اختر اسماً مختلفاً', 'danger')
            return redirect(url_for('items_edit', name=name))

        if new_name != name:
            PurchaseItem.query.filter(PurchaseItem.item_name == name).update(
                {'item_name': new_name}, synchronize_session='fetch')
            InvoiceItem.query.filter(InvoiceItem.item_name == name).update(
                {'item_name': new_name}, synchronize_session='fetch')
            ReturnItem.query.filter(ReturnItem.item_name == name).update(
                {'item_name': new_name}, synchronize_session='fetch')

        # تعديل السعر والفئة على احدث سجل شراء فقط
        # فواتير البيع القديمة وسجلات الشراء التاريخية تبقى كما هي بدون اي تغيير
        latest_pi.unit_type = unit_type
        latest_pi.unit_price = unit_price
        latest_pi.selling_price = selling_price

        db.session.commit()
        flash(f'تم تعديل الصنف "{new_name}" بنجاح - الفواتير القديمة لم تتأثر', 'success')
        return redirect(url_for('items_list'))

    qty_purchased = db.session.query(db.func.coalesce(db.func.sum(PurchaseItem.quantity), 0)).filter(
        PurchaseItem.item_name == name).scalar()
    qty_sold = db.session.query(db.func.coalesce(db.func.sum(InvoiceItem.quantity), 0)).filter(
        InvoiceItem.item_name == name).scalar()
    qty_returned = db.session.query(db.func.coalesce(db.func.sum(ReturnItem.quantity), 0)).filter(
        ReturnItem.item_name == name).scalar()

    return render_template('item_edit.html',
        item=latest_pi,
        name=name,
        qty=max(0, (qty_purchased or 0) - (qty_sold or 0) + (qty_returned or 0)),
        supplier=latest_pi.purchase.supplier.name if latest_pi.purchase and latest_pi.purchase.supplier else '—')


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


@app.route('/guide')
@login_required
def user_guide():
    return render_template('guide.html')


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
    c = Customer.query.get(customer_id)
    if not c:
        return jsonify({'total_remaining': 0, 'invoices': []})
    result = []
    for inv in Invoice.query.filter(
        Invoice.customer_id == c.id,
        Invoice.is_returned == False
    ).order_by(Invoice.id).all():
        fixed_due = max(0, inv.balance_after or 0)
        if fixed_due > 0:
            result.append({
                'invoice_number': inv.invoice_number,
                'total': max(0, (inv.total or 0) - (inv.discount or 0)),
                'paid': inv.paid_amount or 0,
                'remaining': fixed_due
            })
    return jsonify({'total_remaining': round(max(0, c.balance()), 2), 'invoices': result})


@app.route('/api/supplier-balance')
@login_required
def api_supplier_balance():
    supplier_id = request.args.get('supplier_id', type=int)
    if not supplier_id:
        return jsonify({'total_remaining': 0, 'purchases': []})
    s = Supplier.query.get(supplier_id)
    if not s:
        return jsonify({'total_remaining': 0, 'purchases': []})
    result = []
    for pur in Purchase.query.filter_by(supplier_id=s.id).order_by(Purchase.id).all():
        fixed_due = max(0, pur.balance_after or 0)
        if fixed_due > 0:
            result.append({
                'purchase_number': pur.purchase_number,
                'total': max(0, (pur.total or 0) - (pur.discount or 0)),
                'paid': pur.paid_amount or 0,
                'remaining': fixed_due
            })
    return jsonify({'total_remaining': round(max(0, s.balance()), 2), 'purchases': result})


@app.route('/api/dashboard-data')
@login_required
def api_dashboard_data():
    # تجميع داخل قاعدة البيانات بدل تحميل كل السجلات في الذاكرة
    start = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    for _ in range(11):
        start = (start - timedelta(days=1)).replace(day=1)
    end = datetime.utcnow()

    rev_rows = db.session.query(
        func.strftime('%Y-%m', Invoice.date).label('ym'),
        func.coalesce(func.sum(Invoice.total), 0)
    ).filter(
        Invoice.is_returned == False, Invoice.date >= start, Invoice.date <= end
    ).group_by('ym').all()
    pay_rows = db.session.query(
        func.strftime('%Y-%m', Payment.date).label('ym'),
        func.coalesce(func.sum(Payment.amount), 0)
    ).filter(
        Payment.date >= start, Payment.date <= end
    ).group_by('ym').all()

    rev_map = dict(rev_rows)
    pay_map = dict(pay_rows)

    monthly_data = []
    now = datetime.utcnow()
    for i in range(11, -1, -1):
        month = now.month - i
        year = now.year
        if month <= 0:
            month += 12
            year -= 1
        key = f"{year}-{month:02d}"
        monthly_data.append({
            'month': key,
            'revenue': float(rev_map.get(key, 0) or 0),
            'paid': float(pay_map.get(key, 0) or 0),
        })
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
    customer_id = request.args.get('customer_id', '').strip()
    if not name:
        return jsonify({'found': False})

    # سعر مخصص حسب (العميل + الصنف): آخر سعر باعه هذا العميل لهذا الصنف
    if customer_id and customer_id.isdigit():
        cust_inv_item = InvoiceItem.query.join(Invoice).filter(
            Invoice.customer_id == int(customer_id),
            InvoiceItem.item_name == name
        ).order_by(InvoiceItem.id.desc()).first()
        if cust_inv_item and (cust_inv_item.unit_price or 0) > 0:
            return jsonify({
                'found': True,
                'selling_price': cust_inv_item.unit_price,
                'unit_price': cust_inv_item.unit_price,
                'source': 'customer'
            })

    # السعر العام الافتراضي من احدث أمر شراء
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


@app.route('/api/invoice-items')
@login_required
def api_invoice_items():
    invoice_id = request.args.get('invoice_id', '').strip()
    if not invoice_id or not invoice_id.isdigit():
        return jsonify([])
    inv = db.session.get(Invoice, int(invoice_id))
    if not inv:
        return jsonify([])
    return jsonify([
        {
            'item_name': it.item_name or '',
            'unit_type': it.unit_type or 'ق',
            'unit_price': it.unit_price or 0,
            'quantity': it.quantity or 0,
            'total': it.total or 0
        }
        for it in inv.items
    ])


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
