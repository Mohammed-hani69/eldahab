import os
import sys
sys.path.insert(0, os.path.dirname(__file__))

from app import app
from models import db, Customer, Invoice, InvoiceItem, Payment, Return, ReturnItem, Supplier, Purchase, PurchaseItem, SupplierPayment
from datetime import datetime, timedelta
import random
import math

def seed():
    with app.app_context():
        db.drop_all()
        db.create_all()

        # ============ العملاء - فنادق ============
        customers_data = [
            {'name': 'فندق ماريوت القاهرة', 'phone': '0227380000', 'address': 'القاهرة - التجمع الخامس', 'account_type': 'sales'},
            {'name': 'هيلتون رمسيس', 'phone': '0225770000', 'address': 'القاهرة - وسط البلد', 'account_type': 'sales'},
            {'name': 'انتركونتيننتال الاسكندرية', 'phone': '0354440000', 'address': 'اسكندرية - الشاطبي', 'account_type': 'sales'},
            {'name': 'فندق كينج ماري', 'phone': '0653330000', 'address': 'الجيزة - الدري', 'account_type': 'shipping'},
            {'name': 'هوليدي ان سيتي ستار', 'phone': '0228600000', 'address': 'القاهرة - مدينة نصر', 'account_type': 'travel'},
            {'name': 'نوفوتيل سيدي جابر', 'phone': '0693450000', 'address': 'اسكندرية - سيدي جابر', 'account_type': 'bab_al_sharriah'},
            {'name': 'فندق كابيتول جاردن', 'phone': '0863480000', 'address': 'المنصورة - شارع الجيش', 'account_type': 'sales'},
            {'name': 'فندق سانت ريجيس', 'phone': '0227355555', 'address': 'القاهرة - المعادي', 'account_type': 'shipping'},
            {'name': 'فندق بيت النيل', 'phone': '0483470000', 'address': 'الاقصر - شارع المحطة', 'account_type': 'sales'},
            {'name': 'ميزون جاردن', 'phone': '0823450000', 'address': 'اسوان - شارع الكورنيش', 'account_type': 'travel'},
            {'name': 'فندق لاجوند', 'phone': '0222670000', 'address': 'القاهرة - عابدين', 'account_type': 'bab_al_sharriah'},
            {'name': 'ريتز كارلتون', 'phone': '0225850000', 'address': 'القاهرة - التجمع الخامس', 'account_type': 'sales'},
            {'name': 'فندق سميراميس', 'phone': '0653110000', 'address': 'دمياط الجديدة - الكورنيش', 'account_type': 'sales'},
            {'name': 'بارك هيلتون', 'phone': '0483490000', 'address': 'مرسى مطروح', 'account_type': 'shipping'},
            {'name': 'فندق شرم ستار', 'phone': '0822480000', 'address': 'شرم الشيخ - خليج نعمة', 'account_type': 'sales'},
        ]

        customers = []
        for cd in customers_data:
            c = Customer(**cd)
            db.session.add(c)
            customers.append(c)
        db.session.flush()

        # ============ المنتجات - مستلزمات فنادق ============
        items_pool = [
            ('طقم حمام كامل', 1500, 4500),
            ('مناشف فنادق 500 جرام', 80, 200),
            ('ورق مفرش ابيض 300 متر', 350, 700),
            ('شامبو صغير 30 مل', 15, 40),
            ('لوشن جسم 30 مل', 18, 45),
            ('طقم اكواب سيراميك', 120, 300),
            ('畚 ماء استانلس ستيل', 250, 600),
            ('مصباح ديكور فنادق', 400, 1200),
            ('سجادة استقبال', 600, 1500),
            ('مفتاح باب الكتروني', 2500, 6000),
            ('نظافة مكتبية', 80, 200),
            ('طقم ملا فنادق', 1200, 3500),
            ('غطاء وسادة قطني', 45, 100),
            ('طقم شاي فنادق', 200, 500),
            ('الة قهوة كبيرة', 8000, 25000),
            ('ثلاجة بار', 5000, 15000),
            ('تكييف مركزي 3 حصان', 12000, 30000),
            ('كرسي استقبال جلد', 1500, 4000),
            ('مكتب استقبال خشب', 3000, 8000),
            ('تلفزيون ذكي 55 بوصة', 10000, 22000),
            ('طقم تراس فنادق', 800, 2000),
            ('مروحة سقف', 600, 1500),
            ('سخان مياه مركزي', 3000, 8000),
            ('طفاية حريق', 350, 700),
            ('سلة مهملات ستانلس', 150, 400),
            ('ستارة عازل للضوء', 400, 1000),
            ('حذاء نضيف ضيف', 25, 60),
            ('روب نضيف 350 جرام', 120, 280),
            ('مرآة حمام كبيرة', 300, 800),
            ('رف حمام استانلس', 200, 500),
        ]

        shipping_companies = ['شركة سمسا للشحن', 'شركة ارامكس', 'شركة جي ان تي', 'دي اتش ال مصر', '']
        invoices = []
        for i in range(25):
            cust = random.choice(customers[:10])
            days_ago = random.randint(1, 365)
            inv_date = datetime.utcnow() - timedelta(days=days_ago)
            inv = Invoice(
                invoice_number=f"INV-{i+1:06d}",
                customer_id=cust.id,
                shipping_company=random.choice(shipping_companies),
                date=inv_date,
                is_returned=False
            )
            db.session.add(inv)
            db.session.flush()
            total = 0
            num_items = random.randint(3, 12)
            selected = random.sample(items_pool, num_items)
            for item_name, low, high in selected:
                qty = random.randint(1, 20)
                price = random.randint(low, high)
                item_total = qty * price
                ii = InvoiceItem(
                    invoice_id=inv.id,
                    item_name=item_name,
                    quantity=qty,
                    unit_price=price,
                    total=item_total
                )
                db.session.add(ii)
                total += item_total
            inv.total = total
            invoices.append(inv)
        db.session.flush()

        # ============ المدفوعات ============
        for inv in invoices:
            if random.random() > 0.25:
                days_ago = random.randint(1, 250)
                p_date = datetime.utcnow() - timedelta(days=days_ago)
                pay_frac = random.uniform(0.2, 1.0)
                p = Payment(
                    customer_id=inv.customer_id,
                    amount=round(inv.total * pay_frac, 0),
                    date=p_date,
                    invoice_id=inv.id,
                    notes=random.choice(['دفعة كاش', 'تحويل بنكي', 'شيك', 'دفعة جزئية', '']),
                    next_payment_date=(datetime.utcnow() + timedelta(days=random.randint(7, 90))).date() if pay_frac < 1 else None,
                    next_payment_amount=round(inv.total * (1 - pay_frac), 0) if pay_frac < 1 else None
                )
                db.session.add(p)
        db.session.flush()

        # ============ المرتجعات ============
        for inv in invoices[:6]:
            days_ago = random.randint(1, 180)
            r_date = datetime.utcnow() - timedelta(days=days_ago)
            ret = Return(
                customer_id=inv.customer_id,
                invoice_id=inv.id,
                reason=random.choice(['عيب في المنتج', 'المقاس غلط', 'المنتج مختلف عن الطلب', 'تلف اثناء الشحن', 'العميل رفض الطلب']),
                date=r_date
            )
            db.session.add(ret)
            db.session.flush()
            total = 0
            ret_items = random.sample(list(inv.items), min(2, len(list(inv.items))))
            for ri in ret_items:
                qty = random.randint(1, min(ri.quantity, 5))
                rit = ReturnItem(
                    return_id=ret.id,
                    item_name=ri.item_name,
                    quantity=qty,
                    unit_price=ri.unit_price,
                    total=qty * ri.unit_price
                )
                db.session.add(rit)
                total += qty * ri.unit_price
            ret.total_amount = total
        db.session.flush()

        # ============ الموردين ============
        suppliers_data = [
            {'name': 'مصنع الملابس المصرية', 'phone': '0224400000', 'address': 'القاهرة - المرج', 'notes': 'مصنع مناشف ومفروشات فنادق'},
            {'name': 'شركة المستلزمات الفندقية', 'phone': '0334500000', 'address': 'اسكندرية - كفر الدوار', 'notes': 'مستلزمات فنادق ومطاعم'},
            {'name': 'مورد ادوات المطبخ', 'phone': '0222500000', 'address': 'القاهرة - التبة', 'notes': 'ادوات مطبخ فنادق'},
            {'name': 'شركة التجهيزات الفندقية', 'phone': '0502300000', 'address': '6 اكتوبر - المنطقة الصناعية', 'notes': 'تجهيزات فنادق كاملة'},
            {'name': 'المتحدة للاكسسوارات', 'phone': '0227900000', 'address': 'القاهرة - وسط البلد', 'notes': 'اكسسوارات وديكور فنادق'},
            {'name': 'شركة جولدن هوستل', 'phone': '0228100000', 'address': 'القاهرة - التجمع الخامس', 'notes': 'مستوردين من اوروبا'},
        ]

        suppliers = []
        for sd in suppliers_data:
            s = Supplier(**sd)
            db.session.add(s)
            suppliers.append(s)
        db.session.flush()

        # ============ المشتريات ============
        purchase_items_pool = [
            ('قماش مفروشات قطن 100%', 5000, 12000),
            ('شامبو ولوشن احجام صغيرة', 200, 600),
            ('مناشف قطن مصرى كبير', 60, 150),
            ('اكواب بورسلين فنادق', 80, 200),
            ('ادوات مطبخ استانلس', 1000, 4000),
            ('قلب باب الكتروني', 1500, 4000),
            ('سجادات استقبال', 400, 1000),
            ('ستائر عازلة', 300, 800),
            ('مفاتيح باب فنادق', 800, 2500),
            ('قميص نضيف فنادق', 30, 70),
            ('ادوات نظافة', 150, 400),
            ('سجادة موك', 2000, 5000),
        ]

        purchases = []
        for i in range(15):
            sup = random.choice(suppliers)
            days_ago = random.randint(1, 300)
            p_date = datetime.utcnow() - timedelta(days=days_ago)
            pur = Purchase(
                purchase_number=f"PUR-{i+1:06d}",
                supplier_id=sup.id,
                date=p_date,
                notes=random.choice(['طلبية عاجلة', 'شحن بحري', 'شحن جوي', ''])
            )
            db.session.add(pur)
            db.session.flush()
            total = 0
            num = random.randint(2, 7)
            sel = random.sample(purchase_items_pool, num)
            for iname, low, high in sel:
                qty = random.randint(10, 100)
                price = random.randint(low, high)
                sell_price = math.ceil(price * random.uniform(1.25, 1.80) / 5) * 5
                it = PurchaseItem(
                    purchase_id=pur.id,
                    item_name=iname,
                    quantity=qty,
                    unit_price=price,
                    selling_price=sell_price,
                    total=qty * price
                )
                db.session.add(it)
                total += qty * price
            pur.total = total
            purchases.append(pur)
        db.session.flush()

        # ============ مدفوعات الموردين ============
        for pur in purchases:
            if random.random() > 0.35:
                days_ago = random.randint(1, 200)
                sp = SupplierPayment(
                    supplier_id=pur.supplier_id,
                    amount=round(pur.total * random.uniform(0.15, 0.85), 0),
                    date=datetime.utcnow() - timedelta(days=days_ago),
                    notes=random.choice(['دفعة مقدمة', 'تسوية جزئية', 'تحويل بنكي', ''])
                )
                db.session.add(sp)
        db.session.flush()

        db.session.commit()

        print("=" * 50)
        print("  El Dahab Trading - Hotel Supplies System")
        print("=" * 50)
        print(f"  العملاء:          {Customer.query.count()}")
        print(f"  الفواتير:         {Invoice.query.count()}")
        print(f"  المدفوعات:        {Payment.query.count()}")
        print(f"  المرتجعات:        {Return.query.count()}")
        print(f"  الموردين:         {Supplier.query.count()}")
        print(f"  المشتريات:        {Purchase.query.count()}")
        print(f"  مدفوعات الموردين: {SupplierPayment.query.count()}")
        print("=" * 50)

if __name__ == '__main__':
    seed()
