from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    full_name = db.Column(db.String(200))
    is_admin = db.Column(db.Boolean, default=False)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime)
    permissions = db.relationship('UserPermission', backref='user', lazy=True, cascade='all, delete-orphan')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def has_permission(self, page):
        if self.is_admin:
            return True
        return any(p.page == page for p in self.permissions)


class UserPermission(db.Model):
    __tablename__ = 'user_permissions'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    page = db.Column(db.String(50), nullable=False)


class EntityLock(db.Model):
    __tablename__ = 'entity_locks'
    id = db.Column(db.Integer, primary_key=True)
    entity_type = db.Column(db.String(20), nullable=False)
    entity_id = db.Column(db.Integer, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    locked_at = db.Column(db.DateTime, default=datetime.utcnow)
    heartbeat = db.Column(db.DateTime, default=datetime.utcnow)
    user = db.relationship('User', backref='locks_held')


class Customer(db.Model):
    __tablename__ = 'customers'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    phone = db.Column(db.String(50))
    address = db.Column(db.Text)
    account_type = db.Column(db.String(50), nullable=False, default='sales')
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    invoices = db.relationship('Invoice', backref='customer', lazy=True)
    payments = db.relationship('Payment', backref='customer', lazy=True)
    returns = db.relationship('Return', backref='customer', lazy=True)
    installment_plans = db.relationship('InstallmentPlan', backref='customer', lazy=True)

    def total_invoiced(self):
        # مجموع الفواتير غير المرتجعة (القيمة الصافية بعد الخصم)
        return sum((inv.total or 0) - (inv.discount or 0) for inv in self.invoices if not inv.is_returned)

    def total_paid(self):
        # الدفعات المسجلة (سجلات) + مبالغ الأقساط المدفوعة + المبالغ المدفوعة فوراً
        # عند إنشاء الفاتورة (كاش / مقدم تقسيط) —— بدون ازدواج
        sum_payments = sum(p.amount for p in self.payments)
        sum_inst = sum(ip.amount for ip in InstallmentPayment.query.filter(
            InstallmentPayment.plan_id.in_([pl.id for pl in self.installment_plans])
        ).all())
        # paid_amount على الفاتورة يمثل فقط المبلغ المدفوع فوراً عند الإنشاء
        sum_inv_paid = sum((inv.paid_amount or 0) for inv in self.invoices if not inv.is_returned)
        return sum_payments + sum_inst + sum_inv_paid

    def total_returns(self):
        return sum(r.total_amount for r in self.returns)

    def balance(self):
        return self.total_invoiced() - self.total_paid() - self.total_returns()

    def total_credit(self):
        return sum(inv.total for inv in self.invoices if not inv.is_returned and inv.payment_type == 'credit')

    def total_installment_plan_amount(self):
        return sum(plan.total_amount for plan in self.installment_plans)

    def total_installment_paid(self):
        return sum(p.amount for plan in self.installment_plans for p in plan.payments)

    def installment_remaining(self):
        return self.total_installment_plan_amount() - self.total_installment_paid()

    def total_installment_overdue(self):
        from datetime import date as dt_date
        today = dt_date.today()
        total = 0
        for plan in self.installment_plans:
            for inst in plan.installments:
                if inst.status == 'pending' and inst.due_date and inst.due_date < today:
                    total += inst.amount
        return total


class Invoice(db.Model):
    __tablename__ = 'invoices'
    id = db.Column(db.Integer, primary_key=True)
    invoice_number = db.Column(db.String(50), unique=True, nullable=False)
    customer_id = db.Column(db.Integer, db.ForeignKey('customers.id'), nullable=False)
    shipping_company = db.Column(db.String(200))
    total = db.Column(db.Float, default=0)
    discount = db.Column(db.Float, default=0)
    payment_type = db.Column(db.String(20), default='cash')
    paid_amount = db.Column(db.Float, default=0)
    remaining = db.Column(db.Float, default=0)
    date = db.Column(db.DateTime, default=datetime.utcnow)
    is_returned = db.Column(db.Boolean, default=False)
    show_balance = db.Column(db.Boolean, default=False)
    payment_method = db.Column(db.String(20), default='cash')
    receipt_image = db.Column(db.String(200))
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    creator = db.relationship('User', foreign_keys=[created_by])
    modified_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    modifier = db.relationship('User', foreign_keys=[modified_by])
    previous_due = db.Column(db.Float, default=0)
    balance_after = db.Column(db.Float, default=0)
    notes = db.Column(db.Text)
    items = db.relationship('InvoiceItem', backref='invoice', lazy=True, cascade='all, delete-orphan')
    returns = db.relationship('Return', backref='invoice', lazy=True)
    payments = db.relationship('Payment', backref='invoice', lazy=True)


class InvoiceItem(db.Model):
    __tablename__ = 'invoice_items'
    id = db.Column(db.Integer, primary_key=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey('invoices.id'), nullable=False)
    item_name = db.Column(db.String(300), nullable=False)
    unit_type = db.Column(db.String(10), nullable=False, default='ق')
    quantity = db.Column(db.Float, nullable=False, default=0)
    unit_price = db.Column(db.Float, nullable=False, default=0)
    total = db.Column(db.Float, nullable=False, default=0)


class Payment(db.Model):
    __tablename__ = 'payments'
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customers.id'), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    date = db.Column(db.DateTime, default=datetime.utcnow)
    invoice_id = db.Column(db.Integer, db.ForeignKey('invoices.id'), nullable=True)
    notes = db.Column(db.Text)
    next_payment_date = db.Column(db.Date, nullable=True)
    next_payment_amount = db.Column(db.Float, nullable=True)
    payment_method = db.Column(db.String(20), default='cash')
    receipt_image = db.Column(db.String(200))
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    creator = db.relationship('User', foreign_keys=[created_by])


class Return(db.Model):
    __tablename__ = 'returns'
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customers.id'), nullable=False)
    invoice_id = db.Column(db.Integer, db.ForeignKey('invoices.id'), nullable=True)
    total_amount = db.Column(db.Float, default=0)
    date = db.Column(db.DateTime, default=datetime.utcnow)
    reason = db.Column(db.Text)
    items = db.relationship('ReturnItem', backref='return_entry', lazy=True, cascade='all, delete-orphan')


class ReturnItem(db.Model):
    __tablename__ = 'return_items'
    id = db.Column(db.Integer, primary_key=True)
    return_id = db.Column(db.Integer, db.ForeignKey('returns.id'), nullable=False)
    item_name = db.Column(db.String(300), nullable=False)
    unit_type = db.Column(db.String(10), nullable=False, default='ق')
    quantity = db.Column(db.Float, nullable=False, default=0)
    unit_price = db.Column(db.Float, nullable=False, default=0)
    total = db.Column(db.Float, nullable=False, default=0)


class Supplier(db.Model):
    __tablename__ = 'suppliers'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    phone = db.Column(db.String(50))
    address = db.Column(db.Text)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    purchases = db.relationship('Purchase', backref='supplier', lazy=True)
    payments = db.relationship('SupplierPayment', backref='supplier', lazy=True)
    installment_plans = db.relationship('SupplierInstallmentPlan', backref='supplier', lazy=True)

    def total_purchased(self):
        return sum(p.total for p in self.purchases)

    def total_paid(self):
        # الدفعات المسجلة + مبالغ أقساط المورد المدفوعة + الدفع الفوري عند إنشاء أمر الشراء
        sum_payments = sum(p.amount for p in self.payments)
        sum_inst = sum(ip.amount for ip in SupplierInstallmentPayment.query.filter(
            SupplierInstallmentPayment.plan_id.in_([pl.id for pl in self.installment_plans])
        ).all())
        sum_pur_paid = sum((p.paid_amount or 0) for p in self.purchases)
        return sum_payments + sum_inst + sum_pur_paid

    def balance(self):
        return self.total_purchased() - self.total_paid()

    def total_credit(self):
        return sum(p.total for p in self.purchases if p.payment_type == 'credit')

    def total_installment_plan_amount(self):
        return sum(plan.total_amount for plan in self.installment_plans)

    def total_installment_paid(self):
        return sum(p.amount for plan in self.installment_plans for p in plan.payments)

    def installment_remaining(self):
        return self.total_installment_plan_amount() - self.total_installment_paid()

    def total_installment_overdue(self):
        from datetime import date as dt_date
        today = dt_date.today()
        total = 0
        for plan in self.installment_plans:
            for inst in plan.installments:
                if inst.status == 'pending' and inst.due_date and inst.due_date < today:
                    total += inst.amount
        return total


class Purchase(db.Model):
    __tablename__ = 'purchases'
    id = db.Column(db.Integer, primary_key=True)
    purchase_number = db.Column(db.String(50), unique=True, nullable=False)
    supplier_id = db.Column(db.Integer, db.ForeignKey('suppliers.id'), nullable=False)
    total = db.Column(db.Float, default=0)
    payment_type = db.Column(db.String(20), default='cash')
    payment_method = db.Column(db.String(20), default='cash')
    receipt_image = db.Column(db.String(200))
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    creator = db.relationship('User', foreign_keys=[created_by])
    paid_amount = db.Column(db.Float, default=0)
    remaining = db.Column(db.Float, default=0)
    date = db.Column(db.DateTime, default=datetime.utcnow)
    notes = db.Column(db.Text)
    items = db.relationship('PurchaseItem', backref='purchase', lazy=True, cascade='all, delete-orphan')
    payments = db.relationship('SupplierPayment', backref='purchase', lazy=True)


class PurchaseItem(db.Model):
    __tablename__ = 'purchase_items'
    id = db.Column(db.Integer, primary_key=True)
    purchase_id = db.Column(db.Integer, db.ForeignKey('purchases.id'), nullable=False)
    item_name = db.Column(db.String(300), nullable=False)
    unit_type = db.Column(db.String(10), nullable=False, default='ق')
    quantity = db.Column(db.Float, nullable=False, default=0)
    unit_price = db.Column(db.Float, nullable=False, default=0)
    selling_price = db.Column(db.Float, nullable=False, default=0)
    total = db.Column(db.Float, nullable=False, default=0)


class SupplierPayment(db.Model):
    __tablename__ = 'supplier_payments'
    id = db.Column(db.Integer, primary_key=True)
    supplier_id = db.Column(db.Integer, db.ForeignKey('suppliers.id'), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    date = db.Column(db.DateTime, default=datetime.utcnow)
    purchase_id = db.Column(db.Integer, db.ForeignKey('purchases.id'), nullable=True)
    notes = db.Column(db.Text)
    payment_method = db.Column(db.String(20), default='cash')
    receipt_image = db.Column(db.String(200))
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    creator = db.relationship('User', foreign_keys=[created_by])


class InstallmentPlan(db.Model):
    __tablename__ = 'installment_plans'
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customers.id'), nullable=False)
    invoice_id = db.Column(db.Integer, db.ForeignKey('invoices.id'), nullable=True)
    plan_number = db.Column(db.String(50), unique=True, nullable=False)
    total_amount = db.Column(db.Float, nullable=False, default=0)
    down_payment = db.Column(db.Float, default=0)
    installment_count = db.Column(db.Integer, nullable=False, default=1)
    installment_amount = db.Column(db.Float, nullable=False, default=0)
    remaining = db.Column(db.Float, nullable=False, default=0)
    start_date = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(20), default='active')
    notes = db.Column(db.Text)
    date = db.Column(db.DateTime, default=datetime.utcnow)
    installments = db.relationship('Installment', backref='plan', lazy=True, cascade='all, delete-orphan')
    payments = db.relationship('InstallmentPayment', backref='plan', lazy=True, cascade='all, delete-orphan')


class Installment(db.Model):
    __tablename__ = 'installments'
    id = db.Column(db.Integer, primary_key=True)
    plan_id = db.Column(db.Integer, db.ForeignKey('installment_plans.id'), nullable=False)
    number = db.Column(db.Integer, nullable=False)
    amount = db.Column(db.Float, nullable=False, default=0)
    due_date = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(20), default='pending')
    paid_date = db.Column(db.Date, nullable=True)
    notes = db.Column(db.Text)


