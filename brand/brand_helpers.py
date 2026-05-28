from django.db.models import Sum
import graphene

from saleor.brand.models import Brand, BrandPayout, Arrear
from saleor.utilities.time_utilities import TimeUtilities
from saleor.external_services.mail.mail_impl import MailImpl
from saleor.order.models import OrderLine
from .states import ArrearTypeEnum

class BrandAging:
    def get_header():
        header = ['brand_name', 'brand_id', 'created_at', 'brand_source', 'status', '>01-3 Months', '>3-6 Months', '>6-12 Months', '>One Year', 'Not Due', 'Grand Total', '_', 'Arrear']
        return header
    
    def get_all_durations():
        durations = ['>01-3 Months', '>3-6 Months', '>6-12 Months', '>One Year', 'Not Due', 'Grand Total']
        return durations
    
    def get_duration(days):
        if days < 30:
            return "Not Due"
        if days < 90:
            return ">01-3 Months"
        if days < 180:
            return ">3-6 Months"
        if days < 360:
            return ">6-12 Months"
        return ">One Year"
    
    def get_brand_due_amount():
        today = TimeUtilities().get_today_start()
        release_date = '2022-01-04'
        orders = OrderLine.objects.exclude(metadata__fake__isnull=False, metadata__fake='true').filter(order__created__gt=release_date, order__created__lt=today).values('brand__brand_name', 'order__created', 'metadata__brand_due_amount')
        
        brand_rows = dict()
        for order in orders:
            row = dict()
            days = (today - order['order__created']).days

            row['brand_name'] = order['brand__brand_name']
            row['due_amount'] = order['metadata__brand_due_amount']
            row['duration'] = BrandAging.get_duration(days)

            if not row['brand_name'] in brand_rows:
                brand_rows[row['brand_name']] = []
            brand_rows[row['brand_name']].append(row)

        return brand_rows

    def get_brand_payout():
        today = TimeUtilities().get_today_start()
        payouts = BrandPayout.objects.filter(date__lt=today).values('brand__brand_name', 'date', 'amount')
        payout_rows = dict()
        for payout in payouts:
            row = dict()
            days = (today - payout['date']).days

            row['brand_name'] = payout['brand__brand_name']
            row['amount'] = payout['amount']
            row['duration'] = BrandAging.get_duration(days)

            if not row['brand_name'] in payout_rows:
                payout_rows[row['brand_name']] = []
            payout_rows[row['brand_name']].append(row)

        brand_payout = dict()
        for brand_name, rows in payout_rows.items():
            if not brand_name in brand_payout:
                brand_payout[brand_name] = dict()
                for duration in BrandAging.get_all_durations():
                    brand_payout[brand_name][duration] = 0.0

            for row in rows:
                amount = float(row['amount'])
                duration = row['duration']
                brand_payout[brand_name][duration] += amount
                brand_payout[brand_name]['Grand Total'] += amount

        return brand_payout

    def get_brand_total():
        brand_rows = BrandAging.get_brand_due_amount()
        brand_payout = BrandAging.get_brand_payout()
        brand_total = dict()
        for brand_name, rows in brand_rows.items():
            if not brand_name in brand_total:
                brand_total[brand_name] = dict()
                for duration in BrandAging.get_all_durations():
                    brand_total[brand_name][duration] = -brand_payout.get(brand_name, {}).get(duration, 0.0)
                    
            for row in rows:
                due_amount = float(row['due_amount'])
                duration = row['duration']

                brand_total[brand_name][duration] += due_amount
                brand_total[brand_name]['Grand Total'] += due_amount

        return brand_total

    def get_rows():
        brand_total = BrandAging.get_brand_total()
        brands = Brand.objects.all().values('id', 'brand_name', 'created_at', 'brand_source', 'status')
        brands = {brand['brand_name']: brand for brand in brands}

        brand_arr = Arrear.objects.filter(brand__brand_name__in=brands).filter(arrear_type=ArrearTypeEnum.BRAND)\
                    .values('brand__brand_name').order_by('brand__brand_name').annotate(arrear_amount=Sum('amount'))    
        arrear = {brand_arrear['brand__brand_name']: brand_arrear['arrear_amount'] for brand_arrear in brand_arr}
        
        grand_total = dict()
        for duration in BrandAging.get_all_durations():
            grand_total[duration] = 0.0

        rows = []
        for brand_name, due_amount in brand_total.items():
            row = brands.get(brand_name)
            brand_gid = graphene.Node.to_global_id('Brand', row.pop('id'))
            row['brand_id'] = brand_gid
            for duration in BrandAging.get_all_durations():
                grand_total[duration] += due_amount.get(duration, 0)
                row[duration] = "{0:.2f}".format(due_amount.get(duration, 0))
            row['Arrear'] = "{0:.2f}".format(arrear.get(row['brand_name'], 0))
            rows.append(row)

        row = dict()
        for duration in BrandAging.get_all_durations():
            row[duration] = "{0:.2f}".format(grand_total.get(duration, 0))
        rows.append(row)
        
        return rows

    def send_email(recipient_email=None):
        if not recipient_email:
            recipient_email = 'pradeep@zaamo.co'
            
        mail = MailImpl()
        rows = BrandAging.get_rows()
        header = BrandAging.get_header()
        attachment = mail.get_csv_attachment_dict(filename='Brand aging.csv', rows=rows, fieldnames=header)
        mail.send_mail_with_attachment('brand_ledger_csv', 'Hi, PFA\n', 'Brand Aging Report', [attachment], recipient_email=recipient_email)