class InstallmentPayment(db.Model):
    __tablename__ = 'installment_payments'
    id = db.Column(db.Integer, primary_key=True)
    plan_id = db.Column(db.Integer, db.ForeignKey('installment_plans.id'), nullable=False)
    installment_id = db.Column(db.Integer, db.ForeignKey('installments.id'), nullable=True)
    amount = db.Column(db.Float, nullable=False)
    date = db.Column(db.DateTime, default=datetime.utcnow)
    notes = db.Column(db.Text)
    payment_method = db.Column(db.String(20), default='cash')
    receipt_image = db.Column(db.String(200))
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    creator = db.relationship('User', foreign_keys=[created_by])


class SupplierInstallmentPlan(db.Model):
    __tablename__ = 'supplier_installment_plans'
    id = db.Column(db.Integer, primary_key=True)
    supplier_id = db.Column(db.Integer, db.ForeignKey('suppliers.id'), nullable=False)
    purchase_id = db.Column(db.Integer, db.ForeignKey('purchases.id'), nullable=True)
    plan_number = db.Column(db.String(50), unique=True, nullable=False)
    total_amount = db.Column(db.Float, nullable=False, default=0)
    down_payment = db.Column(db.Float, default=0)
    installment_count = db.Column(db.Integer, nullable=False, default=1)
    installment_amount = db.Column(db.Float, nullable=False, default=0)
    remaining = db.Column(db.Float, nullable=False, default=0)
    start_date = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(20), default='active')
    notes = db.Column(db.Text)
    date = db.Column(db.DateTime, default=datetime.utcnow)
    installments = db.relationship('SupplierInstallment', backref='plan', lazy=True, cascade='all, delete-orphan')
    payments = db.relationship('SupplierInstallmentPayment', backref='plan', lazy=True, cascade='all, delete-orphan')


class SupplierInstallment(db.Model):
    __tablename__ = 'supplier_installments'
    id = db.Column(db.Integer, primary_key=True)
    plan_id = db.Column(db.Integer, db.ForeignKey('supplier_installment_plans.id'), nullable=False)
    number = db.Column(db.Integer, nullable=False)
    amount = db.Column(db.Float, nullable=False, default=0)
    due_date = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(20), default='pending')
    paid_date = db.Column(db.Date, nullable=True)
    notes = db.Column(db.Text)


class SupplierInstallmentPayment(db.Model):
    __tablename__ = 'supplier_installment_payments'
    id = db.Column(db.Integer, primary_key=True)
    plan_id = db.Column(db.Integer, db.ForeignKey('supplier_installment_plans.id'), nullable=False)
    installment_id = db.Column(db.Integer, db.ForeignKey('supplier_installments.id'), nullable=True)
    amount = db.Column(db.Float, nullable=False)
    date = db.Column(db.DateTime, default=datetime.utcnow)
    notes = db.Column(db.Text)
    payment_method = db.Column(db.String(20), default='cash')
    receipt_image = db.Column(db.String(200))
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    creator = db.relationship('User', foreign_keys=[created_by])


class ShippingCompany(db.Model):
    __tablename__ = 'shipping_companies'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    phone = db.Column(db.String(50))
    contact_person = db.Column(db.String(200))
    address = db.Column(db.Text)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def total_shipments(self):
        return Invoice.query.filter_by(shipping_company=self.name).count()

    def total_shipped_value(self):
        from sqlalchemy import func
        result = db.session.query(func.sum(Invoice.total)).filter_by(shipping_company=self.name).scalar()
        return result or 0
